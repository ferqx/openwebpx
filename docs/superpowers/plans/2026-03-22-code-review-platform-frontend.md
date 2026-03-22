# Code Review Platform Frontend Plan

**Goal:** Add the phase-1 code review frontend inside the existing portal shell without introducing a new top-level entry, while keeping task mode intact and reusing the existing repository/branch context.

## Scope
- Add `代码审查` as a portal work tab.
- Add review run list and detail UI.
- Add repository review settings drawer.
- Add `继续修复` dialog for sending findings back into a thread.
- Wire publish and fix approval actions to backend phase-1 APIs.
- Add focused hook and component tests for the new frontend state and route behavior.

## Out of Scope
- Real-time streaming for review runs
- Thread picker beyond current thread context
- Partial finding selection for continue-fix
- Provider-specific publish UI
- New global navigation entry

## Task 1: Add Frontend Review Domain Types and API Client

**Files:**
- Create: `web/src/lib/code-review.ts`
- Create: `web/src/business/portal/code-review-types.ts`
- Test: `web/src/lib/code-review.test.ts`

### Steps
- Add typed request/response models for:
  - repository config
  - review run summary/detail
  - review finding
  - fix request
  - publish response
- Add API helpers for repository config, run list/detail, publish, approve, reject.
- Add lightweight tests for payload normalization and endpoint wrappers.

## Task 2: Extend Portal Tab State for Review Mode

**Files:**
- Modify: `web/src/business/portal/types.ts`
- Modify: `web/src/hooks/use-portal-page-controller.ts`
- Modify: `web/src/business/portal/portal-task-toolbar.tsx`
- Modify: `web/src/business/portal/portal-task-content.tsx`
- Test: `web/src/hooks/use-portal-page-controller.test.ts`

### Steps
- Extend `PortalTab` from `tasks` to `tasks | review`.
- Add tab switch handling for the new review tab.
- Make toolbar action area tab-aware:
  - tasks => search
  - review => settings
- Keep the portal shell unchanged outside the tab content contract.

## Task 3: Add Review List State Hook

**Files:**
- Create: `web/src/hooks/use-portal-code-review-state.ts`
- Test: `web/src/hooks/use-portal-code-review-state.test.ts`

### Steps
- Manage:
  - loading
  - selected run id
  - filters
  - search
  - run fetch lifecycle
- Scope data to the selected repository context from the existing portal SCM state.
- Return derived values for:
  - visible runs
  - empty state messaging
  - pending approval emphasis

## Task 4: Build Review Run List UI

**Files:**
- Create: `web/src/business/portal/portal-code-review-list.tsx`
- Create: `web/src/business/portal/portal-code-review-run-card.tsx`
- Modify: `web/src/business/portal/portal-task-content.tsx`
- Test: `web/src/business/portal/portal-code-review-list.test.tsx`

### Steps
- Add a new `TabsContent value="review"`.
- Render list toolbar filters and search.
- Render run cards with:
  - status
  - repository / PR-MR metadata
  - branch summary
  - finding counts
  - mode badges
- Add loading, empty, and filtered-empty states.

## Task 5: Build Review Detail UI

**Files:**
- Create: `web/src/business/portal/portal-code-review-detail.tsx`
- Create: `web/src/business/portal/portal-code-review-findings.tsx`
- Create: `web/src/business/portal/portal-code-review-sidebar.tsx`
- Test: `web/src/business/portal/portal-code-review-detail.test.tsx`

### Steps
- Add detail view for selected run.
- Use split layout:
  - findings main column
  - summary/actions/timeline side column
- Add finding filters and expandable finding cards.
- Show run summary and timeline.

## Task 6: Add Review Settings Drawer

**Files:**
- Create: `web/src/business/portal/portal-code-review-settings-sheet.tsx`
- Modify: `web/src/hooks/use-portal-page-controller.ts`
- Test: `web/src/business/portal/portal-code-review-settings-sheet.test.tsx`

### Steps
- Add settings sheet open state to portal controller.
- Load and save repository review config.
- Support:
  - review enabled
  - auto fix enabled
  - auto fix requires approval
  - auto fix severities
  - auto publish enabled

## Task 7: Add Publish and Fix Approval Actions

**Files:**
- Modify: `web/src/hooks/use-portal-code-review-state.ts`
- Modify: `web/src/business/portal/portal-code-review-sidebar.tsx`
- Test: `web/src/hooks/use-portal-code-review-state.test.ts`

### Steps
- Add publish action for completed runs.
- Add approve/reject actions for fix requests.
- Respect backend state constraints and show action loading states.
- Refresh run detail after action completion.

## Task 8: Add Continue-Fix Dialog

**Files:**
- Create: `web/src/business/portal/portal-code-review-continue-fix-dialog.tsx`
- Modify: `web/src/hooks/use-portal-page-controller.ts`
- Modify: `web/src/hooks/use-portal-code-review-state.ts`
- Test: `web/src/business/portal/portal-code-review-continue-fix-dialog.test.tsx`

### Steps
- Show the dialog only when:
  - auto-fix is disabled
  - findings exist
  - current thread context exists
- Prefill the prompt with review-fix instructions.
- Append a new user message into the active thread continuation path.
- Navigate to or refocus the thread detail after submit.

## Task 9: Add Frontend Route/Interaction Verification

**Files:**
- Test: `web/src/pages/portal.test.tsx`
- Test: `web/src/pages/task-detail.test.tsx`

### Steps
- Verify tab switching.
- Verify portal tab state survives navigation to task detail and back.
- Verify review actions remain scoped to review tab only.

## Task 10: Update Frontend Documentation

**Files:**
- Modify: `web/CLAUDE.md`
- Modify: `web/AGENTS.md` if indexing needs updating
- Create or modify: `web/docs/changelogs/<date>.md`

### Steps
- Document the new review tab surfaces, major hooks, and current phase-1 constraints.

## Task 11: Final Frontend Verification

### Steps
- Run targeted frontend tests for new hooks and components.
- Run lint/build checks for touched frontend files.
- Fix regressions before moving to implementation completion.

### Expected verification commands
- `pnpm --prefix web test:hooks`
- `pnpm --prefix web test:lib`
- `pnpm --prefix web lint`
