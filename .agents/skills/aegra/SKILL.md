---
name: Aegra
description: Use when deploying self-hosted AI agents, building LangGraph applications, configuring agent persistence and streaming, setting up authentication, managing threads and state, or migrating from LangSmith Deployments. Reach for this skill when working with Agent Protocol servers, configuring observability, or building production agent infrastructure.
metadata:
    mintlify-proj: aegra
    version: "1.0"
---

# Aegra Skill

## Product summary

Aegra is an open-source, self-hosted Agent Protocol server for running LangGraph agents on your own infrastructure. It's a drop-in replacement for LangSmith Deployments with the same SDK and APIs but no vendor lock-in. Agents use Aegra to deploy production-ready servers with PostgreSQL persistence, streaming, authentication, and observability. Key files: `aegra.json` (configuration), `.env` (environment variables), `Dockerfile` and `docker-compose.yml` (deployment). Primary CLI commands: `aegra init`, `aegra dev`, `aegra up`, `aegra serve`. [Full documentation](https://aegra.mintlify.app)

## When to use

Reach for this skill when:
- Deploying LangGraph agents to production with full persistence and state management
- Building multi-turn conversations with thread-based state checkpointing
- Configuring authentication (JWT, OAuth, Firebase, or custom handlers)
- Setting up real-time streaming with Server-Sent Events (SSE)
- Implementing human-in-the-loop approval gates before tool execution
- Migrating from LangSmith Deployments to self-hosted infrastructure
- Adding observability via OpenTelemetry to Langfuse, Phoenix, Datadog, or other OTLP backends
- Building semantic search with pgvector embeddings
- Extending the Agent Protocol API with custom FastAPI routes
- Troubleshooting agent execution, database connectivity, or configuration issues

## Quick reference

### CLI commands

| Command | Use case | Starts PostgreSQL? | Starts app? |
|---------|----------|-------------------|------------|
| `aegra init` | Create new project from template | — | — |
| `aegra dev` | Local development with hot reload | Yes (Docker) | Yes (host) |
| `aegra up` | Self-hosted Docker production | Yes (Docker) | Yes (Docker) |
| `aegra serve` | PaaS/Kubernetes (external DB) | No | Yes (host) |
| `aegra down` | Stop containers | — | — |

### Configuration files

| File | Purpose |
|------|---------|
| `aegra.json` | Graphs, auth, HTTP, semantic store config |
| `.env` | Database, tracing, API keys, secrets |
| `Dockerfile` | Container image definition |
| `docker-compose.yml` | PostgreSQL + app orchestration |

### Key aegra.json sections

```json
{
  "graphs": {
    "agent": "./graphs/agent.py:graph"
  },
  "auth": "./my_auth.py:auth",
  "dependencies": ["./shared", "./libs"],
  "http": {
    "app": "./custom_routes.py:app",
    "cors": {"allow_origins": ["https://myapp.com"]}
  },
  "store": {
    "index": {
      "embed": "openai:text-embedding-3-small",
      "dims": 1536
    }
  }
}
```

### Environment variables (critical)

| Variable | Purpose | Example |
|----------|---------|---------|
| `DATABASE_URL` | PostgreSQL connection | `postgresql://user:pass@localhost/aegra` |
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB` | Individual DB config (if no DATABASE_URL) | `myuser`, `secret`, `localhost`, `5432`, `aegra` |
| `OTEL_TARGETS` | Tracing backends (comma-separated) | `LANGFUSE,PHOENIX` |
| `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY` | Langfuse credentials | — |
| `PHOENIX_COLLECTOR_ENDPOINT` | Phoenix trace endpoint | `http://127.0.0.1:6006/v1/traces` |

## Decision guidance

### When to use each deployment command

| Scenario | Command | Notes |
|----------|---------|-------|
| Local development | `aegra dev` | Manages PostgreSQL container, hot reload enabled |
| Self-hosted production (your infrastructure) | `aegra up` | Full Docker stack, recommended for most deployments |
| PaaS platforms (Railway, Render, Fly.io) | `aegra serve` | Provide external PostgreSQL, runs app only |
| Kubernetes | `aegra serve` | Use in pod spec, external PostgreSQL required |

### When to use each storage option

| Need | Approach | Config |
|------|----------|--------|
| Simple key-value storage | Store API (default) | No config needed |
| Semantic similarity search | Semantic store with pgvector | Add `store.index` with embedding model |
| Thread state persistence | Threads API (automatic) | No config needed, uses PostgreSQL checkpoints |

### When to use each streaming mode

| Mode | Use case |
|------|----------|
| `values` | Full state snapshot after each node |
| `updates` | State delta (only changed fields) |
| `messages` | Token-by-token LLM output |
| `events` | LangGraph internal events for debugging |
| `custom` | User-defined data via `get_stream_writer()` |

## Workflow

### 1. Create and configure a project

```bash
pip install aegra-cli
aegra init
# Follow prompts: location, template (simple-chatbot or react-agent), project name
```

### 2. Define your graph

Create `graphs/agent.py` with a compiled LangGraph graph:

```python
from langgraph.graph import StateGraph

builder = StateGraph(State)
builder.add_node("agent", agent_node)
builder.set_entry_point("agent")
graph = builder.compile()
```

### 3. Register the graph in aegra.json

