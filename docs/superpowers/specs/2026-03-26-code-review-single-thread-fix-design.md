# Code Review Single-Thread Queue Design

## Goal

Ensure a review run and all follow-up fix work stay bound to one task thread. The review detail page remains separate, but review continuation and approved fix execution must use the review run's existing `thread_id`, must not allow selecting any other thread, and must execute through a serialized message queue on that same thread.

## Context

The current system already persists `ReviewRun.thread_id` on the backend and exposes it in run detail payloads. That means the data model already has a canonical thread binding for each review run.

The inconsistency is in two places:

- The frontend continuation flow. `use-portal-code-review-continuation.ts` derives a list of "same repository" task options and lets the user choose among them. This makes review follow-up work drift away from the thread already associated with the run.
- The fix approval path conceptually treats fix execution as a separate runner concern instead of "one more message on the same working thread". That conflicts with the operational cost of threads in this system, where each thread implies container bootstrap, repo checkout, and dependency installation.

The user's explicit requirement is that review and fix are just different messages in the same conversation thread. The thread is the durable execution environment.

## Decision

Use `ReviewRun.thread_id` as the single source of truth for all review-follow-up execution.

This applies to both:

- manual "continue fix" behavior from the review detail workflow
- approved fix requests triggered from review findings

When a review run has a bound `thread_id`, the system must append a new message into that same thread. When a review run does not have a bound `thread_id`, the UI must not offer continuation and the backend must not attempt automatic fix execution.

The thread becomes a serialized work queue:

- new review/fix follow-up messages are queued onto the bound thread
- only one execution runs at a time per thread
- new work waits until the current run completes
- no approval flow may create a separate fix thread
- no approval flow may interrupt an active run for this phase

## Non-Goals

- Do not merge the review detail page into task detail.
- Do not change the backend schema for `ReviewRun`.
- Do not introduce automatic thread creation for runs that currently lack `thread_id`.
- Do not implement run preemption or priority queueing.
- Do not redesign the reject flow beyond preserving single-thread semantics.

## Current Behavior

### Backend

- `ReviewRun.thread_id` is populated by analysis flow and returned by `CodeReviewRunService`.
- Fix request approval/rejection is attached to the review run and does not currently allow choosing a different thread.
- The current fix runner path is modeled as a separate execution concern rather than an enqueue-on-existing-thread operation.

### Frontend

- `ReviewDetailPage` shows the bound thread link when `run.thread_id` exists.
- `use-portal-code-review-continuation.ts` derives task options from same-repository task threads.
- The continue-fix dialog lets the user choose from those task options before navigating to a task thread with `initialPrompt` and `shouldAutoRun`.

## Proposed Behavior

### Single-Thread Rule

- A review run owns exactly one execution thread: `ReviewRun.thread_id`.
- Review analysis, manual continuation, and approved fix execution all target that same thread.
- If `thread_id` is absent, review results remain viewable, but no follow-up execution can be started.

### Manual Continuation Rule

- If `selectedRun.thread_id` is present:
  - the continue-fix flow must target that thread only
  - the UI must not present a thread picker
  - the existing generated prompt flow remains unchanged
- If `selectedRun.thread_id` is missing:
  - the continue-fix action is unavailable
  - the hint text must explain that the current review has no associated task thread

### Approved Fix Rule

- Approving a fix request must append a repair instruction message onto `ReviewRun.thread_id`.
- If the bound thread currently has an active run, the repair instruction must be queued and executed later.
- If the bound thread is idle, the repair instruction may start immediately through the same queue mechanism.
- The persisted fix request status model should still move through approval/running/completed-or-failed, but "running" now means "accepted by the thread work queue / executing on the bound thread", not "launched in a separate fix runner thread".

### Queue Semantics

- Queue scope is per thread.
- Execution order is FIFO.
- Only one queued review/fix task may actively execute on a thread at a time.
- No queue item may interrupt an in-flight run in this phase.
- The implementation can be lightweight, but the API contract must behave as serialized work from the user's perspective.

### UI Semantics

