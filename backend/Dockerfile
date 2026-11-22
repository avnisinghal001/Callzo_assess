FROM python:3.13.18-slim AS base
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH"
WORKDIR /app

# Dependencies first, so source edits do not invalidate the cached install layer.
FROM base AS builder
COPY --from=ghcr.io/astral-sh/uv:0.11.18 /uv /usr/local/bin/uv
ENV UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

FROM base AS runtime
RUN useradd --system --uid 10001 --no-create-home app
COPY --from=builder /app/.venv /app/.venv
COPY app ./app
COPY migrations ./migrations
USER app
EXPOSE 8000
CMD ["uvicorn", "app.main:app_from_env", "--factory", "--host", "0.0.0.0", "--port", "8000", "--no-access-log", "--proxy-headers", "--timeout-graceful-shutdown", "15"]

FROM builder AS test
RUN uv sync --frozen --no-install-project
COPY pyproject.toml ./
COPY app ./app
COPY migrations ./migrations
COPY tests ./tests
CMD ["pytest", "-q"]
