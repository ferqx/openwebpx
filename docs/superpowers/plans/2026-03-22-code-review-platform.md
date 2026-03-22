# Code Review Platform Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the backend-first repository-scoped AI code review platform under `app/`, including repository integration, webhook-driven review runs, findings, automatic fix-request generation from repository policy, approval-gated runner execution, and a complete backend timeline.

**Architecture:** The platform is implemented as a new backend domain inside `app/`. Routers provide HTTP boundaries, services own business logic, provider adapters normalize GitHub and GitLab payloads, ORM models persist repository and review state, and a stub runner adapter provides the first-phase fix execution contract without requiring real external execution infrastructure.

**Tech Stack:** FastAPI, SQLAlchemy async ORM, Alembic, PostgreSQL JSONB, pytest, httpx, existing `aegra_api` session lifecycle

---

## Planned File Structure

- Create: `app/models/code_review.py`
- Modify: `app/models/__init__.py`
- Create: `app/services/code_review/__init__.py`
- Create: `app/services/code_review/repository_service.py`
- Create: `app/services/code_review/webhook_service.py`
- Create: `app/services/code_review/review_dispatcher.py`
- Create: `app/services/code_review/review_analyzer.py`
- Create: `app/services/code_review/review_run_service.py`
- Create: `app/services/code_review/timeline_service.py`
- Create: `app/services/code_review/fix_service.py`
- Create: `app/services/code_review/fix_runner.py`
- Create: `app/services/code_review/provider_github.py`
- Create: `app/services/code_review/provider_gitlab.py`
- Create: `app/routers/code_review_repositories.py`
- Create: `app/routers/code_review_runs.py`
- Create: `app/routers/code_review_webhooks.py`
- Create: `app/routers/code_review_fixes.py`
- Modify: `app/main.py`
- Create: `alembic/versions/<timestamp>_add_code_review_platform_tables.py`
- Create: `tests/test_code_review_models.py`
- Create: `tests/test_code_review_repository_service.py`
- Create: `tests/test_code_review_webhooks.py`
- Create: `tests/test_code_review_runs.py`
- Create: `tests/test_code_review_fixes.py`
- Create: `tests/test_code_review_end_to_end.py`
- Modify: `CLAUDE.md`
- Create: `docs/backend/code_review_platform.md`

### Task 1: Add Code Review Domain Models

**Files:**
- Create: `app/models/code_review.py`
- Modify: `app/models/__init__.py`
- Test: `tests/test_code_review_models.py`

- [ ] **Step 1: Write the failing model test**

Create tests that assert the ORM module exports these models:
- `RepositoryIntegration`
- `RepositoryMembership`
- `RepositoryReviewConfig`
- `ReviewRun`
- `ReviewFinding`
- `ReviewTimelineEvent`
- `ReviewFixRequest`

Also assert expected enum-like status values and relationship field names are present.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_code_review_models.py -v`
Expected: FAIL because `app/models/code_review.py` does not exist.

- [ ] **Step 3: Write minimal ORM implementation**

Implement SQLAlchemy models with:
- repository uniqueness on `provider + external_repo_id`
- membership uniqueness on `repository_integration_id + user_id`
- one config row per integration
- run uniqueness on `idempotency_key`
- foreign keys between runs, findings, timeline events, and fix requests
- JSONB payload fields for finding metadata, timeline payload, and fix result payload

- [ ] **Step 4: Export the new models**

Update `app/models/__init__.py` so the new code review models are importable through the package.

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_code_review_models.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add app/models/code_review.py app/models/__init__.py tests/test_code_review_models.py
git commit -m "feat: add code review domain models"
```

### Task 2: Add Database Migration for Code Review Platform Tables

**Files:**
- Create: `alembic/versions/<timestamp>_add_code_review_platform_tables.py`
- Test: `tests/test_code_review_models.py`

- [ ] **Step 1: Extend the failing persistence test**

Add assertions that the migration creates:
- repository tables
- review run tables
- fix request table
- indexes for repository lookup and run idempotency

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_code_review_models.py -v`
Expected: FAIL because the migration file does not exist.

- [ ] **Step 3: Write the migration**

Create Alembic migration that creates:
- `repository_integrations`
- `repository_memberships`
- `repository_review_configs`
- `review_runs`
- `review_findings`
- `review_timeline_events`
- `review_fix_requests`

Include:
- unique constraint for repository identity
- unique constraint for membership
- unique constraint for `review_runs.idempotency_key`
- useful lookup indexes for repository visibility and fix status queries

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_code_review_models.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add alembic/versions tests/test_code_review_models.py
git commit -m "feat: add code review platform migration"
```

