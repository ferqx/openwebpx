import React from 'react';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from '@/components/ui/dialog';
import { Label } from '@/components/ui/label';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from '@/components/ui/select';
import {
  Textarea
} from '@/components/ui/textarea';
import { type CodeReviewRunDetail } from '@/business/portal/code-review-types';
import { statusLabel, type TaskItem } from '@/lib/tasks';

const DEFAULT_CONTINUE_FIX_INSTRUCTION =
  '请根据本次代码审查结果修复问题，优先处理高优先级项，并在完成后说明修改内容。';

const CONTINUE_FIX_PROMPT_TEMPLATES = [
  {
    id: 'balanced',
    label: '默认修复',
    instruction: DEFAULT_CONTINUE_FIX_INSTRUCTION
  },
  {
    id: 'strict',
    label: '严格修复',
    instruction:
      '请根据本次代码审查结果逐项修复问题，优先处理 high 和 medium 项，不要扩大改动范围，并在完成后说明每项对应修改。'
  },
  {
    id: 'minimal',
    label: '最小改动',
    instruction:
      '请根据本次代码审查结果进行最小必要修改，只修复明确问题，避免无关重构，并在完成后解释取舍。'
  }
] as const;

const formatFindingLocation = (filePath: string | null, lineStart: number | null) => {
  if (!filePath) return '未知位置';
  if (lineStart === null) return filePath;
  return `${filePath}:${lineStart}`;
};

export const findContinueFixTemplate = (instruction: string) =>
  CONTINUE_FIX_PROMPT_TEMPLATES.find(
    (template) => template.instruction === instruction.trim()
  )?.id ?? 'custom';

export const resolveContinueFixInstruction = (templateId: string) =>
  CONTINUE_FIX_PROMPT_TEMPLATES.find((template) => template.id === templateId)
    ?.instruction ?? '';

const describeContinueFixTask = (task: TaskItem) =>
  `${task.repo} · ${task.branch} · ${statusLabel[task.status]}`;

export const buildContinueFixPrompt = ({
  run,
  instruction
}: {
  run: CodeReviewRunDetail;
  instruction?: string;
}) => {
  const trimmedInstruction = instruction?.trim() || DEFAULT_CONTINUE_FIX_INSTRUCTION;
  const findingsSummary = run.findings
    .map((finding, index) => {
      const location = formatFindingLocation(finding.file_path, finding.line_start);
      const body = finding.body?.trim() || '暂无附加说明';
      return [
        `${index + 1}. [${finding.severity}] ${finding.title}`,
        `位置: ${location}`,
        `说明: ${body}`
      ].join('\n');
    })
    .join('\n\n');

  return [
    trimmedInstruction,
    '',
    `仓库: ${run.repository?.full_name ?? '未知仓库'}`,
    `运行: #${run.id}`,
    `类型: ${run.event_type}`,
    '',
    '审查发现:',
    findingsSummary || '暂无审查发现'
  ].join('\n');
};

type PortalCodeReviewContinueFixDialogProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  run: CodeReviewRunDetail | null;
  threadId: string | null;
  threadTask: TaskItem | null;
  instruction: string;
  onInstructionChange: (value: string) => void;
  onInstructionTemplateChange?: (value: string) => void;
  isSubmitting: boolean;
  onSubmit: () => void | Promise<void>;
};

export function PortalCodeReviewContinueFixDialog({
  open,
  onOpenChange,
  run,
  threadId,
  threadTask,
  instruction,
  onInstructionChange,
  onInstructionTemplateChange,
  isSubmitting,
  onSubmit
}: PortalCodeReviewContinueFixDialogProps) {
  const findingsPreview = run?.findings.slice(0, 3) ?? [];
  const selectedTemplateId = findContinueFixTemplate(instruction);
  const promptPreview = run
    ? buildContinueFixPrompt({
        run,
        instruction
      })
    : '';

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>继续修复</DialogTitle>
          <DialogDescription>
            将当前代码审查结果整理成新提问，追加到该审查绑定的唯一线程中继续执行修复。
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div className="space-y-2">
            <Label>绑定线程</Label>
            {threadId ? (
              <p className="text-sm text-muted-foreground">
                这次修复只能继续到审查绑定的线程 <span className="font-medium text-foreground">{threadId}</span>。
              </p>
            ) : (
              <p className="text-sm text-muted-foreground">
                当前审查没有绑定线程，无法继续修复。
              </p>
            )}
            {threadTask ? (
              <div className="rounded-lg border bg-muted/20 px-3 py-2 text-xs text-muted-foreground">
                <p className="font-medium text-foreground">{threadTask.title}</p>
                <p>{describeContinueFixTask(threadTask)}</p>
                <p>最近更新 {threadTask.updatedAt}</p>
              </div>
            ) : threadId ? (
              <div className="rounded-lg border bg-muted/20 px-3 py-2 text-xs text-muted-foreground">
                <p className="font-medium text-foreground">线程 {threadId}</p>
                <p>该线程尚未加载到本地任务列表，提交后仍会直接跳转到对应线程页。</p>
              </div>
            ) : null}
          </div>

          <div className="space-y-2">
            <Label>提示模板</Label>
            <Select
              value={selectedTemplateId}
              onValueChange={(value) => {
                if (!onInstructionTemplateChange || value === 'custom') return;
                onInstructionTemplateChange(value);
              }}
            >
              <SelectTrigger className="w-full">
                <SelectValue placeholder="选择提示模板" />
              </SelectTrigger>
              <SelectContent>
                {CONTINUE_FIX_PROMPT_TEMPLATES.map((template) => (
                  <SelectItem key={template.id} value={template.id}>
                    {template.label}
                  </SelectItem>
                ))}
                <SelectItem value="custom">自定义</SelectItem>
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-2">
            <Label>本次附加指令</Label>
            <Textarea
              rows={4}
              value={instruction}
              onChange={(event) => onInstructionChange(event.target.value)}
            />
          </div>

          <div className="space-y-2 rounded-lg border bg-muted/30 p-3">
            <p className="text-sm font-medium text-foreground">将带入的审查发现</p>
            {findingsPreview.length === 0 ? (
              <p className="text-sm text-muted-foreground">当前没有可带入的审查发现</p>
            ) : (
              <div className="space-y-2 text-sm">
                {findingsPreview.map((finding) => (
                  <div key={finding.id} className="space-y-1">
                    <p className="font-medium text-foreground">
                      [{finding.severity}] {finding.title}
                    </p>
                    <p className="text-xs text-muted-foreground">
                      {formatFindingLocation(finding.file_path, finding.line_start)}
                    </p>
                  </div>
                ))}
                {run && run.findings.length > findingsPreview.length ? (
                  <p className="text-xs text-muted-foreground">
                    还有 {run.findings.length - findingsPreview.length} 项发现会一并发送。
                  </p>
                ) : null}
              </div>
            )}
          </div>

          <div className="space-y-2 rounded-lg border bg-muted/10 p-3">
            <p className="text-sm font-medium text-foreground">发送预览</p>
            <pre className="max-h-48 overflow-auto whitespace-pre-wrap text-xs text-muted-foreground">
              {promptPreview}
            </pre>
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            取消
          </Button>
          <Button
            disabled={
              isSubmitting ||
              run === null ||
              run.findings.length === 0 ||
              !threadId
            }
            onClick={() => void onSubmit()}
          >
            {isSubmitting ? '跳转中...' : '发送到线程'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export { CONTINUE_FIX_PROMPT_TEMPLATES, DEFAULT_CONTINUE_FIX_INSTRUCTION };
