# Code Review Settings Visual Alignment Design

## Goal
Align the standalone code review settings page with the portal homepage shell and the project's existing shadcn-style UI language, while keeping the separate settings route for repository review configuration.

## Constraints
- Keep the current navigation flow: users still click into a dedicated settings page.
- Reuse `PortalHeader` instead of maintaining a second page-specific header style.
- Preserve the existing data hooks and save behavior unless layout work requires a minimal structural adjustment.
- Keep changes focused on visual structure and component reuse.

## Design
- Use the same top-level shell rhythm as `portal.tsx`: `bg-background`, sticky top section, centered main column.
- Place `PortalHeader` at the top of the page and move the page-specific title, description, back action, and save/cancel actions into a lightweight page intro block below it.
- Remove the three feature promo cards and replace them with a compact summary card plus a global policy card.
- Keep the repository configuration area as a table-like editing surface, but restyle it with standard shadcn card, border, spacing, and muted treatments rather than dashboard-style shadows and saturated icon blocks.
- Keep empty/loading states, but tone them down to match the portal page.

## Component Boundaries
- Extend `PortalHeader` only as needed to support shared use from the settings page.
- Keep the code review settings page as the composition root for its intro block, global policy block, and repository configuration block.
