import {
  lazy,
  memo,
  Suspense,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState
} from 'react';
import { AnimatePresence, motion, useReducedMotion } from 'motion/react';
import { code } from '@streamdown/code';
import {
  AlertTriangle,
  Brain,
  Check,
  CircleCheck,
  ChevronDown,
  CircleDashed,
  CircleEllipsis,
  Copy,
  RotateCcw,
  Wrench
} from 'lucide-react';
import { Loader } from '@/components/ai-elements/loader';
import { Shimmer } from '@/components/ai-elements/shimmer';
import { Terminal } from '@/components/ai-elements/terminal';
import {
  Message,
  MessageAction,
  MessageActions,
  MessageContent,
  MessageResponse
} from '@/components/ai-elements/message';
import {
  ChainOfThought,
  ChainOfThoughtContent,
  ChainOfThoughtHeader,
  ChainOfThoughtStep
} from '@/components/ai-elements/chain-of-thought';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger
} from '@/components/ui/tooltip';
import { Task, TaskTrigger } from '@/components/ai-elements/task';
import { cn } from '@/lib/utils';
import {
  type CopyMeta,
  areMessagesEqual,
  getToolChangeDisplayState,
  getToolTitleHighlightText,
  getToolTitle,
  getToolTitleTooltip,
  groupMessageParts,
  shouldRenderToolDiffContent,
  shouldRenderMessagePartsInOriginalOrder,
  toShellMarkdown
} from '@/business/thread-chat/thread-chat-message-utils';
import {
  type ThreadChatDisplayMessage,
  type ThreadChatPart
} from '@/business/thread-chat/types';
import { useStickToBottomContext } from 'use-stick-to-bottom';

const ThreadChatDiffViewer = lazy(async () => {
  const module = await import('@/business/thread-chat/thread-chat-diff-viewer');
  return { default: module.ThreadChatDiffViewer };
});

type ThreadChatMessageItemProps = {
  message: ThreadChatDisplayMessage;
  isCurrentStreaming: boolean;
  isThinking?: boolean;
  isLatestResponding?: boolean;
  copyMeta: CopyMeta;
  disableCopy?: boolean;
  compactToolView?: boolean;
  onResetEnvironmentInitialization?: () => void | Promise<void>;
  isEnvironmentResetting?: boolean;
};

type ToolPart = Extract<ThreadChatPart, { type: 'tool' }>;
type EnvironmentPart = Extract<ThreadChatPart, { type: 'environment' }>;
type ToolPlanStep = {
  step: string;
  status: 'pending' | 'in_progress' | 'completed' | string;
};

const hasEnvironmentParts = (message: ThreadChatDisplayMessage) =>
  message.parts.some((part) => part.type === 'environment');

const TURN_FAILURE_PREFIX = '本轮请求失败：';
const isTurnFailureContent = (content: string) =>
  content.trim().startsWith(TURN_FAILURE_PREFIX);

const ENV_STEP_BADGE_VARIANT: Record<
  EnvironmentPart['steps'][number]['status'],
  'outline' | 'secondary' | 'destructive'
> = {
  pending: 'outline',
  running: 'secondary',
  success: 'secondary',
  skipped: 'outline',
  error: 'destructive'
};

const ENV_STEP_STATUS_TEXT: Record<
  EnvironmentPart['steps'][number]['status'],
  string
> = {
  pending: '等待中',
  running: '进行中',
  success: '完成',
  skipped: '跳过',
  error: '失败'
};