```json
{
  "graphs": {
    "agent": "./graphs/agent.py:graph"
  }
}
```

### 4. Configure authentication (if needed)

Create `my_auth.py`:

```python
from langgraph_sdk import Auth

auth = Auth()

@auth.authenticate
async def authenticate(headers: dict) -> dict:
    token = headers.get("Authorization", "").replace("Bearer ", "")
    if not token:
        raise Exception("Authentication required")
    # Verify JWT, OAuth, Firebase, etc.
    return {
        "identity": "user123",
        "display_name": "Jane Doe",
        "is_authenticated": True,
    }
```

Register in `aegra.json`: `"auth": "./my_auth.py:auth"`

### 5. Set up environment variables

Copy `.env.example` to `.env` and configure:

```bash
DATABASE_URL=postgresql://user:password@localhost:5432/aegra
OTEL_TARGETS=LANGFUSE
LANGFUSE_PUBLIC_KEY=pk_...
LANGFUSE_SECRET_KEY=sk_...
```

### 6. Start the server

```bash
# Local development
uv run aegra dev

# Production (Docker)
aegra up

# PaaS (external DB)
aegra serve
```

### 7. Verify and test

```bash
# Check health
curl http://localhost:8000/health

# View API docs
open http://localhost:8000/docs

# Create an assistant
curl -X POST http://localhost:8000/assistants \
  -H "Content-Type: application/json" \
  -d '{"graph_id": "agent", "assistant_id": "my_assistant"}'

# Create a thread and run
curl -X POST http://localhost:8000/threads/my_thread/runs \
  -H "Content-Type: application/json" \
  -d '{"assistant_id": "my_assistant", "input": {"messages": [{"type": "human", "content": "Hello"}]}}'
```

## Common gotchas

- **Using `aegra` instead of `aegra-cli`**: Install `aegra-cli` directly, not the `aegra` meta-package on PyPI. The meta-package doesn't support version pinning.

- **Database connection fails**: If using `aegra dev` or `aegra up`, ensure Docker is running. If using `aegra serve`, verify `DATABASE_URL` or individual `POSTGRES_*` variables in `.env` match your PostgreSQL instance.

- **Migrations haven't applied**: The server couldn't connect to PostgreSQL during startup. Check logs for connection errors, fix the connection, and restart. Verify no other process holds a database lock.

- **Wrong database credentials**: Ensure `POSTGRES_USER` and `POSTGRES_PASSWORD` in `.env` match what PostgreSQL was initialized with. If using Docker, check `docker-compose.yml` for the initial values.

- **Semantic store embedding mismatch**: The `dims` value in `store.index` must match your embedding model's output dimensions exactly. For `text-embedding-3-small`, use `1536`. Verify the embed format is `provider:model-id` (e.g., `openai:text-embedding-3-small`) and the API key is set.

- **Auth not applying to custom routes**: By default, custom FastAPI routes bypass Aegra auth. Set `"enable_custom_route_auth": true` in the `http` section of `aegra.json` to enforce authentication.

- **CORS errors**: Default is `allow_origins: ["*"]` with `allow_credentials: false`. When specifying concrete origins, `allow_credentials` defaults to `true`. Adjust in `aegra.json` as needed.

- **Streaming reconnection**: Use the `Last-Event-ID` header to resume from a specific event after a disconnect. The server will replay events from that point.

- **Thread state not persisting**: Ensure PostgreSQL is running and migrations have applied. State is automatically persisted after each node execution; no manual save is required.

- **Graph import errors**: Check that graph import paths in `aegra.json` are correct (`./path/to/file.py:variable`). The variable must be a compiled LangGraph graph. Use `dependencies` to add shared module paths to `sys.path`.

## Verification checklist

Before deploying or submitting work:

- [ ] Graph is compiled and exported correctly in `graphs/` directory
- [ ] Graph import path in `aegra.json` is correct (`./path/to/file.py:variable`)
- [ ] `.env` file exists with `DATABASE_URL` or individual `POSTGRES_*` variables
- [ ] If using auth, `auth` field in `aegra.json` points to valid auth handler
- [ ] If using semantic store, `store.index` has correct embedding model and `dims` matches model output
- [ ] If using custom routes, `http.app` points to valid FastAPI app
- [ ] If using dependencies, paths in `dependencies` array exist and are relative to config file
- [ ] Health endpoint responds: `curl http://localhost:8000/health`
- [ ] API docs load: `http://localhost:8000/docs`
- [ ] Can create an assistant via API
- [ ] Can create a thread and execute a run
- [ ] Streaming works: run with `stream=true` and receive SSE events
- [ ] If using auth, unauthenticated requests return 401
- [ ] If using observability, traces appear in configured backend (Langfuse, Phoenix, etc.)
- [ ] Database migrations completed without errors in logs

## Resources

- **Comprehensive navigation**: [llms.txt](https://aegra.mintlify.app/llms.txt) — page-by-page documentation index for agents
- **Configuration reference**: [aegra.json and environment variables](https://aegra.mintlify.app/reference/configuration)
- **Deployment guide**: [Docker, PaaS, and Kubernetes deployment](https://aegra.mintlify.app/guides/deployment)
- **Migration guide**: [Switching from LangSmith Deployments](https://aegra.mintlify.app/migration)

---

> For additional documentation and navigation, see: https://aegra.mintlify.app/llms.txt
