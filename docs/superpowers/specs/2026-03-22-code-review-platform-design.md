# Code Review Platform Design

## Goal

Build a new repository-scoped AI code review platform on the backend first, using the existing `app/` FastAPI structure. The first phase must support repository integration, webhook-driven review runs, findings persistence, automatic fix-request generation from repository policy, approval-gated fix execution via a runner adapter, and a complete backend-visible timeline. Frontend work starts only after the backend is functionally complete and verified.

## Scope

Included in phase 1:
- Repository-scoped review integration for GitHub and GitLab
- Repository membership and repository review configuration
- Public webhook ingestion for GitHub and GitLab
- Unified review run model and timeline
- Findings persistence
- Automatic creation of fix requests when repository policy enables auto-fix
- Approval and rejection workflow for fix requests
- Runner callback contract and stub runner adapter
- Backend tests covering the full flow

Explicitly excluded from phase 1:
- Frontend UI
- Backward compatibility with the removed code review API shape
- Real external fix execution infrastructure
- Real provider-side comment publishing
- Queue infrastructure beyond a clean async dispatcher abstraction

## Existing Codebase Constraints

- Backend custom APIs live under `app/`, not under `libs/aegra-api/src/aegra_api/`.
- Route registration happens in `app/main.py`.
- Shared DB engine and session lifecycle come from `aegra_api`, but custom business models and routes belong in `app/`.
- Existing project structure already uses:
  - `app/routers/` for HTTP boundaries
  - `app/services/` for business logic
  - `app/models/` for ORM models
  - `alembic/versions/` for migrations
  - top-level `tests/` for backend tests
- Commit `a54fb5a` removed the old code review module, so this work is a reconstruction on top of the current backend shape rather than a compatibility patch.

## Architecture

The new platform should be built as a backend domain inside `app/`, split into small focused units instead of reviving the former single-file `app/routers/code_review.py` design.

Core layers:
- Routers: request validation, auth boundaries, response shaping
- Services: review domain orchestration
- Provider adapters: GitHub and GitLab payload normalization
- ORM models: repository, run, finding, fix, timeline persistence
- Adapters: fix runner and publisher integration boundaries

The system should treat repository integration, review execution, and fix execution as separate concerns:
- Repository integration answers which repos are connected and who can act on them
- Review execution answers what happened for a specific webhook-triggered analysis
- Fix execution answers whether an auto-fix candidate was approved and how execution progressed

## Domain Model

### Repository Domain

`RepositoryIntegration`
- Represents a provider repository connected to the platform
- Key fields:
  - `id`
  - `provider`
  - `external_repo_id`
  - `full_name`
  - `default_branch`
  - `gitlab_base_url`
  - `webhook_status`
  - `webhook_management_mode`
  - `created_at`
  - `updated_at`

Uniqueness:
- Unique on `provider + external_repo_id`

`RepositoryMembership`
- Connects a user to a repository integration
- Key fields:
  - `id`
  - `repository_integration_id`
  - `user_id`
  - `role`
  - `can_approve_fixes`
  - `created_at`
  - `updated_at`

Uniqueness:
- Unique on `repository_integration_id + user_id`

`RepositoryReviewConfig`
- Stores repository-scoped review policy
- Key fields:
  - `id`
  - `repository_integration_id`
  - `review_enabled`
  - `review_triggers`
  - `auto_fix_enabled`
  - `auto_fix_severities`
  - `auto_fix_requires_approval`
  - `auto_publish_enabled`
  - `updated_by`
  - `updated_at`

Relationship:
- One config row per repository integration

### Review Run Domain

`ReviewRun`
- Represents one normalized review execution for one provider event and one head commit
- Key fields:
  - `id`
  - `repository_integration_id`
  - `provider`
  - `event_type`
  - `external_event_id`
  - `external_pr_or_mr_id`
  - `head_commit_id`
  - `base_commit_id`
  - `base_branch`
  - `head_branch`
  - `status`
  - `idempotency_key`
  - `created_by_event_at`
  - `created_at`
  - `updated_at`

