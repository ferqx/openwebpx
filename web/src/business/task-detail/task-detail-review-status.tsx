import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { CircleAlert, CircleCheckBig, MessageSquareWarning } from 'lucide-react';

export type ReviewCommentPublishStatus = {
  status: string;
  reason?: string;
  provider?: string;
  summary?: string;
  extractedCount?: number;
  filteredCount?: number;
  publishedCount?: number;
};

type TaskDetailReviewStatusProps = {
  reviewStatus: ReviewCommentPublishStatus;
};

const getStatusBadge = (reviewStatus: ReviewCommentPublishStatus) => {
  if (reviewStatus.status === 'published') {
    return {
      label: '已回贴到代码行',
      variant: 'secondary' as const,
      icon: CircleCheckBig
    };
  }
  if (reviewStatus.status === 'error') {
    return {
      label: '回贴失败',
      variant: 'destructive' as const,
      icon: CircleAlert
    };
  }
  return {
    label: '未生成行级评论',
    variant: 'outline' as const,
    icon: MessageSquareWarning
  };
};

const getStatusDescription = (reviewStatus: ReviewCommentPublishStatus) => {
  if (reviewStatus.status === 'published') {
    return `已发布 ${reviewStatus.publishedCount ?? 0} 条行级评论，候选 ${reviewStatus.extractedCount ?? 0} 条，校验通过 ${reviewStatus.filteredCount ?? 0} 条。`;
  }

  if (reviewStatus.reason === 'no_structured_comments') {
    return '本次审查没有生成可回贴的结构化行级评论。';
  }
  if (reviewStatus.reason === 'no_valid_comments') {
    return `模型生成了 ${reviewStatus.extractedCount ?? 0} 条候选评论，但都没有通过 diff 行号校验，所以没有发到代码托管平台。`;
  }
  if (reviewStatus.reason === 'publish_failed') {
    return '后端在向代码托管平台发布行级评论时失败了，请检查后端日志与仓库权限配置。';
  }
  if (reviewStatus.reason?.startsWith('run_')) {
    return '本次审查运行没有成功完成，因此没有尝试发布行级评论。';
  }
  if (reviewStatus.reason === 'invalid_github_locator' || reviewStatus.reason === 'invalid_gitlab_locator') {
    return '审查线程缺少可用的 PR/MR 定位信息，因此无法把评论回贴到对应代码行。';
  }
  return '当前没有可展示的代码行评论发布结果。';
};

export function TaskDetailReviewStatus({
  reviewStatus
}: TaskDetailReviewStatusProps) {
  const badge = getStatusBadge(reviewStatus);
  const Icon = badge.icon;
  const summary = reviewStatus.summary?.trim();

  return (
    <Alert className="border-dashed bg-muted/30">
      <Icon className="size-4" />
      <AlertTitle className="flex flex-wrap items-center gap-2">
        <span>代码审查评论</span>
        <Badge variant={badge.variant}>{badge.label}</Badge>
        {reviewStatus.provider ? (
          <Badge variant="outline" className="uppercase">
            {reviewStatus.provider}
          </Badge>
        ) : null}
      </AlertTitle>
      <AlertDescription>
        <p>{getStatusDescription(reviewStatus)}</p>
        {summary ? <p className="mt-1 text-xs text-muted-foreground">{summary}</p> : null}
      </AlertDescription>
    </Alert>
  );
}
