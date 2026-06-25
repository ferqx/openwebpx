# sandbox-agent Development (CLAUDE.md)

This file provides local development context. For global collaboration rules, refer to [AGENTS.md](AGENTS.md).

## 1. Documentation Index
- **Core Protocol**: [AGENTS.md](AGENTS.md)
- **Conventions & Constraints**: [docs/development/conventions.md](docs/development/conventions.md)
- **Architecture & Data Flow**: [docs/architecture.md](docs/architecture.md)
- **Core Hooks (Logic)**: [docs/development/state-hooks.md](docs/development/state-hooks.md)
- **AI Elements (UI)**: [docs/features/ai-elements.md](docs/features/ai-elements.md)
- **Testing & E2E**: [docs/development/testing-strategy.md](docs/development/testing-strategy.md)
- **Changelogs**: [docs/changelogs/](docs/changelogs/)

## 2. Local Commands
- `pnpm dev`: Start Vite dev server.
- `pnpm build` / `pnpm lint`: Build and check style.
- `pnpm test:hooks`: Run React Hooks tests.
- `pnpm test:lib`: Run library logic tests.
- `pnpm test:e2e`: Run Playwright E2E tests.
- `pnpm smoke:scm-connections`: SCM auth smoke test.
- `pnpm smoke:thread-cancel`: Thread-level cancel smoke test.

## 3. Tech Stack
- React 19 (Compiler), TypeScript, Vite 7, Tailwind 4.
- Shadcn UI, AI Elements, LangGraph SDK, AI SDK.

## 4. Key Rules
- **Import Aliases**: Always use `@/` for `src/`.
- **Constraint Thresholds**: Strictly follow 500/300 line limits defined in [AGENTS.md](AGENTS.md).
- **Quality Mandates**: Zero `any` usage; mandatory error handling; no empty-state flashing.
- **SCM**: Use `/integrations/scm/` endpoints; state source is the backend connections.
- **Portal Code Review**: The portal now contains a `review` tab alongside `tasks`. Review state lives in `use-portal-code-review-state.ts`; continue-fix thread handoff lives in `use-portal-code-review-continuation.ts`; all review UI stays under `src/business/portal/`.
