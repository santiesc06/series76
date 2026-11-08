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
# The uv download cache lives in a build cache mount, not in the image (~600 MB less).
COPY backend/pyproject.toml backend/uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-default-groups --no-install-project

# Voice (US-22, design V3): the Whisper model is downloaded here, into the image, so the container
# never needs Hugging Face at runtime. Change the model with the build arg (compose: WHISPER_MODEL).
ARG WHISPER_MODEL=small
ENV HF_HOME=/opt/hf     WHISPER_MODEL=${WHISPER_MODEL}
RUN python -c "import os; from faster_whisper import download_model; download_model(os.environ['WHISPER_MODEL'])"     && chmod -R a+rX /opt/hf
ENV HF_HUB_OFFLINE=1

COPY backend/ ./
# The verified dataset that `ingest load` puts into PostgreSQL (ingest/paths.py expects ../data).
COPY data/processed/ /app/data/processed/

RUN useradd --create-home --uid 10001 app
USER app

EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=5 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/health/ready', timeout=2)"]

# On every start: migrate the schema, (re)load the catalog (idempotent, conversations untouched),
# create the test users (idempotent), then serve. Design A4, U5, US-20 AC1.
CMD ["sh", "-c", "alembic upgrade head && python -m ingest load && python -m app.auth.seed && exec uvicorn app.main:app --host 0.0.0.0 --port 8000"]
