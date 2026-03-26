# Code Review Single-Thread Queue Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep review continuation and approved fix execution on the same existing task thread, with FIFO queued execution instead of creating or selecting alternate threads.

**Architecture:** Frontend continuation flow will treat `ReviewRun.thread_id` as the only valid target and stop offering thread selection. Backend fix approval will stop launching separate runner work and instead enqueue a repair message against the bound thread, dispatching immediately only when the thread is idle. Queue state will be expressed through the existing review/fix status model plus a lightweight per-thread queue integration.

**Tech Stack:** FastAPI, SQLAlchemy async session, Aegra thread/run APIs, React 19, TypeScript, node:test, pytest

---

### Task 1: Lock The Frontend To `run.thread_id`

**Files:**
- Modify: `web/src/hooks/use-portal-code-review-continuation.ts`
- Modify: `web/src/business/portal/portal-code-review-continue-fix-dialog.tsx`
- Test: `web/test/hooks/use-portal-code-review-state.test.ts`
- Test: `web/test/pages/review-detail-page.test.ts`

- [ ] **Step 1: Write the failing frontend tests**

Add tests that assert:
- continuation ignores same-repo alternate tasks
- continuation is enabled only when `selectedRun.thread_id` exists
- continuation navigates to `/tasks/{thread_id}`

- [ ] **Step 2: Run the targeted frontend tests to verify they fail**

Run: `pnpm --prefix web exec node --import tsx --test test/pages/review-detail-page.test.ts test/hooks/use-portal-code-review-state.test.ts`

Expected: FAIL on assertions that still reflect selectable threads or missing direct thread binding.

- [ ] **Step 3: Implement the minimal continuation changes**

Change the hook and dialog so:
- `run.thread_id` is the only continuation target
- thread selection UI is removed or rendered as read-only context
- missing local task metadata does not block navigation to `/tasks/{thread_id}`

- [ ] **Step 4: Run the targeted frontend tests to verify they pass**

Run: `pnpm --prefix web exec node --import tsx --test test/pages/review-detail-page.test.ts test/hooks/use-portal-code-review-state.test.ts`

Expected: PASS

- [ ] **Step 5: Run frontend lint**

Run: `pnpm --prefix web exec eslint src/hooks/use-portal-code-review-continuation.ts src/business/portal/portal-code-review-continue-fix-dialog.tsx test/pages/review-detail-page.test.ts test/hooks/use-portal-code-review-state.test.ts`

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add web/src/hooks/use-portal-code-review-continuation.ts web/src/business/portal/portal-code-review-continue-fix-dialog.tsx web/test/pages/review-detail-page.test.ts web/test/hooks/use-portal-code-review-state.test.ts
git commit -m "feat: bind review continuation to review thread"
```

### Task 2: Add Backend Queue Contract For Approved Fixes

**Files:**
- Modify: `app/services/code_review/fix_service.py`
- Modify: `app/services/code_review/fix_runner.py`
- Test: `tests/test_code_review_fixes.py`

- [ ] **Step 1: Write the failing backend tests**

Add service tests covering:
- approving a fix uses the run's existing `thread_id`
- approving a fix fails clearly when `thread_id` is missing
- approving a fix does not create or return a new thread id

- [ ] **Step 2: Run the targeted backend tests to verify they fail**

Run: `uv run pytest tests/test_code_review_fixes.py -q -k 'approve and thread'`

Expected: FAIL because approval currently does not model queue-on-existing-thread semantics.

- [ ] **Step 3: Implement the minimal backend queue contract**

Update fix approval flow so it:
- resolves `ReviewRun.thread_id`
- rejects approval when it is absent
- builds a repair instruction for the existing thread
- returns queue-backed runner metadata without creating another thread

Keep the implementation minimal and aligned with the current Phase 1 architecture.

- [ ] **Step 4: Run the targeted backend tests to verify they pass**

Run: `uv run pytest tests/test_code_review_fixes.py -q -k 'approve and thread'`

Expected: PASS

- [ ] **Step 5: Run Python compile verification**

Run: `python3 -m py_compile app/services/code_review/fix_service.py app/services/code_review/fix_runner.py tests/test_code_review_fixes.py`

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add app/services/code_review/fix_service.py app/services/code_review/fix_runner.py tests/test_code_review_fixes.py
git commit -m "feat: enqueue approved fixes on existing review thread"
```

### Task 3: Serialize Fix Work Per Thread

**Files:**
- Modify: `app/services/code_review/fix_service.py`
- Modify: existing thread/run integration code that dispatches work onto Aegra threads
- Test: `tests/test_code_review_fixes.py`

- [ ] **Step 1: Write the failing queue-order tests**

Add tests that assert:
- a busy thread does not start the next approved fix immediately
- additional approved fixes are queued FIFO on the same thread

- [ ] **Step 2: Run the targeted queue tests to verify they fail**

Run: `uv run pytest tests/test_code_review_fixes.py -q -k 'queue or fifo'`

Expected: FAIL because per-thread queued sequencing is not implemented yet.

- [ ] **Step 3: Implement the minimal serialized queue behavior**

Add a lightweight queue mechanism that:
- scopes queued work per `thread_id`
- dispatches only one active fix/review follow-up at a time per thread
- leaves later items waiting until current work finishes

Avoid priority, cancellation, or preemption in this phase.

- [ ] **Step 4: Run the targeted queue tests to verify they pass**

Run: `uv run pytest tests/test_code_review_fixes.py -q -k 'queue or fifo'`

Expected: PASS

- [ ] **Step 5: Run broader fix-service regression tests**

Run: `uv run pytest tests/test_code_review_fixes.py -q`

Expected: PASS or only known unrelated environment-blocked failures documented clearly.

- [ ] **Step 6: Commit**

```bash
git add app/services/code_review/fix_service.py tests/test_code_review_fixes.py
git commit -m "feat: serialize approved fix work per thread"
```

### Task 4: Align Review Detail Messaging And Docs

**Files:**
- Modify: `web/src/pages/review-detail.tsx`
- Modify: `docs/changelogs/2026-03-26.md`
- Modify: `docs/backend/code_review_platform.md`

- [ ] **Step 1: Write the failing source-level assertions if needed**

Add or update assertions that review detail messaging reflects:
- one bound thread
- queued continuation/fix semantics

- [ ] **Step 2: Run the targeted source-level tests to verify they fail**

Run: `pnpm --prefix web exec node --import tsx --test test/pages/review-detail-page.test.ts`

Expected: FAIL if old selectable-thread wording remains.

- [ ] **Step 3: Implement the copy and documentation updates**

Update user-facing hints and docs so they describe:
- single-thread execution
- queued approved fixes
- no alternate thread selection

- [ ] **Step 4: Run the targeted source-level tests to verify they pass**

Run: `pnpm --prefix web exec node --import tsx --test test/pages/review-detail-page.test.ts`

Expected: PASS

- [ ] **Step 5: Run final verification commands**

Run:
- `pnpm --prefix web exec eslint src/pages/review-detail.tsx`
- `python3 -m py_compile app/services/code_review/fix_service.py app/services/code_review/fix_runner.py`

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add web/src/pages/review-detail.tsx docs/changelogs/2026-03-26.md docs/backend/code_review_platform.md
git commit -m "docs: describe single-thread queued review fixes"
```