### Task 3: Implement Repository Integration and Review Config Services

**Files:**
- Create: `app/services/code_review/__init__.py`
- Create: `app/services/code_review/repository_service.py`
- Create: `app/routers/code_review_repositories.py`
- Modify: `app/main.py`
- Test: `tests/test_code_review_repository_service.py`

- [ ] **Step 1: Write the failing repository service test**

Cover:
- same repository synced by two users reuses `RepositoryIntegration`
- sync creates `RepositoryMembership` for the current user
- config defaults are created for new integrations
- GitLab repositories retain `gitlab_base_url`
- listing repositories only returns memberships visible to the current user

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_code_review_repository_service.py -v`
Expected: FAIL because the service and router do not exist.

- [ ] **Step 3: Write minimal repository service implementation**

Implement service functions for:
- syncing provider repositories using existing SCM auth data
- creating or reusing repository integrations
- creating repository memberships
- reading and updating repository review config

Use the existing SCM service patterns instead of duplicating OAuth logic.

- [ ] **Step 4: Add repository routes**

Create endpoints for:
- `POST /api/code-review/repositories/sync`
- `GET /api/code-review/repositories`
- `GET /api/code-review/repositories/{id}/config`
- `PUT /api/code-review/repositories/{id}/config`

Protected routes should require existing auth and load the current user identity from the request context.

- [ ] **Step 5: Register the router**

Update `app/main.py` to include the repository router under the protected route set.

- [ ] **Step 6: Run test to verify it passes**

Run: `uv run pytest tests/test_code_review_repository_service.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add app/services/code_review app/routers/code_review_repositories.py app/main.py tests/test_code_review_repository_service.py
git commit -m "feat: add code review repository integration services"
```

### Task 4: Implement Provider Adapters and Webhook Run Creation

**Files:**
- Create: `app/services/code_review/provider_github.py`
- Create: `app/services/code_review/provider_gitlab.py`
- Create: `app/services/code_review/webhook_service.py`
- Create: `app/routers/code_review_webhooks.py`
- Modify: `app/main.py`
- Test: `tests/test_code_review_webhooks.py`

- [ ] **Step 1: Write the failing webhook test**

Cover:
- GitHub webhook signature validation
- GitLab webhook token validation
- provider payload normalization to unified review event fields
- repository config lookup
- idempotent run creation with `provider + external_repo_id + event_type + external_pr_or_mr_id + head_commit_id`
- disabled repository config safely ignores the event

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_code_review_webhooks.py -v`
Expected: FAIL because adapters and webhook routes do not exist.

- [ ] **Step 3: Write provider adapters**

Implement adapter functions that normalize GitHub and GitLab webhook payloads into a shared internal event shape containing:
- repository identity
- provider event type
- PR or MR identity
- base/head branch
- base/head commit
- raw payload snapshot for diagnostics

- [ ] **Step 4: Write webhook service**

Implement service logic that:
- validates incoming webhook auth
- resolves the repository integration and config
- computes the run idempotency key
- creates `ReviewRun(status=queued)` only once
- writes initial timeline events

- [ ] **Step 5: Add public webhook routes**

Create endpoints:
- `POST /api/code-review/webhooks/github`
- `POST /api/code-review/webhooks/gitlab`

These routes must be public and must return quickly after enqueueing work.

- [ ] **Step 6: Register the public router**

Update `app/main.py` to include the webhook router without authenticated-user dependency.

- [ ] **Step 7: Run test to verify it passes**

Run: `uv run pytest tests/test_code_review_webhooks.py -v`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add app/services/code_review/provider_github.py app/services/code_review/provider_gitlab.py app/services/code_review/webhook_service.py app/routers/code_review_webhooks.py app/main.py tests/test_code_review_webhooks.py
git commit -m "feat: add code review webhook ingestion"
```

### Task 5: Implement Async Dispatcher and Review Run Orchestration

**Files:**
- Create: `app/services/code_review/review_dispatcher.py`
- Create: `app/services/code_review/review_run_service.py`
- Create: `app/services/code_review/timeline_service.py`
- Create: `app/routers/code_review_runs.py`
- Modify: `app/main.py`
- Test: `tests/test_code_review_runs.py`

- [ ] **Step 1: Write the failing run orchestration test**

Cover:
- dispatcher enqueue contract
- run status flow `queued -> analyzing -> completed`
- failed analysis transitions to `failed`
- timeline events are appended through one service
- run list/detail endpoints return findings and timeline

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_code_review_runs.py -v`
Expected: FAIL because dispatcher, run service, and routes do not exist.

