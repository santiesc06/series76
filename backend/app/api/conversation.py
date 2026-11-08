"""Conversation endpoints (design C1)."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from langchain_core.language_models.chat_models import BaseChatModel
from sqlalchemy.orm import Session

from app.agent.llm import get_chat_model
from app.api.schemas import (
    ConversationRequest,
    ConversationResponse,
    DebugInfo,
    ErrorResponse,
    SessionMessages,
    SessionSummary,
)
from app.auth.deps import CurrentUser
from app.config import get_settings
from app.db.session import get_db
from app.services import conversation
from app.services.conversation import NotFoundError

router = APIRouter(prefix="/api", tags=["conversation"])
DB = Annotated[Session, Depends(get_db)]
ERRORS = {
    401: {"model": ErrorResponse},
    404: {"model": ErrorResponse},
    422: {"model": ErrorResponse},
}


@router.post(
    "/conversation",
    response_model=ConversationResponse,
    responses={**ERRORS, 502: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
)
def converse(
    body: ConversationRequest,
    user: CurrentUser,
    db: DB,
    model: Annotated[BaseChatModel, Depends(get_chat_model)],
) -> dict:
    """Ask a question. Without `session_id` a new conversation starts; with it, it continues."""
    return conversation.handle_turn(db, model, body.query, body.session_id, user_id=user.id)


@router.get("/sessions", response_model=list[SessionSummary], responses=ERRORS)
def sessions(user: CurrentUser, db: DB) -> list[dict]:
    """The user's saved conversations, most recently active first."""
    return conversation.list_sessions(db, user.id)


@router.get("/sessions/{session_id}/messages", response_model=SessionMessages, responses=ERRORS)
def messages(session_id: uuid.UUID, user: CurrentUser, db: DB) -> dict:
    """Full history of a conversation, to resume it."""
    return conversation.session_messages(db, session_id, user.id)


@router.get(
    "/messages/{message_id}/debug",
    response_model=DebugInfo,
    responses=ERRORS,
    tags=["developer"],
)
def debug(message_id: uuid.UUID, user: CurrentUser, db: DB) -> dict:
    """Developer only: tool calls, parameters, results, tokens and checks for one answer."""
    if not get_settings().debug_endpoints:
        raise NotFoundError("Message")  # behaves as if the endpoint did not exist
    return conversation.message_debug(db, message_id, user.id)