const ThreadChatEnvironmentInitCard = ({
  part,
  onResetEnvironmentInitialization,
  isEnvironmentResetting = false
}: {
  part: EnvironmentPart;
  onResetEnvironmentInitialization?: () => void | Promise<void>;
  isEnvironmentResetting?: boolean;
}) => {
  const hasContainerOrRepoError = part.steps.some(
    (step) =>
      (step.key === 'container' || step.key === 'repo') &&
      step.status === 'error'
  );
  const canReset =
    part.status !== 'running' &&
    hasContainerOrRepoError &&
    Boolean(onResetEnvironmentInitialization);

  return (
    <Card className="w-full gap-3 py-3" style={{ boxShadow: 'none' }}>
      <CardHeader className="pb-0 px-0 flex flex-row items-center justify-between gap-2">
        <CardTitle className="text-sm">{part.title}</CardTitle>
        {canReset && (
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={isEnvironmentResetting}
            onClick={() => {
              void onResetEnvironmentInitialization?.();
            }}
          >
            <RotateCcw className="size-3.5" />
            {isEnvironmentResetting ? '重置中...' : '重置初始化'}
          </Button>
        )}
      </CardHeader>
      <CardContent className="px-0 space-y-2 border-0! shadow-none!">
        <div className="flex flex-wrap items-center gap-2">
          {part.steps.map((step) => (
            <Badge key={step.key} variant={ENV_STEP_BADGE_VARIANT[step.status]}>
              {step.title} · {ENV_STEP_STATUS_TEXT[step.status]}
            </Badge>
          ))}
        </div>
        <Terminal
          autoScroll
          className="w-full rounded-md"
          isStreaming={part.status === 'running'}
          output={part.output}
        />
      </CardContent>
    </Card>
  );
};