- [ ] **Step 3: Write the timeline service**

Implement a focused service that records deduplicated timeline events with:
- `review_run_id`
- `event_type`
- optional `dedupe_key`
- structured payload

- [ ] **Step 4: Write the run service and dispatcher**

Implement:
- a dispatcher interface with `enqueue(run_id)`
- a first-phase local async task implementation
- review run query helpers
- state transitions for `queued`, `analyzing`, `completed`, `failed`

- [ ] **Step 5: Add run routes**

Create endpoints:
- `GET /api/code-review/runs`
- `GET /api/code-review/runs/{run_id}`

Return run summary, findings, and timeline in the detail response.

- [ ] **Step 6: Register the router**

Update `app/main.py` to include the runs router in the protected route set.

- [ ] **Step 7: Run test to verify it passes**

Run: `uv run pytest tests/test_code_review_runs.py -v`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add app/services/code_review/review_dispatcher.py app/services/code_review/review_run_service.py app/services/code_review/timeline_service.py app/routers/code_review_runs.py app/main.py tests/test_code_review_runs.py
git commit -m "feat: add review run orchestration"
```

### Task 6: Implement Analyzer and Automatic Fix Request Generation

**Files:**
- Create: `app/services/code_review/review_analyzer.py`
- Modify: `app/services/code_review/review_run_service.py`
- Test: `tests/test_code_review_runs.py`

- [ ] **Step 1: Extend the failing analyzer test**

Cover:
- analyzer reads diff context from provider adapters
- findings are persisted for a run
- `can_auto_fix` is set according to severity and rule metadata
- repository config with `auto_fix_enabled` automatically creates `ReviewFixRequest`
- fix requests start in `pending_approval`

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_code_review_runs.py -v`
Expected: FAIL because the analyzer and auto-fix policy logic do not exist.

- [ ] **Step 3: Write minimal analyzer implementation**

Implement a backend analyzer abstraction that:
- marks the run as `analyzing`
- fetches diff context
- produces normalized findings
- persists findings
- creates automatic fix requests from repository config policy
- records analysis lifecycle timeline events

The first implementation can use deterministic test doubles or stubbed logic instead of a real AI engine.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_code_review_runs.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/services/code_review/review_analyzer.py app/services/code_review/review_run_service.py tests/test_code_review_runs.py
git commit -m "feat: add analyzer and auto fix request generation"
```

### Task 7: Implement Fix Approval Workflow and Runner Adapter

**Files:**
- Create: `app/services/code_review/fix_runner.py`
- Create: `app/services/code_review/fix_service.py`
- Create: `app/routers/code_review_fixes.py`
- Modify: `app/main.py`
- Test: `tests/test_code_review_fixes.py`

- [ ] **Step 1: Write the failing fix workflow test**

Cover:
- only members with approval rights can approve fix requests
- rejecting a request moves it to `rejected`
- approving a request moves it through `approved -> running`
- stub runner returns a stable `runner_job_id`
- callback transitions fix requests to `completed` or `failed`
- duplicate callbacks do not corrupt state

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_code_review_fixes.py -v`
Expected: FAIL because fix service, runner adapter, and routes do not exist.

- [ ] **Step 3: Write the runner adapter**

Implement a first-phase stub runner with:
- `start_fix(fix_request)` returning `runner_job_id`
- callback payload contract for terminal states

Do not perform real branch or PR or MR creation in phase 1.

- [ ] **Step 4: Write the fix service**

Implement:
- membership permission checks
- approve flow
- reject flow
- callback handling
- timeline updates for approval and runner lifecycle

- [ ] **Step 5: Add fix routes**

Create endpoints:
- `POST /api/code-review/fix-requests/{id}/approve`
- `POST /api/code-review/fix-requests/{id}/reject`
- `POST /api/code-review/fix-runner/callback`

The callback route should be public; approval and rejection routes should be protected.

- [ ] **Step 6: Register the router**

