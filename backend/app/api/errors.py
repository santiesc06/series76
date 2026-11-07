"""One error format for every failure (design C4): {"error": {"code": ..., "message": ...}}."""

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.agent.llm import LLMNotConfiguredError
from app.agent.runner import AgentError
from app.services.conversation import NotFoundError

log = logging.getLogger("api")

# Agent error codes that mean "try again later" rather than "the request was wrong".
AGENT_STATUS = {"agent_step_limit": 504}


def error_response(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}})


def register(app: FastAPI) -> None:
    @app.exception_handler(NotFoundError)
    async def not_found(_: Request, exc: NotFoundError) -> JSONResponse:
        return error_response(404, "not_found", f"{exc.what} not found.")

    @app.exception_handler(AgentError)
    async def agent_failed(_: Request, exc: AgentError) -> JSONResponse:
        log.warning("agent error", extra={"code": exc.code})
        return error_response(AGENT_STATUS.get(exc.code, 502), exc.code, exc.message)

    @app.exception_handler(LLMNotConfiguredError)
    async def not_configured(_: Request, exc: LLMNotConfiguredError) -> JSONResponse:
        return error_response(503, "llm_not_configured", "The language model is not configured.")

    @app.exception_handler(OperationalError)
    async def database_down(_: Request, exc: OperationalError) -> JSONResponse:
        log.error("database unavailable", extra={"error": str(exc.orig)})
        return error_response(503, "database_unavailable", "The database is not reachable.")

    @app.exception_handler(RequestValidationError)
    async def invalid_request(_: Request, exc: RequestValidationError) -> JSONResponse:
        first = exc.errors()[0] if exc.errors() else {}
        field = ".".join(str(p) for p in first.get("loc", [])[1:]) or "request"
        return error_response(422, "invalid_request", f"{field}: {first.get('msg', 'invalid')}")

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = "not_found" if exc.status_code == 404 else "http_error"
        return error_response(exc.status_code, code, str(exc.detail))

    @app.exception_handler(Exception)
    async def unexpected(_: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled error")
        return error_response(500, "internal_error", "Something went wrong. Please retry.")