Run statuses for phase 1:
- `queued`
- `analyzing`
- `completed`
- `failed`

Uniqueness:
- Unique on `idempotency_key`

`ReviewFinding`
- Represents one finding produced by analysis
- Key fields:
  - `id`
  - `review_run_id`
  - `severity`
  - `category`
  - `file_path`
  - `line_start`
  - `line_end`
  - `title`
  - `body`
  - `rule_id`
  - `can_auto_fix`
  - `metadata`
  - `created_at`

`ReviewTimelineEvent`
- Stores user-visible and backend-visible lifecycle events
- Key fields:
  - `id`
  - `review_run_id`
  - `event_type`
  - `dedupe_key`
  - `payload`
  - `created_at`

### Fix Domain

`ReviewFixRequest`
- Represents an automatic fix candidate created from policy after findings exist
- Key fields:
  - `id`
  - `review_run_id`
  - `review_finding_id`
  - `source`
  - `status`
  - `approval_required`
  - `approved_by`
  - `approved_at`
  - `rejected_by`
  - `rejected_at`
  - `runner_job_id`
  - `result_payload`
  - `created_at`
  - `updated_at`

Source values for phase 1:
- `auto_policy`

Fix statuses for phase 1:
- `pending_approval`
- `approved`
- `rejected`
- `running`
- `completed`
- `failed`

## API Design

Protected endpoints:
- `POST /api/code-review/repositories/sync`
- `GET /api/code-review/repositories`
- `GET /api/code-review/repositories/{id}/config`
- `PUT /api/code-review/repositories/{id}/config`
- `GET /api/code-review/runs`
- `GET /api/code-review/runs/{run_id}`
- `POST /api/code-review/fix-requests/{id}/approve`
- `POST /api/code-review/fix-requests/{id}/reject`
- `POST /api/code-review/runs/{run_id}/publish`

Public endpoints:
- `POST /api/code-review/webhooks/github`
- `POST /api/code-review/webhooks/gitlab`
- `POST /api/code-review/fix-runner/callback`

API design rules:
- No compatibility promise with removed legacy endpoints
- All repository-facing data is repository-scoped, not user-profile-scoped
- Fix requests are not user-created by manual POST in phase 1
- Fix requests are system-generated from repository policy after findings are created

## Execution Flow

### Repository Setup Flow

1. User completes SCM auth through the existing SCM system.
2. `POST /api/code-review/repositories/sync` lists provider repositories visible to the user.
3. The sync service creates or reuses `RepositoryIntegration`.
4. The sync service creates or updates `RepositoryMembership` for the current user.
5. The config service persists one `RepositoryReviewConfig` row per repository as needed.
6. Webhook management state is stored on the integration, but webhook sync failures do not block configuration persistence.

### Review Run Flow

1. Provider webhook arrives at a public endpoint.
2. The router validates signature or token.
3. The provider adapter normalizes the payload to a unified event contract.
4. The webhook service resolves the repository integration and config.
5. If review is not enabled for the repository, the event is ignored safely.
6. The webhook service computes the `idempotency_key`.
7. If the event already exists, the endpoint returns success without creating another run.
8. Otherwise, the service creates `ReviewRun(status=queued)`.
9. Timeline records `review_requested` and `queued`.
10. The dispatcher enqueues `run_id` for analysis and the webhook returns immediately.

### Analysis Flow

1. Dispatcher starts analyzer work asynchronously.
2. Analyzer marks the run as `analyzing`.
3. Analyzer fetches normalized diff context from the provider adapter.
4. Analyzer produces findings.
5. Findings are persisted.
6. Timeline records `analysis_started` and `analysis_completed` or `analysis_failed`.
7. Run status becomes `completed` or `failed`.
8. If repository policy allows auto-fix for a finding, the service creates a `ReviewFixRequest(status=pending_approval)`.
9. Timeline records `fix_request_created`.

### Fix Flow

1. Authorized repository member approves or rejects a fix request.
2. Rejection moves the request to `rejected` and records timeline.
3. Approval moves the request to `approved`, then `running`, and invokes the runner adapter.
4. The runner adapter returns a stable `runner_job_id`.
5. Callback updates the fix request to `completed` or `failed`.
6. Timeline records `fix_approved`, `fix_runner_started`, and terminal runner events.

