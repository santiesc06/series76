"""FastAPI application entry point."""

from fastapi import FastAPI

from app.api import health
from app.config import get_settings
from app.logging_config import configure_logging

configure_logging(get_settings().log_level)

app = FastAPI(
    title="Series 76 Technical Assistant API",
    version="0.1.0",
    description="Answers questions about Series 76 electric actuators and recommends models.",
)

app.include_router(health.router)