const ThreadChatToolTaskItem = ({ part }: { part: ToolPart }) => {
  const { stopScroll } = useStickToBottomContext();
  const reduceMotion = useReducedMotion();
  const [open, setOpen] = useState(false);
  const parsedPlan = useMemo(() => {
    if (part.toolName !== 'update_plan') return undefined;
    const raw = part.content?.trim();
    if (!raw || !raw.startsWith('{')) return undefined;

    try {
      const payload = JSON.parse(raw) as {
        active_step?: unknown;
        explanation?: unknown;
        plan?: unknown;
        details?: {
          active_step?: unknown;
          explanation?: unknown;
          plan?: unknown;
        };
      };
      const container =
        payload.details && typeof payload.details === 'object'
          ? payload.details
          : payload;

      const rawPlan = Array.isArray(container.plan) ? container.plan : [];
      const plan: ToolPlanStep[] = rawPlan
        .filter(
          (item): item is { step?: unknown; status?: unknown } =>
            typeof item === 'object' && item != null
        )
        .map((item) => ({
          step: typeof item.step === 'string' ? item.step.trim() : '',
          status:
            typeof item.status === 'string' ? item.status.trim() : 'pending'
        }))
        .filter((item) => item.step.length > 0);
      if (plan.length === 0) return undefined;

      return {
        activeStep:
          typeof container.active_step === 'string'
            ? container.active_step.trim()
            : '',
        explanation:
          typeof container.explanation === 'string'
            ? container.explanation.trim()
            : '',
        plan
      };
    } catch {
      return undefined;
    }
  }, [part.content, part.toolName]);
  const planProgressLabel = useMemo(() => {
    if (part.toolName !== 'update_plan' || !parsedPlan) return '';

    const hasPlan = parsedPlan.plan.length > 0;
    const isCompleted =
      hasPlan && parsedPlan.plan.every((item) => item.status === 'completed');
    if (isCompleted) return '已完成';

    if (parsedPlan.activeStep.trim())
      return `当前: ${parsedPlan.activeStep.trim()}`;
    const inProgressStep = parsedPlan.plan.find(
      (item) => item.status === 'in_progress'
    );
    if (inProgressStep?.step?.trim())
      return `当前: ${inProgressStep.step.trim()}`;
    return '';
  }, [parsedPlan, part.toolName]);

  const renderPlanStatusIcon = (status: ToolPlanStep['status']) => {
    if (status === 'completed') {
      return <CircleCheck className="size-4 text-emerald-600" />;
    }
    if (status === 'in_progress') {
      return <CircleEllipsis className="size-4 text-blue-600" />;
    }
    return <CircleDashed className="size-4 text-muted-foreground" />;
  };

  const renderPlanStatusText = (status: ToolPlanStep['status']) => {
    if (status === 'completed') return '已完成';
    if (status === 'in_progress') return '进行中';
    return '待处理';
  };
  const toolStatusLabel =
    part.status === 'running'
      ? '执行中'
      : part.status === 'error'
        ? '执行失败'
        : '执行成功';
  const toolStatusBadgeVariant =
    part.status === 'error' ? 'destructive' : 'outline';
  const toolChangeDisplay = getToolChangeDisplayState(part);
  const shouldRenderDiffContent = shouldRenderToolDiffContent(part);
  const toolTitle = getToolTitle(part.toolName, part.toolInvocation);
  const toolTitleHighlightText = getToolTitleHighlightText(
    part.toolName,
    part.toolInvocation
  );
  const toolTitleTooltip = getToolTitleTooltip(
    part.toolName,
    part.toolInvocation
  );
  const highlightedTitleContent = useMemo(() => {
    if (!toolTitleHighlightText || !toolTitle.includes(toolTitleHighlightText)) {
      return toolTitle;
    }

    const highlightStart = toolTitle.indexOf(toolTitleHighlightText);
    if (highlightStart < 0) return toolTitle;

    const prefix = toolTitle.slice(0, highlightStart);
    const suffix = toolTitle.slice(highlightStart + toolTitleHighlightText.length);

    return (
      <>
        {prefix}
        {toolTitleTooltip ? (
          <TooltipProvider>
            <Tooltip disableHoverableContent>
              <TooltipTrigger asChild>
                <span className="inline rounded-sm text-foreground/85 decoration-foreground/40 underline-offset-2 transition-all hover:text-foreground hover:underline">
                  {toolTitleHighlightText}
                </span>
              </TooltipTrigger>
              <TooltipContent className="pointer-events-none max-w-none" side="top">
                <p className="whitespace-nowrap">{toolTitleTooltip}</p>
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>
        ) : (
          <span className="rounded-sm text-foreground/85 decoration-foreground/40 underline-offset-2 transition-all hover:text-foreground hover:underline">
            {toolTitleHighlightText}
          </span>
        )}
        {suffix}
      </>
    );
  }, [toolTitle, toolTitleHighlightText, toolTitleTooltip]);

  return (
    <Task
      className="w-full"
      defaultOpen={false}
      onOpenChange={(nextOpen) => {
        stopScroll();
        setOpen(nextOpen);
      }}
      open={open}
    >
      <TaskTrigger
        className="w-full"
        title={toolTitleTooltip ?? part.toolInvocation?.trim() ?? toolTitle}
      >
        {(() => {
          const content = (
            <div className="group/tool-row flex max-w-max cursor-pointer items-center gap-4 text-sm text-muted-foreground">
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm">{highlightedTitleContent}</p>
              </div>
              {planProgressLabel ? (
                <span className="max-w-[20rem] truncate text-xs text-muted-foreground">
                  {planProgressLabel}
                </span>
              ) : null}
              {toolChangeDisplay.showAdded && (
                <span className="shrink-0 text-xs font-medium text-emerald-600">
                  +{toolChangeDisplay.added}
                </span>
              )}
              {toolChangeDisplay.showRemoved && (
                <span className="shrink-0 text-xs font-medium text-red-600">
                  -{toolChangeDisplay.removed}
                </span>
              )}
              <ChevronDown
                className={cn(
                  'size-4 shrink-0 opacity-0 transition-all group-hover/tool-row:opacity-100',
                  open ? 'rotate-180 opacity-100' : undefined
                )}
              />
            </div>
          );

          if (part.status === 'running') {
            return <Shimmer className="block w-full">{content}</Shimmer>;
          }

          return content;
        })()}
      </TaskTrigger>
      <AnimatePresence initial={false}>
        {open ? (
          <motion.div
            animate={{ opacity: 1, y: 0 }}
            className="overflow-hidden"
            exit={{ opacity: 0, y: -4 }}
            initial={{ opacity: 0, y: -4 }}
            key={`${part.toolCallId ?? part.toolName}-content`}
            transition={
              reduceMotion
                ? { duration: 0 }
                : {
                    opacity: { duration: 0.16, ease: 'easeOut' },
                    y: { duration: 0.16, ease: [0.22, 1, 0.36, 1] }
                  }
            }
          >
            <div className="mt-4 space-y-2 border-muted border-l-2 pl-4">
              {shouldRenderDiffContent ? (
                <div className="mt-2">
                  <Suspense
                    fallback={
                      <div className="flex min-h-24 items-center gap-2 rounded-md border bg-muted/30 px-3 py-2 text-sm text-muted-foreground">
                        <Loader size={14} />
                        <span>正在加载 diff 详情...</span>
                      </div>
                    }
                  >
                  <ThreadChatDiffViewer
                      filePath={part.toolInvocation}
                      newValue={part.diffNewValue}
                      oldValue={part.diffOldValue}
                      diffLineMode={part.diffLineMode}
                      diffLineOffset={part.diffLineOffset}
                      diffHunks={part.diffHunks}
                      diffSections={part.diffSections}
                    />
                  </Suspense>
                </div>
              ) : part.toolName === 'update_plan' && parsedPlan ? (
                <Card className="mt-2 w-full gap-2 py-3">
                  <CardHeader className="px-3 pb-0">
                    <CardTitle className="text-sm">计划更新</CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-3 px-3">
                    {parsedPlan.explanation ? (
                      <p className="text-sm text-muted-foreground">
                        {parsedPlan.explanation}
                      </p>
                    ) : null}
                    <div className="space-y-2">
                      {parsedPlan.plan.map((item, index) => {
                        const isActive =
                          parsedPlan.activeStep.length > 0 &&
                          parsedPlan.activeStep === item.step;
                        return (
                          <div
                            className={cn(
                              'flex items-center justify-between gap-3 rounded-md border px-3 py-2',
                              isActive
                                ? 'border-blue-300 bg-blue-50/70'
                                : 'border-border'
                            )}
                            key={`${item.step}-${index}`}
                          >
                            <div className="flex min-w-0 items-center gap-2">
                              {renderPlanStatusIcon(item.status)}
                              <span className="truncate text-sm">{item.step}</span>
                            </div>
                            <Badge variant="outline">
                              {renderPlanStatusText(item.status)}
                            </Badge>
                          </div>
                        );
                      })}
                    </div>
                  </CardContent>
                </Card>
              ) : (
                <div className="mt-2 space-y-2">
                  <div className="flex items-center gap-2">
                    <Badge variant={toolStatusBadgeVariant}>{toolStatusLabel}</Badge>
                  </div>
                  {part.content.trim() ? (
                    <MessageResponse plugins={{ code }}>
                      {toShellMarkdown(part.content)}
                    </MessageResponse>
                  ) : null}
                </div>
              )}
            </div>
          </motion.div>
        ) : null}
      </AnimatePresence>
    </Task>
  );
};