Update `app/main.py` to include the protected fixes router and the public callback router.

- [ ] **Step 7: Run test to verify it passes**

Run: `uv run pytest tests/test_code_review_fixes.py -v`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add app/services/code_review/fix_runner.py app/services/code_review/fix_service.py app/routers/code_review_fixes.py app/main.py tests/test_code_review_fixes.py
git commit -m "feat: add fix approval workflow and runner adapter"
```

### Task 8: Add Publish Adapter Contract Without Real Provider Publishing

**Files:**
- Modify: `app/services/code_review/review_run_service.py`
- Modify: `app/routers/code_review_runs.py`
- Test: `tests/test_code_review_runs.py`

- [ ] **Step 1: Extend the failing publish contract test**

Cover:
- publish endpoint exists
- disabled publish configuration returns a safe rejection
- enabled publish configuration calls a stub publish path without posting real provider comments
- timeline records publish attempt events

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_code_review_runs.py -v`
Expected: FAIL because the publish contract is missing.

- [ ] **Step 3: Write minimal publish contract implementation**

Add a publish entrypoint that:
- checks repository config
- records a timeline attempt
- returns a stable stub response

Keep provider-specific comment publication deferred to a later phase.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_code_review_runs.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/services/code_review/review_run_service.py app/routers/code_review_runs.py tests/test_code_review_runs.py
git commit -m "feat: add publish adapter contract"
```

### Task 9: Add End-to-End Backend Flow Test

**Files:**
- Create: `tests/test_code_review_end_to_end.py`

- [ ] **Step 1: Write the failing end-to-end test**

Cover the full stubbed backend flow:
- sync repository
- enable repository review and auto-fix config
- ingest webhook
- create queued run
- complete analysis
- persist findings
- automatically create fix request
- approve fix request
- receive runner callback
- reach terminal fix request state

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_code_review_end_to_end.py -v`
Expected: FAIL because at least one part of the full flow is still missing.

- [ ] **Step 3: Fill the remaining integration gaps**

Implement the minimum cross-module glue required for the full stubbed flow to pass cleanly.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_code_review_end_to_end.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_code_review_end_to_end.py app/routers app/services/code_review app/models/code_review.py
git commit -m "test: add code review backend end-to-end coverage"
```

### Task 10: Update Backend Documentation

**Files:**
- Modify: `CLAUDE.md`
- Create: `docs/backend/code_review_platform.md`

- [ ] **Step 1: Write the failing docs checklist**

Create a manual checklist in the docs change describing:
- new backend module location
- migration requirement
- public webhook routes
- protected repository/run/fix routes
- first-phase runner limitations

- [ ] **Step 2: Write documentation**

Update `CLAUDE.md` with the new backend module reference and add a dedicated backend doc for the platform architecture and operational constraints.

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md docs/backend/code_review_platform.md
git commit -m "docs: add code review platform backend documentation"
```

### Task 11: Full Backend Verification

**Files:**
- No code changes required unless verification finds gaps

- [ ] **Step 1: Run targeted backend test suite**

Run: `uv run pytest tests/test_code_review_models.py tests/test_code_review_repository_service.py tests/test_code_review_webhooks.py tests/test_code_review_runs.py tests/test_code_review_fixes.py tests/test_code_review_end_to_end.py -v`
Expected: PASS

- [ ] **Step 2: Run broader backend regression coverage**

Run: `uv run pytest tests/test_custom_routes_smoke.py tests/test_scm_connections.py tests/test_app_main_nullpool.py tests/test_app_main_recovery.py -v`
Expected: PASS

- [ ] **Step 3: Run backend lint if needed**

Run: `uv run ruff check app tests`
Expected: PASS

- [ ] **Step 4: Fix any failures**

If any command fails, fix the issue and rerun the affected verification command before proceeding.

- [ ] **Step 5: Commit final verification fixes if needed**

```bash
git add -A
git commit -m "chore: finish code review backend verification"
```

## Notes for Implementation

- Keep all new review routes under `/api/code-review/...`.
- Do not recreate the removed legacy route shapes unless a later requirement explicitly demands compatibility.
- Reuse existing auth and SCM integrations; do not fork OAuth behavior into the new module.
- Keep webhook handlers fast and non-blocking.
- Centralize timeline writes to avoid inconsistent event history.
- Keep the runner contract stable even though phase 1 uses a stub implementation.
