# OpenWebPX Full-Stack Monorepo (CLAUDE.md)

This file provides local development context. For global collaboration rules, refer to [AGENTS.md](AGENTS.md).

## 1. Documentation Map
- **Core Protocol**: [AGENTS.md](AGENTS.md)
- **Frontend Master Docs**: [web/AGENTS.md](web/AGENTS.md) & [web/CLAUDE.md](web/CLAUDE.md)
- **Tech Conventions**: [docs/development/conventions.md](docs/development/conventions.md)
- **Architecture**: [docs/architecture.md](docs/architecture.md)
- **Backend Code Review Platform**: [docs/backend/code_review_platform.md](docs/backend/code_review_platform.md)

## 2. Global Commands (Root)
- `make dev-install`: Setup both backend and frontend environments.
- `make run`: Run the backend server (`app.main:app`).
- `pnpm --prefix web dev`: Run the frontend dev server.
- `make ci-check`: Run all static checks and tests (Backend + Frontend).

## 3. Backend Commands (app/)
- `uv run pytest`: Run backend tests.
- `uv run ruff check .`: Lint Python code.
- `python scripts/migrate.py upgrade`: Apply DB migrations.

## 4. Frontend Commands (web/)
- See [web/CLAUDE.md](web/CLAUDE.md) for detailed frontend commands.
- `pnpm --prefix web test:hooks`: Run frontend unit tests.

## 4. Frontend Commands (web/)
- `pnpm --prefix web test:hooks`: Run frontend logic tests.
- `pnpm --prefix web test:e2e`: Run Playwright tests.

## 5. Directory Structure
- `app/`: FastAPI backend implementation.
- `web/`: React frontend project.
- `docs/`: Unified documentation center.
- `graphs/`: LangGraph agent definitions.