const readEnvInt = (
  rawValue: string | undefined,
  fallback: number,
  min: number,
  max: number
): number => {
  if (!rawValue) return fallback;
  const parsed = Number.parseInt(rawValue, 10);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.min(Math.max(parsed, min), max);
};

const THREAD_CHAT_MESSAGE_ITEM_ENV = import.meta.env ?? {};

const STREAM_SMOOTHING_CONFIG = {
  intervalMs: readEnvInt(
    THREAD_CHAT_MESSAGE_ITEM_ENV.VITE_STREAM_SMOOTHING_INTERVAL_MS,
    22,
    8,
    60
  ),
  smallChunkSize: readEnvInt(
    THREAD_CHAT_MESSAGE_ITEM_ENV.VITE_STREAM_SMOOTHING_CHUNK_SMALL,
    1,
    1,
    6
  ),
  mediumChunkSize: readEnvInt(
    THREAD_CHAT_MESSAGE_ITEM_ENV.VITE_STREAM_SMOOTHING_CHUNK_MEDIUM,
    2,
    1,
    8
  ),
  largeChunkSize: readEnvInt(
    THREAD_CHAT_MESSAGE_ITEM_ENV.VITE_STREAM_SMOOTHING_CHUNK_LARGE,
    3,
    1,
    10
  ),
  mediumThreshold: readEnvInt(
    THREAD_CHAT_MESSAGE_ITEM_ENV.VITE_STREAM_SMOOTHING_MEDIUM_THRESHOLD,
    16,
    4,
    120
  ),
  largeThreshold: readEnvInt(
    THREAD_CHAT_MESSAGE_ITEM_ENV.VITE_STREAM_SMOOTHING_LARGE_THRESHOLD,
    48,
    8,
    400
  )
} as const;

