# Code Review Platform Frontend Design

## Goal
Add a phase-1 frontend experience for the backend code review platform without changing the current top-level portal shell. The new UI must live inside the existing portal page, reuse the current repository and branch context, and introduce a `代码审查` work tab parallel to the existing `任务` tab.

## Existing Shell Constraints
- Keep the current portal structure:
  - top header with logo and navigation actions
  - middle repository and branch prompt panel
  - lower work area driven by tabs
- Do not add a new top-level navigation entry for code review.
- Reuse the current repository and branch selection as the shared context for both tasks and code review.
- Preserve current task flows and task detail routing.

## Primary UX Model
The portal now has two parallel work modes:
- `任务`: thread-oriented execution workflow
- `代码审查`: review-oriented workflow

These modes are intentionally different:
- Task mode is about creating and continuing agent threads.
- Code review mode is about reading review runs, reviewing findings, handling fix approvals, and optionally sending findings back into a thread for manual follow-up.

## Portal Tab Behavior
- Add a new portal tab value: `review`.
- Tabs become:
  - `任务`
  - `代码审查`
- Toolbar action area is tab-sensitive:
  - `任务`: search button for tasks
  - `代码审查`: settings button for repository review configuration

## Code Review Work Area
The code review work area has two levels:

1. Run list view
- Default view for the `代码审查` tab.
- Shows review runs for the current repository context.
- Supports filtering and scanning for status, findings, and approval needs.

2. Run detail view
- Opens when a run is selected.
- Uses a split layout:
  - main column: findings
  - side column: run summary, actions, timeline

## Run List View
### Purpose
Help the user answer:
- What review runs exist for the selected repository?
- Which runs are still analyzing?
- Which runs need attention?
- Which runs have findings or pending approvals?

### Layout
- Top toolbar row inside the tab content:
  - status filter
  - mode filter
  - text search
- Main content:
  - card-style list of review runs

### Filters
- Status:
  - all
  - queued
  - analyzing
  - completed
  - failed
- Mode:
  - all
  - review only
  - auto-fix enabled
  - pending approval
- Search:
  - repository name
  - branch names
  - external PR or MR id

### Run Card Content
- status badge
- repository name
- provider + PR/MR identifier
- `head -> base` branch summary
- created time
- finding count
- fix request summary
- light mode badge:
  - `review only`
  - `auto-fix enabled`
  - `pending approval`

### Sorting
- newest first by default
- pending approval should be visually emphasized but not forcibly re-sorted beyond the default time order in phase 1

### Empty States
- No runs for repository:
  - explain that code review runs appear after repository review is configured and webhook events arrive
- Filtered empty state:
  - explain that no runs match the current filters

## Run Detail View
### Header
- back to run list
- run status badge
- repository full name
- external PR/MR identifier
- provider
- `head -> base` branch summary
- created time

### Main Column: Findings
- findings is the primary content area
- filter controls:
  - severity
  - auto-fix capable only
  - file path query
- finding cards include:
  - severity
  - title
  - file path and line range
  - body
  - rule id
  - auto-fix capability
  - fix request status when present

### Side Column
#### Run Summary
- run id
- provider
- event type
- commit ids
- current status

#### Actions
- `Publish`
  - enabled only when the run is `completed`
- `继续修复`
  - shown only when:
    - the run has findings
    - repository auto-fix is not enabled
    - a usable thread context exists
- `Approve` / `Reject`
  - shown when an auto-generated fix request exists and the current user can approve fixes

#### Timeline
- show lifecycle events in forward order
- event names should be humanized
- phase-1 events include:
  - review requested
  - queued
  - analysis started
  - analysis completed
  - analysis failed
  - fix request created
  - fix request approved
  - fix request running
  - fix request completed
  - fix request failed
  - publish requested
  - publish completed

## Repository Review Settings
### Entry
- triggered from the right-side button in the code review tab toolbar
- use a drawer or sheet, not a deep navigation page

### Fields
- `review_enabled`
- `auto_fix_enabled`
- `auto_fix_requires_approval`
- `auto_fix_severities`
- `auto_publish_enabled`

### UX Rule
- the settings panel is repository-scoped
- it must respect the repository selected in the existing prompt panel

## Continue Fix Flow
This is distinct from repository-level auto-fix.

### Intent
If the repository is not configured for auto-fix, the user can still decide to continue from review findings by appending a new user message to an existing task thread.

### Trigger
- available from run detail action area
- shown only for runs with findings when repository auto-fix is disabled

### Interaction
- open a lightweight dialog or sheet
- show:
  - target thread
  - summary of included findings
  - editable prompt text

### Defaults
- target thread: current selected thread context
- included findings: entire run
- prompt text: prefilled repair-oriented message

### Submit Result
- append a new user prompt to the chosen thread
- navigate to or refocus the thread detail page
- let the existing task/thread execution flow continue from there

### Phase-1 Limitation
- no partial finding selection yet
- no thread picker yet beyond current thread context

## State Model
Frontend state for code review should remain separate from task state.

Suggested phase-1 slices:
- portal tab selection
- review run list query state
- review run detail selected id
- review settings panel open state
- continue-fix dialog open state
- publish loading state
- fix approval loading state

## Backend Contracts Consumed
- `POST /api/code-review/repositories/sync`
- `GET /api/code-review/repositories`
- `GET /api/code-review/repositories/{id}/config`
- `PUT /api/code-review/repositories/{id}/config`
- `GET /api/code-review/runs`
- `GET /api/code-review/runs/{id}`
- `POST /api/code-review/runs/{id}/publish`
- `POST /api/code-review/fix-requests/{id}/approve`
- `POST /api/code-review/fix-requests/{id}/reject`

Phase-1 frontend does not need to call webhook or runner callback routes directly.

## Visual Direction
- Preserve the existing portal shell and design system.
- Do not introduce a separate product visual language.
- The code review surfaces should feel more like a compact workbench than the thread list.
- Use badges, grouped metadata, and consistent spacing to make statuses scannable.
- Avoid dense tables as the primary layout.

## Out of Scope
- Real-time review run streaming
- Thread picker for continue-fix
- Partial finding selection for continue-fix
- Provider-specific publish details
- Frontend support for real external analyzer or real fix runner execution differences

## Implementation Boundaries
- Add code review UI inside `web/src/business/portal/` and supporting hooks/lib code.
- Keep components under the existing size limits from `web/AGENTS.md`.
- Prefer adding new focused hooks instead of overloading `usePortalTaskState`.
- Maintain `loading -> data/empty` behavior with no empty-state flashing.
