export type CodeReviewProvider = 'github' | 'gitlab';

export type CodeReviewRepositorySyncRequest = {
  provider: CodeReviewProvider;
  gitlab_base_url?: string | null;
  github_auth_mode?: string | null;
};

export type CodeReviewRepositorySummary = {
  id: number;
  provider: CodeReviewProvider;
  external_repo_id: string;
  repository_identity_key?: string;
  full_name?: string | null;
  default_branch?: string | null;
  gitlab_base_url?: string | null;
  review_enabled?: boolean;
};

export type CodeReviewRepositoryListResponse = {
  repositories: CodeReviewRepositorySummary[];
};

export type CodeReviewRepositoryConfig = {
  id: number;
  repository_integration_id: number;
  review_enabled: boolean;
  review_triggers: Record<string, unknown> | null;
  auto_fix_enabled: boolean;
  auto_fix_severities: Record<string, unknown> | null;
  auto_fix_requires_approval: boolean;
  auto_publish_enabled: boolean;
  updated_by?: string | null;
  updated_at?: string | null;
};

export type CodeReviewRepositoryConfigUpdate = {
  review_enabled?: boolean;
  review_triggers?: Record<string, unknown> | null;
  auto_fix_enabled?: boolean;
  auto_fix_severities?: Record<string, unknown> | null;
  auto_fix_requires_approval?: boolean;
  auto_publish_enabled?: boolean;
};

export type CodeReviewRunStatus = 'queued' | 'analyzing' | 'completed' | 'failed';

export type CodeReviewRunSummary = {
  id: number;
  repository_integration_id: number;
  provider: CodeReviewProvider;
  event_type: string;
  status: CodeReviewRunStatus;
  idempotency_key: string;
  external_pr_or_mr_id?: string | null;
  head_commit_id?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
};

export type CodeReviewRunRepository = {
  id: number;
  provider: CodeReviewProvider;
  external_repo_id: string;
  repository_identity_key: string;
  full_name?: string | null;
  gitlab_base_url?: string | null;
};

export type CodeReviewFinding = {
  id: number;
  severity: string;
  category: string | null;
  file_path: string | null;
  line_start: number | null;
  line_end: number | null;
  title: string;
  body: string | null;
  rule_id?: string | null;
  can_auto_fix: boolean;
  metadata: Record<string, unknown> | null;
  created_at?: string | null;
};

export type CodeReviewFixRequestStatus =
  | 'pending_approval'
  | 'approved'
  | 'rejected'
  | 'running'
  | 'completed'
  | 'failed';

export type CodeReviewFixRequest = {
  id: number;
  review_run_id: number;
  review_finding_id: number | null;
  source: string;
  status: CodeReviewFixRequestStatus;
  approval_required: boolean;
  approved_by?: string | null;
  approved_at?: string | null;
  rejected_by?: string | null;
  rejected_at?: string | null;
  runner_job_id?: string | null;
  result_payload?: Record<string, unknown> | null;
  updated_at?: string | null;
};

export type CodeReviewTimelineEvent = {
  id: number;
  event_type: string;
  dedupe_key?: string | null;
  payload: Record<string, unknown> | null;
  created_at?: string | null;
};

export type CodeReviewRunDetail = CodeReviewRunSummary & {
  repository: CodeReviewRunRepository | null;
  findings: CodeReviewFinding[];
  fix_requests: CodeReviewFixRequest[];
  timeline_events: CodeReviewTimelineEvent[];
};

export type CodeReviewRunListResponse = {
  runs: CodeReviewRunSummary[];
};

export type CodeReviewPublishRunResult = {
  published: boolean;
  run_id: number;
  status: CodeReviewRunStatus;
  published_at: string;
  stubbed: boolean;
};