const getStreamChunkSize = (remainingChars: number): number => {
  if (remainingChars > STREAM_SMOOTHING_CONFIG.largeThreshold) {
    return STREAM_SMOOTHING_CONFIG.largeChunkSize;
  }
  if (remainingChars > STREAM_SMOOTHING_CONFIG.mediumThreshold) {
    return STREAM_SMOOTHING_CONFIG.mediumChunkSize;
  }
  return STREAM_SMOOTHING_CONFIG.smallChunkSize;
};

const StreamingBufferedResponse = ({ text }: { text: string }) => {
  const [visibleText, setVisibleText] = useState(text);
  const targetTextRef = useRef(text);
  const visibleTextRef = useRef(text);
  const timerRef = useRef<number | null>(null);

  useEffect(() => {
    targetTextRef.current = text;
    if (timerRef.current != null) {
      window.clearTimeout(timerRef.current);
      timerRef.current = null;
    }

    const currentVisibleText = visibleTextRef.current;
    const isCompatibleAppend = text.startsWith(currentVisibleText);

    if (!isCompatibleAppend) {
      timerRef.current = window.setTimeout(() => {
        visibleTextRef.current = text;
        setVisibleText(text);
      }, 0);
      return () => {
        if (timerRef.current != null) {
          window.clearTimeout(timerRef.current);
          timerRef.current = null;
        }
      };
    }

    const flushNextChunk = () => {
      const current = visibleTextRef.current;
      const target = targetTextRef.current;
      if (!target.startsWith(current) || current.length >= target.length) {
        return;
      }

      const remaining = target.length - current.length;
      const chunkSize = getStreamChunkSize(remaining);
      const next = target.slice(0, current.length + chunkSize);

      visibleTextRef.current = next;
      setVisibleText(next);

      if (next.length < target.length) {
        timerRef.current = window.setTimeout(
          flushNextChunk,
          STREAM_SMOOTHING_CONFIG.intervalMs
        );
      }
    };

    if (text.length > currentVisibleText.length) {
      timerRef.current = window.setTimeout(flushNextChunk, 0);
    }

    return () => {
      if (timerRef.current != null) {
        window.clearTimeout(timerRef.current);
        timerRef.current = null;
      }
    };
  }, [text]);

  return (
    <MessageResponse
      className="response-stream-gradient"
      isAnimating={false}
      mode="static"
    >
      {visibleText}
    </MessageResponse>
  );
};