## Async Design

Webhook handling must remain short and non-blocking. Findings should not be generated inside the webhook request lifecycle.

Phase 1 async boundary:
- `review_dispatcher.enqueue(run_id)` is the only handoff entry
- The initial implementation may use a process-local async task strategy
- The interface must be designed so a real queue or worker can replace it later without changing routers or domain models

This keeps the platform stable when later replacing the dispatcher with a real background worker system.

## Idempotency Strategy

Webhook idempotency key should be derived from normalized event identity instead of only provider delivery IDs.

Recommended key components:
- `provider`
- `external_repo_id`
- `event_type`
- `external_pr_or_mr_id`
- `head_commit_id`

The concatenated normalized value should be hashed and stored as `ReviewRun.idempotency_key`.

Callback idempotency:
- Use `fix_request_id + runner_job_id + callback_state`

Timeline dedupe:
- Timeline events may repeat logically, but service code should avoid duplicate writes for the same `(review_run_id, event_type, dedupe_key)` combination where applicable.

## Service Boundaries

Recommended file layout:
- `app/models/code_review.py`
- `app/routers/code_review_repositories.py`
- `app/routers/code_review_runs.py`
- `app/routers/code_review_webhooks.py`
- `app/routers/code_review_fixes.py`
- `app/services/code_review/repository_service.py`
- `app/services/code_review/webhook_service.py`
- `app/services/code_review/review_dispatcher.py`
- `app/services/code_review/review_analyzer.py`
- `app/services/code_review/review_run_service.py`
- `app/services/code_review/timeline_service.py`
- `app/services/code_review/fix_service.py`
- `app/services/code_review/fix_runner.py`
- `app/services/code_review/provider_github.py`
- `app/services/code_review/provider_gitlab.py`

Boundary rules:
- Routers never implement business policy directly.
- Provider-specific parsing stays out of routers.
- Fix execution stays behind an adapter.
- Timeline writes are centralized.
- Config-driven auto-fix generation happens during analysis completion, not by manual user creation.

## Error Handling

Rules:
- Webhook validation failures return provider-appropriate client errors.
- Unknown repositories or disabled review config should return success-safe outcomes where possible to avoid retry storms.
- Webhook sync failures during repository configuration should not block config persistence.
- Analyzer failures must move runs to `failed` and write a timeline event with structured diagnostic payload.
- Runner callback failures must not corrupt terminal states or create duplicate terminal transitions.

## Testing Strategy

Phase 1 tests should cover four levels.

### Persistence and Migration Tests

Verify:
- Table creation
- Foreign keys
- Uniqueness constraints
- JSON payload fields
- Status field persistence

### Service Tests

Verify:
- Repository sync behavior
- Membership reuse when multiple users connect the same repository
- Webhook normalization
- Idempotent run creation
- Async dispatch handoff
- Findings persistence
- Auto-fix request generation from policy
- Approval and rejection state transitions
- Callback state transitions

### Router Tests

Verify:
- Auth behavior for protected endpoints
- Public webhook acceptance and validation behavior
- Response shapes
- Error codes

### End-to-End Backend Tests

Run a full stubbed flow:
- webhook received
- run queued
- analysis completed
- findings persisted
- fix request automatically created
- approval submitted
- runner callback received
- fix request terminal state reached

## Phase 1 Completion Criteria

Phase 1 is complete when:
- Backend repository integration, webhook ingestion, review run persistence, findings persistence, auto-fix request generation, approval, and runner callback flows all work
- Backend tests cover the full domain flow and pass
- No frontend work is required to validate the platform behavior
- The system can later plug in a real publisher and a real runner without changing core API or table design

## Deferred Work

Move to later phases:
- Frontend review configuration and review timeline pages
- Real provider-side comment publishing
- Real fix runner execution that creates branches and PRs or MRs
- Rich reviewer assignment and notifications
- Advanced retry scheduling and queue infrastructure