- "Continue fix" means "continue in the associated task thread", not "pick a same-repo thread".
- The existing "查看关联线程" action remains valid and should still open the same `run.thread_id`.
- Any helper text that implies the user can choose another thread must be removed or rewritten.
- Approval UI and timeline wording should reflect queued execution on the existing thread rather than separate runner startup.

## File-Level Design

### web/src/hooks/use-portal-code-review-continuation.ts

- Remove dependency on repository-based task matching for continuation.
- Replace task-option derivation with direct resolution of the run's bound thread:
  - find the matching `TaskItem` by `selectedRun.thread_id`
  - if found, navigate to that task
  - if not found in the currently loaded thread list, still navigate using the thread id and omit `task` state if necessary
- `canContinueCodeReviewFix` should depend on `selectedRun.thread_id`, not on candidate options.
- Update hint text to reflect the single-thread rule.

### web/src/business/portal/portal-code-review-continue-fix-dialog.tsx

- Remove thread-selection UI or make it read-only with the bound thread shown as contextual info only.
- Keep instruction editing and prompt-template behavior unchanged.

### web/src/pages/review-detail.tsx

- No route change is required.
- The existing "查看关联线程" behavior remains.
- Any props passed into continuation logic should assume one bound thread only.

### Backend queueing surface

The backend must turn approved fixes into "append message to thread" work instead of a separate runner launch. The exact implementation can follow current Aegra thread/run capabilities, but the contract should look like this:

- resolve `ReviewRun.thread_id`
- build a deterministic fix instruction payload from the fix request and finding
- enqueue that instruction against the existing thread
- if the thread is idle, dispatch immediately
- if the thread is busy, persist queued state and return success without creating another thread

Likely touch points:

- app/services/code_review/fix_service.py
- app/services/code_review/fix_runner.py
- existing Aegra-backed thread/run integration paths

## Error Handling

- If a run has no `thread_id`, "continue fix" must be disabled and the user should see a clear hint rather than a failing action.
- If a fix request is approved for a run with no `thread_id`, the backend should reject it with a clear contract error instead of silently creating a new thread.
- If a run has `thread_id` but the task metadata is missing from the locally loaded thread list, navigation to `/tasks/{thread_id}` should still happen. Task detail page already has its own thread-loading behavior and should remain the fallback loader.
- If prompt generation or navigation fails, keep the existing toast error behavior.
- If queue insertion fails, surface a clear API error and do not transition the fix request into a misleading running state.

## Testing Strategy

### Frontend Tests

- Add or update hook tests to lock continuation behavior to `run.thread_id`.
- Verify that same-repository alternative threads are ignored.
- Verify that continuation is disabled when `thread_id` is absent.
- Verify that continuation navigates to `/tasks/{thread_id}` with the existing auto-run prompt payload.

### Backend Tests

- Add service tests proving approved fixes do not create a new thread id.
- Add tests proving approved fixes enqueue work onto the existing `ReviewRun.thread_id`.
- Add tests proving queued work stays FIFO when the thread is already busy.
- Add tests proving approval fails clearly when a run has no `thread_id`.

### Source-Level UI Tests

- Update page/component tests if they currently assume the dialog shows a selectable task list.

## Risks

- If some legacy review runs do not have `thread_id`, users will lose the ability to continue from them manually or approve auto-fix execution. This is acceptable for this change because the requirement is explicit single-thread binding.
- If the frontend still assumes the selected task object must exist locally, continuation could regress for stale thread lists. The implementation should prefer thread-id navigation over local-task presence.
- The queue implementation may expose hidden assumptions in the existing thread/run lifecycle if current task execution is not already serializable.

## Acceptance Criteria

- Review detail page still works as a separate page.
- "Continue fix" never allows selecting a different thread from the review run's bound thread.
- Approving a fix request never creates a new thread.
- Approved fix work is enqueued onto the existing `ReviewRun.thread_id`.
- When a thread is already busy, newly approved fix work waits in FIFO order.
- When `run.thread_id` exists, continuation always navigates to `/tasks/{thread_id}`.
- When `run.thread_id` is missing, continuation is unavailable and approval cannot start execution.
- Existing review detail "查看关联线程" action still opens the same associated thread.