export const ThreadChatMessageItem = memo(
  ({
    message,
    isCurrentStreaming,
    isThinking = false,
    isLatestResponding = false,
    copyMeta,
    disableCopy = false,
    compactToolView = false,
    onResetEnvironmentInitialization,
    isEnvironmentResetting = false
  }: ThreadChatMessageItemProps) => {
    const groupedParts = useMemo(
      () => groupMessageParts(message.parts),
      [message.parts]
    );
    const hasEnvironmentPart = groupedParts.environments.length > 0;
    const shouldRenderAssistantPartsInOrder =
      shouldRenderMessagePartsInOriginalOrder(message);
    const lastContentPartId = useMemo(() => {
      for (let index = message.parts.length - 1; index >= 0; index -= 1) {
        const part = message.parts[index];
        if (part?.type === 'content') return part.id;
      }
      return undefined;
    }, [message.parts]);
    const messageFrom = message.role === 'tool' ? 'assistant' : message.role;
    const [isCopied, setIsCopied] = useState(false);
    const copyResetTimerRef = useRef<number | null>(null);

    const handleCopyMessage = useCallback(async () => {
      if (isCurrentStreaming || disableCopy) return;
      if (typeof window === 'undefined' || !navigator?.clipboard?.writeText) {
        return;
      }

      const copyText = copyMeta.copyText.trim();
      if (!copyText) return;

      await navigator.clipboard.writeText(copyText);
      setIsCopied(true);
      if (copyResetTimerRef.current != null) {
        window.clearTimeout(copyResetTimerRef.current);
      }
      copyResetTimerRef.current = window.setTimeout(() => {
        setIsCopied(false);
        copyResetTimerRef.current = null;
      }, 1200);
    }, [copyMeta.copyText, disableCopy, isCurrentStreaming]);
    const shouldShowRespondingStatus =
      messageFrom === 'assistant' && isLatestResponding;
    const canShowCopyAction =
      copyMeta.canCopy &&
      !isCurrentStreaming &&
      !disableCopy &&
      !shouldShowRespondingStatus;
    const shouldShowActionRow = canShowCopyAction || shouldShowRespondingStatus;

    return (
      <Message className="gap-4" from={messageFrom}>
        <MessageContent
          className={messageFrom === 'assistant' ? 'w-full gap-4' : undefined}
        >
          {compactToolView &&
            message.role === 'tool' &&
            groupedParts.tools.map((part) => {
              const toolChangeDisplay = getToolChangeDisplayState(part);

              return (
                <div
                  className="flex max-w-max items-center gap-2 text-muted-foreground text-sm"
                  key={part.id}
                >
                  {part.status === 'running' ? (
                    <Loader size={14} />
                  ) : (
                    <Wrench className="size-4 shrink-0" />
                  )}
                  <p className="min-w-0 flex-1 truncate text-sm">
                    {getToolTitle(part.toolName, part.toolInvocation)}
                  </p>
                  {toolChangeDisplay.showAdded && (
                    <span className="shrink-0 text-xs font-medium text-emerald-600">
                      +{toolChangeDisplay.added}
                    </span>
                  )}
                  {toolChangeDisplay.showRemoved && (
                    <span className="shrink-0 text-xs font-medium text-red-600">
                      -{toolChangeDisplay.removed}
                    </span>
                  )}
                </div>
              );
            })}

          {!shouldRenderAssistantPartsInOrder &&
            groupedParts.reasoning.length > 0 && (
              <ChainOfThought
                className="w-full"
                defaultOpen={isCurrentStreaming}
              >
                <ChainOfThoughtHeader>思考过程</ChainOfThoughtHeader>
                <ChainOfThoughtContent>
                  {groupedParts.reasoning.map((step, stepIndex) => (
                    <ChainOfThoughtStep
                      key={`${message.id}-reasoning-${stepIndex}`}
                      icon={Brain}
                      label="推理"
                      status={isCurrentStreaming ? 'active' : 'complete'}
                    >
                      <div className="mt-2 whitespace-pre-wrap text-sm text-muted-foreground">
                        {step.content}
                      </div>
                    </ChainOfThoughtStep>
                  ))}
                </ChainOfThoughtContent>
              </ChainOfThought>
            )}

          {!shouldRenderAssistantPartsInOrder &&
            groupedParts.environments.map((part) => (
              <ThreadChatEnvironmentInitCard
                key={part.id}
                part={part}
                isEnvironmentResetting={isEnvironmentResetting}
                onResetEnvironmentInitialization={
                  onResetEnvironmentInitialization
                }
              />
            ))}

          {!shouldRenderAssistantPartsInOrder &&
            !hasEnvironmentPart &&
            groupedParts.content.map((part, partIndex) =>
              isTurnFailureContent(part.content) ? (
                <div
                  className="rounded-md border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-amber-900 dark:text-amber-200"
                  key={part.id}
                >
                  <div className="flex items-start gap-2">
                    <AlertTriangle className="mt-0.5 size-4 shrink-0 text-amber-600 dark:text-amber-300" />
                    <div className="whitespace-pre-wrap wrap-break-word text-sm">
                      {part.content}
                    </div>
                  </div>
                </div>
              ) : isCurrentStreaming &&
                partIndex === groupedParts.content.length - 1 ? (
                <StreamingBufferedResponse key={part.id} text={part.content} />
              ) : (
                <MessageResponse
                  key={part.id}
                  isAnimating={false}
                  mode="static"
                >
                  {part.content}
                </MessageResponse>
              )
            )}

          {!shouldRenderAssistantPartsInOrder &&
            !compactToolView &&
            groupedParts.tools.map((part) => (
              <ThreadChatToolTaskItem key={part.id} part={part} />
            ))}

          {shouldRenderAssistantPartsInOrder &&
            message.parts.map((part) => {
              if (part.type === 'reasoning') {
                return (
                  <ChainOfThought
                    className="w-full"
                    defaultOpen={isCurrentStreaming}
                    key={part.id}
                  >
                    <ChainOfThoughtHeader>思考过程</ChainOfThoughtHeader>
                    <ChainOfThoughtContent>
                      <ChainOfThoughtStep
                        icon={Brain}
                        label="推理"
                        status={isCurrentStreaming ? 'active' : 'complete'}
                      >
                        <div className="mt-2 whitespace-pre-wrap text-sm text-muted-foreground">
                          {part.content}
                        </div>
                      </ChainOfThoughtStep>
                    </ChainOfThoughtContent>
                  </ChainOfThought>
                );
              }

              if (part.type === 'environment') {
                return (
                  <ThreadChatEnvironmentInitCard
                    key={part.id}
                    part={part}
                    isEnvironmentResetting={isEnvironmentResetting}
                    onResetEnvironmentInitialization={
                      onResetEnvironmentInitialization
                    }
                  />
                );
              }

              if (part.type === 'content') {
                if (isTurnFailureContent(part.content)) {
                  return (
                    <div
                      className="rounded-md border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-amber-900 dark:text-amber-200"
                      key={part.id}
                    >
                      <div className="flex items-start gap-2">
                        <AlertTriangle className="mt-0.5 size-4 shrink-0 text-amber-600 dark:text-amber-300" />
                        <div className="whitespace-pre-wrap break-words text-sm">
                          {part.content}
                        </div>
                      </div>
                    </div>
                  );
                }
                if (isCurrentStreaming && part.id === lastContentPartId) {
                  return (
                    <StreamingBufferedResponse
                      key={part.id}
                      text={part.content}
                    />
                  );
                }
                return (
                  <MessageResponse
                    key={part.id}
                    isAnimating={false}
                    mode="static"
                  >
                    {part.content}
                  </MessageResponse>
                );
              }

              return <ThreadChatToolTaskItem key={part.id} part={part} />;
            })}
        </MessageContent>
        {shouldShowActionRow && (
          <MessageActions
            className={cn(
              'min-h-6 w-full items-center',
              messageFrom === 'user' ? 'justify-end' : 'justify-start',
              canShowCopyAction
                ? 'opacity-0 transition-opacity group-hover:opacity-100'
                : 'opacity-100',
              canShowCopyAction ? undefined : 'pointer-events-none',
              messageFrom === 'user' ? 'ml-auto' : undefined
            )}
          >
            {shouldShowRespondingStatus ? (
              <div className="text-sm text-muted-foreground">
                <Shimmer>{isThinking ? 'thinking...' : '正在回复...'}</Shimmer>
              </div>
            ) : null}
            {copyMeta.canCopy ? (
              canShowCopyAction ? (
                <MessageAction
                  aria-label="复制消息"
                  label="复制消息"
                  size={'icon-xs'}
                  onClick={handleCopyMessage}
                  tooltip={isCopied ? '已复制' : '复制消息'}
                  className="cursor-pointer"
                >
                  {isCopied ? <Check /> : <Copy />}
                </MessageAction>
              ) : (
                <span aria-hidden className="size-5" />
              )
            ) : (
              <span aria-hidden className="size-5" />
            )}
          </MessageActions>
        )}
      </Message>
    );
  },
  (prevProps, nextProps) => {
    if (!areMessagesEqual(prevProps.message, nextProps.message)) return false;
    if (prevProps.isCurrentStreaming !== nextProps.isCurrentStreaming) {
      return false;
    }
    if (prevProps.isLatestResponding !== nextProps.isLatestResponding) {
      return false;
    }
    if (prevProps.isThinking !== nextProps.isThinking) return false;
    if (prevProps.disableCopy !== nextProps.disableCopy) return false;
    if (prevProps.compactToolView !== nextProps.compactToolView) return false;

    const reliesOnEnvironmentControls =
      hasEnvironmentParts(prevProps.message) ||
      hasEnvironmentParts(nextProps.message);
    if (reliesOnEnvironmentControls) {
      if (
        prevProps.onResetEnvironmentInitialization !==
        nextProps.onResetEnvironmentInitialization
      ) {
        return false;
      }
      if (
        prevProps.isEnvironmentResetting !== nextProps.isEnvironmentResetting
      ) {
        return false;
      }
    }

    if (prevProps.copyMeta.canCopy !== nextProps.copyMeta.canCopy) return false;
    if (prevProps.copyMeta.copyText !== nextProps.copyMeta.copyText)
      return false;
    return true;
  }
);

ThreadChatMessageItem.displayName = 'ThreadChatMessageItem';
