# Code Review Platform Backend

## Scope
Phase 1 implements a backend-first code review platform in `app/services/code_review/`, `app/routers/`, and the shared `app/models/code_review.py` tables. Review analysis and follow-up fixes now reuse the same bound task thread, with lightweight per-thread FIFO queueing for approved fixes.

## Request Flow
- Public webhook routes:
  - `POST /api/code-review/webhooks/github`
  - `POST /api/code-review/webhooks/gitlab`
- Protected repository/config routes:
  - `POST /api/code-review/repositories/sync`
  - `GET /api/code-review/repositories`
  - `GET /api/code-review/repositories/{id}/config`
  - `PUT /api/code-review/repositories/{id}/config`
- Protected run routes:
  - `GET /api/code-review/runs`
  - `GET /api/code-review/runs/{id}`
  - `POST /api/code-review/runs/{id}/publish`
- Protected/public fix routes:
  - `POST /api/code-review/fix-requests/{id}/approve`
  - `POST /api/code-review/fix-requests/{id}/reject`
  - `POST /api/code-review/fix-runner/callback`

## Phase 1 Behavior
- Webhooks validate GitHub signatures and GitLab tokens.
- Webhooks normalize payloads, resolve repository integrations, create queued runs, and record initial timeline events.
- The dispatcher moves runs through `queued -> analyzing -> completed/failed`.
- The analyzer is deterministic and in-process. It persists findings, can create `ReviewFixRequest` rows from repository policy, and records analysis timeline events.
- Fix approval is membership-gated. Approve requires `ReviewRun.thread_id`, keeps queued work on that same thread, and only dispatches the next fix when the thread is idle.
- Approved fixes are appended onto the existing task thread through Aegra `create_run` instead of creating a separate fix thread.
- The in-process queue worker serializes approved fixes FIFO per `thread_id`. `approved` means queued, `running` means the corresponding Aegra run has been dispatched.
- Runner callbacks are authenticated with `SANDBOX_AGENT_CODE_REVIEW_FIX_RUNNER_SECRET` or `CODE_REVIEW_FIX_RUNNER_SECRET`, and update requests to `completed` or `failed`.
- Publish is a stub contract only. `POST /api/code-review/runs/{id}/publish` requires a visible `completed` run, records publish timeline attempts, and returns a deterministic success payload without provider-side comments.

## Data Model Notes
- Repository identity is stored with `provider + external_repo_id + repository_identity_key`.
- GitHub uses an empty `repository_identity_key`.
- GitLab uses the canonicalized instance URL, including self-managed subpaths.
- `ReviewFixRequest` is linked to both the run and finding with a schema-level composite foreign key.
- Timeline events are the source of truth for lifecycle history.

## Environment Secrets
- `GITHUB_WEBHOOK_SECRET`
- `GITLAB_WEBHOOK_SECRET`
- `SANDBOX_AGENT_CODE_REVIEW_WEBHOOK_SECRET`
- `SANDBOX_AGENT_CODE_REVIEW_FIX_RUNNER_SECRET`
- `CODE_REVIEW_FIX_RUNNER_SECRET`

## Intentionally Stubbed
- Real analyzer execution
- Durable queue recovery across process restarts
- Provider-side publishing/comments
- Webhook delivery retries and queue infrastructure beyond the in-process dispatcher boundary

## Operational Notes
- Keep webhook handlers fast and non-blocking.
- Keep publish and callback routes contract-safe even when the real provider integrations are added later.
- When extending the platform, preserve the existing timeline event names and run/fix status transitions so current tests remain valid.
