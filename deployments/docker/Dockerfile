FROM python:3.12-slim-bookworm AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Create non-root user for runtime
RUN addgroup --system app && adduser --system --ingroup app app

# -----------------------------
# Builder stage
# -----------------------------
FROM base AS builder

COPY --from=ghcr.io/astral-sh/uv:0.10.0 /uv /bin/uv

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install dependencies first (cached layer)
COPY pyproject.toml ./
COPY uv.loc[k] ./
RUN uv sync --no-dev --no-install-project --compile-bytecode

# Copy runtime files referenced by aegra.json and migrations.
COPY app/ ./app/
COPY backends/ ./backends/
COPY middleware/ ./middleware/
COPY graphs/ ./graphs/
COPY alembic/ ./alembic/
COPY alembic.ini ./
COPY aegra.json ./

# -----------------------------
# Runtime stage
# -----------------------------
FROM base AS final

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/app ./app
COPY --from=builder /app/backends ./backends
COPY --from=builder /app/middleware ./middleware
COPY --from=builder /app/graphs ./graphs
COPY --from=builder /app/alembic ./alembic
COPY --from=builder /app/alembic.ini ./alembic.ini
COPY --from=builder /app/aegra.json ./aegra.json

ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8000

USER app

CMD ["aegra", "serve", "--host", "0.0.0.0", "--port", "8000"]
