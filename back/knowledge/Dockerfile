FROM ghcr.io/astral-sh/uv:python3.14-bookworm-slim

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_DEV=1 \
    PATH="/app/.venv/bin:$PATH" \
    KNOWLEDGE_DIR=/data/knowlage_files

COPY back/knowledge/pyproject.toml back/knowledge/uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

COPY back/knowledge/alembic.ini ./
COPY back/knowledge/alembic ./alembic
COPY back/knowledge/knowledge ./knowledge
COPY data/knowlage_files /data/knowlage_files
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

RUN useradd --system --uid 10001 --home /app app \
    && chown -R app:app /app /data/knowlage_files
USER app

EXPOSE 8001

HEALTHCHECK --interval=5s --timeout=5s --start-period=60s --retries=12 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8001/health')"]

CMD ["uvicorn", "knowledge.main:app", "--host", "0.0.0.0", "--port", "8001"]
