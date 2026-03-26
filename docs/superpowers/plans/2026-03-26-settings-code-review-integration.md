# Settings Code Review Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move code review settings into the main settings page and switch repository toggles to immediate persistence.

**Architecture:** Extract the code review settings UI into a reusable section component hosted by `SettingsPage`, then route portal settings actions to `?tab=code-review`. Replace page-wide draft saving with per-repository optimistic updates plus rollback on failure.

**Tech Stack:** React 19, TypeScript, React Router, shadcn/ui, existing portal hooks

---

### Task 1: Lock the new page structure with tests

**Files:**
- Modify: `web/test/pages/code-review-settings-page.test.ts`
- Create: `web/test/pages/settings-page.test.ts`

- [ ] Add a failing source-level test that asserts `SettingsPage` contains a code review tab/section entry.
- [ ] Add a failing source-level test that asserts the standalone code review page no longer contains the full settings implementation.
- [ ] Run the targeted tests to confirm they fail for the expected reason.

### Task 2: Extract the embedded code review settings section

**Files:**
- Create: `web/src/business/portal/code-review-settings-section.tsx`
- Modify: `web/src/pages/code-review-settings.tsx`

- [ ] Move the current code review settings UI into a reusable section component.
- [ ] Replace bulk draft/save behavior with per-row optimistic state, per-row saving flags, and rollback-on-error.
- [ ] Keep the section focused on code review settings content only, not full-page shell.

### Task 3: Integrate with SettingsPage and routing

**Files:**
- Modify: `web/src/pages/settings.tsx`
- Modify: `web/src/hooks/use-portal-page-controller.ts`
- Modify: `web/src/App.tsx`

- [ ] Add a `代码审查` tab/section to `SettingsPage` and render the extracted section there.
- [ ] Make portal entry navigation go to `/settings?tab=code-review`.
- [ ] Remove the standalone settings route or convert it to a lightweight redirect.

### Task 4: Verify and document

**Files:**
- Modify: `docs/changelogs/2026-03-26.md`

- [ ] Run targeted tests and eslint for the touched files.
- [ ] Update the changelog to describe the integration and real-time save behavior.
