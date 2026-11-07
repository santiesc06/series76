# Backend image: FastAPI + LangChain agent. Build from the repository root (it needs data/processed):
#   docker build -f backend/Dockerfile -t series76-backend .
# No secrets are baked in: keys arrive as environment variables at runtime (.dockerignore excludes .env).
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.13.2 /uv /usr/local/bin/uv

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    # Settings come only from real environment variables inside the container, never a .env file.
    APP_DISABLE_DOTENV=1

WORKDIR /app/backend

# Dependencies first (cached layer): runtime only, no dev/ingest groups (pymupdf, pytest, ruff).
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --locked --no-default-groups --no-install-project

COPY backend/ ./
# The verified dataset that `ingest load` puts into PostgreSQL (ingest/paths.py expects ../data).
COPY data/processed/ /app/data/processed/

RUN useradd --create-home --uid 10001 app
USER app

EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=5 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/health/ready', timeout=2)"]

# On every start: migrate the schema, (re)load the catalog (idempotent, conversations untouched),
# then serve. Design A4, US-20 AC1.
CMD ["sh", "-c", "alembic upgrade head && python -m ingest load && exec uvicorn app.main:app --host 0.0.0.0 --port 8000"]
