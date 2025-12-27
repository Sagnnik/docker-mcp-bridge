FROM python:3.12-slim-bookworm AS builder

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_LINK_MODE=copy

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Copy ROOT workspace metadata
COPY pyproject.toml uv.lock ./

# Copy API workspace metadata
COPY api/pyproject.toml api/pyproject.toml

# Copy API source
COPY api api

# Create venv and install ONLY the api workspace
RUN uv venv \
 && . /app/.venv/bin/activate \
 && uv sync \
 && uv sync --package api

FROM python:3.12-slim-bookworm AS final

# Copy uv binary and virtualenv
COPY --from=builder /bin/uv /usr/bin/
COPY --from=builder /app/.venv /app/.venv

WORKDIR /app

# Copy only runtime-required files
COPY api ./api

ENV PYTHONPATH="/app/api:${PYTHONPATH:-}"

EXPOSE 8000

# Run FastAPI
CMD ["uv", "run", "uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]