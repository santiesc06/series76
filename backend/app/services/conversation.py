"""One conversation turn, end to end (design §3, §4).

session -> history + context note -> agent (tools) -> number check (one repair) -> product cards
from the database -> persist user + assistant messages -> response.
"""

import logging
import re
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.agent.number_check import allowed_numbers, unsupported_numbers
from app.agent.runner import AgentRun, base_system_prompt, run_agent
from app.agent.schemas import FinalAnswer
from app.config import get_settings
from app.db.models import ChatSession, Message, Part
from app.observability import tracing_config
from app.services.presentation import highlights_for, product_card
from app.tools.catalog_tools import ToolRecorder, build_tools

log = logging.getLogger("conversation")

TITLE_LENGTH = 60
MAX_PRODUCTS = 5
MAX_ALTERNATIVES = 3
MAX_QUICK_REPLIES = 5
CONTEXT_TURNS = 3  # assistant turns whose products feed the context note
# Fixed fallback sentences (design B4c): picked without an LLM call, by the user's language.
FALLBACK_TEXT = {
    "en": "Here is the data from the catalog for your request.",
    "es": "Aquí están los datos del catálogo para tu consulta.",
}
SPANISH_WORDS = {
    "el", "la", "los", "las", "de", "del", "que", "qué", "cuál", "cual", "cuáles", "para", "con",
    "por", "un", "una", "es", "y", "necesito", "busco", "tiene", "cuánto", "cuanto", "modelo",
    "actuador", "zona", "potencia", "voltaje", "velocidad", "hola", "gracias", "sí", "más",
}  # fmt: skip
ENGLISH_WORDS = {
    "the", "of", "what", "which", "for", "with", "by", "an", "is", "and", "need", "looking",
    "has", "how", "much", "model", "actuator", "zone", "power", "voltage", "speed", "hello",
    "thanks", "yes", "more",
}  # fmt: skip


class NotFoundError(LookupError):
    def __init__(self, what: str):
        super().__init__(f"{what} not found")
        self.what = what


@dataclass
class TurnState:
    recorder: ToolRecorder
    runs: list[AgentRun]


# --------------------------------------------------------------------------- context


def _history(previous: list[Message], window: int) -> list[BaseMessage]:
    recent = previous[-window:] if window > 0 else []
    return [HumanMessage(m.content) if m.role == "user" else AIMessage(m.content) for m in recent]


def _context(previous: list[Message]) -> tuple[list[str], dict | None]:
    """Products shown in the last assistant turns (most recent first) and the last filters."""
    products: list[str] = []
    last_filters = None
    assistant = [m for m in previous if m.role == "assistant" and m.payload]
    for message in reversed(assistant):
        ctx = message.payload.get("context", {})
        if last_filters is None and ctx.get("last_filters"):
            last_filters = ctx["last_filters"]
    for message in reversed(assistant[-CONTEXT_TURNS:]):
        for ref in message.payload.get("context", {}).get("product_refs", []):
            if ref not in products:
                products.append(ref)
    return products, last_filters


def _context_note(products: list[str], last_filters: dict | None) -> str:
    if not products and not last_filters:
        return "No products or searches yet in this conversation."
    lines = []
    if products:
        lines.append("Products shown recently (most recent first): " + ", ".join(products))
    if last_filters:
        lines.append(f"Last search filters: {last_filters}")
    lines.append("Call the tools again for any number you state.")
    return "\n".join(lines)


def language_of(text: str) -> str:
    """'es' or 'en', from a few common words and Spanish-only characters. Defaults to English."""
    lowered = text.lower()
    if re.search(r"[¿¡ñ]", lowered):
        return "es"
    words = re.findall(r"[a-záéíóúüñ]+", lowered)
    spanish = sum(w in SPANISH_WORDS for w in words)
    english = sum(w in ENGLISH_WORDS for w in words)
    return "es" if spanish > english else "en"


# --------------------------------------------------------------------------- tool results


def _walk_part_numbers(value: object, found: list[str]) -> None:
    if isinstance(value, dict):
        pn = value.get("part_number")
        if isinstance(pn, str) and pn not in found:
            found.append(pn)
        for item in value.values():
            _walk_part_numbers(item, found)
    elif isinstance(value, list):
        for item in value:
            _walk_part_numbers(item, found)


def _alternative_notes(recorder: ToolRecorder) -> dict[str, str]:
    notes: dict[str, str] = {}
    for call in recorder.calls:
        for alt in call.result.get("alternatives", []) if call.tool == "search_actuators" else []:
            if "fails" in alt:
                notes[alt["part_number"]] = f"Does not meet: {alt['fails']}"
            elif "if_relaxed" in alt:
                notes[alt["part_number"]] = f"Available if you relax: {alt['if_relaxed']}"
    return notes


def _last_search_filters(recorder: ToolRecorder) -> dict | None:
    searches = [c for c in recorder.calls if c.tool == "search_actuators" and not c.error]
    return searches[-1].args if searches else None


# --------------------------------------------------------------------------- the turn


def _repair_message(problems: list[str]) -> HumanMessage:
    return HumanMessage(
        "[Automatic check, not from the user] Your answer_text contains numbers that no tool "
        f"returned in this turn: {', '.join(problems)}. Call the tools again if you need those "
        "values, and answer again using only numbers returned by the tools."
    )


def _run_with_number_check(
    model: BaseChatModel,
    db: Session,
    system_prompt: str,
    messages: list[BaseMessage],
    user_texts: list[str],
    run_config: dict,
) -> tuple[FinalAnswer, TurnState, dict]:
    settings = get_settings()
    state = TurnState(recorder=ToolRecorder(), runs=[])
    tools = build_tools(db, state.recorder)

    run = run_agent(model, tools, system_prompt, messages, settings.max_tool_iterations, run_config)
    state.runs.append(run)
    allowed = allowed_numbers([c.result for c in state.recorder.calls], user_texts)
    problems = unsupported_numbers(run.answer.answer_text, allowed)
    check = {"status": "pass", "unsupported": []}
    if not problems:
        return run.answer, state, check

    # One repair attempt (design B4), then a safe fallback sentence.
    repair = run_agent(
        model,
        tools,
        system_prompt,
        [*run.messages, _repair_message(problems)],
        settings.max_tool_iterations,
        run_config,
    )
    state.runs.append(repair)
    allowed = allowed_numbers([c.result for c in state.recorder.calls], user_texts)
    still = unsupported_numbers(repair.answer.answer_text, allowed)
    if not still:
        return repair.answer, state, {"status": "repaired", "unsupported": problems}
    fallback = FALLBACK_TEXT[language_of(user_texts[0])]
    answer = repair.answer.model_copy(update={"answer_text": fallback})
    return answer, state, {"status": "fallback", "unsupported": problems + still}


def _cards(
    db: Session, refs: list[str], limit: int, highlight: list[str], notes: dict[str, str]
) -> list[dict]:
    if not refs:
        return []
    stmt = (
        select(Part)
        .where(Part.part_number.in_(refs))
        .options(selectinload(Part.ratings), selectinload(Part.table))
    )
    parts = {p.part_number: p for p in db.scalars(stmt)}
    ordered = [parts[r] for r in refs if r in parts][:limit]
    return [product_card(p, highlight, notes.get(p.part_number)) for p in ordered]


def _dedupe(values: list[str]) -> list[str]:
    seen: list[str] = []
    for value in values:
        if value not in seen:
            seen.append(value)
    return seen


def _owned_session(db: Session, session_id: uuid.UUID, user_id: uuid.UUID | None) -> ChatSession:
    """The conversation if it belongs to `user_id`; someone else's is "not found" (US-21 AC5)."""
    chat = db.get(ChatSession, session_id)
    if chat is None or chat.user_id != user_id:
        raise NotFoundError("Conversation")
    return chat


def handle_turn(
    db: Session,
    model: BaseChatModel,
    query: str,
    session_id: uuid.UUID | None,
    trace_tags: list[str] | None = None,
    user_id: uuid.UUID | None = None,
) -> dict:
    """One user turn. `user_id` owns new conversations and must own continued ones (US-21)."""
    settings = get_settings()
    started = time.perf_counter()

    if session_id is None:
        chat = ChatSession(title=query[:TITLE_LENGTH], user_id=user_id)
        db.add(chat)
        db.flush()
        previous: list[Message] = []
    else:
        chat = _owned_session(db, session_id, user_id)
        previous = list(chat.messages)

    products_in_context, last_filters = _context(previous)
    note = _context_note(products_in_context, last_filters)
    system_prompt = f"{base_system_prompt()}\n\n# Conversation context\n\n{note}\n"
    messages = [*_history(previous, settings.history_window), HumanMessage(query)]
    user_texts = [query] + [m.content for m in previous if m.role == "user"]

    try:
        run_config = tracing_config(str(chat.id), trace_tags or ["api"])
        answer, state, check = _run_with_number_check(
            model, db, system_prompt, messages, user_texts, run_config
        )
    except Exception:
        db.rollback()  # a failed turn leaves nothing behind (no empty new conversation)
        raise
    recorder = state.recorder

    # References: only part numbers a tool returned this turn, or shown earlier (design B3).
    allowed_refs: list[str] = []
    for call in recorder.calls:
        _walk_part_numbers(call.result, allowed_refs)
    allowed_refs += [p for p in products_in_context if p not in allowed_refs]
    requested = _dedupe(answer.product_refs) + _dedupe(answer.alternative_refs)
    rejected = [r for r in requested if r not in allowed_refs]
    product_refs = [r for r in _dedupe(answer.product_refs) if r in allowed_refs]
    alternative_refs = [
        r for r in _dedupe(answer.alternative_refs) if r in allowed_refs and r not in product_refs
    ]
    # Slots follow the status (design B10a): nothing is shown as a match when no model matches,
    # and a clarifying question shows no cards (its choices are the quick replies).
    slot_fix = None
    if answer.status == "no_match" and product_refs:
        slot_fix = "products moved to alternatives (no_match)"
        alternative_refs, product_refs = _dedupe(alternative_refs + product_refs), []
    elif answer.status == "clarification_needed" and (product_refs or alternative_refs):
        slot_fix = "cards removed (clarification_needed)"
        product_refs, alternative_refs = [], []

    turn_filters = _last_search_filters(recorder)
    highlight = highlights_for(turn_filters)
    notes = _alternative_notes(recorder)
    products = _cards(db, product_refs, MAX_PRODUCTS, highlight, notes)
    alternatives = _cards(db, alternative_refs, MAX_ALTERNATIVES, highlight, notes)
    view = answer.view
    if not products:
        view = "cards" if alternatives else "none"
    elif (view == "comparison" and len(products) < 2) or view == "none":
        view = "cards"
    quick_replies = [q.model_dump() for q in answer.quick_replies[:MAX_QUICK_REPLIES]]

    latency_ms = int((time.perf_counter() - started) * 1000)
    input_tokens = sum(r.input_tokens for r in state.runs)
    output_tokens = sum(r.output_tokens for r in state.runs)
    cost = (
        input_tokens * settings.llm_price_input_per_m
        + output_tokens * settings.llm_price_output_per_m
    ) / 1_000_000

    now = datetime.now(UTC)
    user_message = Message(session_id=chat.id, role="user", content=query, created_at=now)
    assistant = Message(
        session_id=chat.id,
        role="assistant",
        content=answer.answer_text,
        created_at=datetime.now(UTC),
        payload={
            "status": answer.status,
            "view": view,
            "products": products,
            "alternatives": alternatives,
            "quick_replies": quick_replies,
            "context": {
                "product_refs": [c["part_number"] for c in products + alternatives],
                "last_filters": turn_filters or last_filters,
            },
        },
        debug={
            "model": settings.llm_model,
            "latency_ms": latency_ms,
            "model_calls": sum(r.model_calls for r in state.runs),
            "tokens": {"input": input_tokens, "output": output_tokens},
            "estimated_cost_usd": round(cost, 6),
            "steps": [
                {
                    "tool": c.tool,
                    "args": c.args,
                    "result": c.result,
                    "duration_ms": c.duration_ms,
                    "error": c.error,
                }
                for c in recorder.calls
            ],
            "number_check": check,
            "rejected_refs": rejected,
            "slot_fix": slot_fix,
            "status_inferred": answer._status_inferred,  # B3b
            "context_note": note,
        },
    )
    db.add_all([user_message, assistant])
    chat.updated_at = datetime.now(UTC)
    db.commit()

    log.info(
        "turn",
        extra={
            "session_id": str(chat.id),
            "message_id": str(assistant.id),
            "model": settings.llm_model,
            "latency_ms": latency_ms,
            "tokens_in": input_tokens,
            "tokens_out": output_tokens,
            "estimated_cost_usd": round(cost, 6),
            "tools": [c.tool for c in recorder.calls],
            "number_check": check["status"],
            "format_retries": sum(r.format_retries for r in state.runs),
            "status": answer.status,
        },
    )
    return assistant_response(chat.id, assistant)


# --------------------------------------------------------------------------- reading


def assistant_response(session_id: uuid.UUID, message: Message) -> dict:
    payload = message.payload or {}
    return {
        "session_id": session_id,
        "message_id": message.id,
        "answer": message.content,
        "status": payload.get("status", "answered"),
        "view": payload.get("view", "none"),
        "products": payload.get("products", []),
        "alternatives": payload.get("alternatives", []),
        "quick_replies": payload.get("quick_replies", []),
        "created_at": message.created_at,
    }


def list_sessions(db: Session, user_id: uuid.UUID | None) -> list[dict]:
    counts = (
        select(Message.session_id, func.count().label("n")).group_by(Message.session_id).subquery()
    )
    stmt = (
        select(ChatSession, func.coalesce(counts.c.n, 0))
        .outerjoin(counts, counts.c.session_id == ChatSession.id)
        .where(ChatSession.user_id == user_id)
        .order_by(ChatSession.updated_at.desc())
    )
    return [
        {
            "id": s.id,
            "title": s.title,
            "created_at": s.created_at,
            "updated_at": s.updated_at,
            "message_count": n,
        }
        for s, n in db.execute(stmt)
    ]


def session_messages(db: Session, session_id: uuid.UUID, user_id: uuid.UUID | None) -> dict:
    chat = _owned_session(db, session_id, user_id)
    items = []
    for m in chat.messages:
        if m.role == "user":
            items.append(
                {"id": m.id, "role": "user", "content": m.content, "created_at": m.created_at}
            )
        else:
            response = assistant_response(chat.id, m)
            items.append(
                {
                    "id": m.id,
                    "role": "assistant",
                    "content": m.content,
                    "created_at": m.created_at,
                    **{
                        k: response[k]
                        for k in ("status", "view", "products", "alternatives", "quick_replies")
                    },
                }
            )
    return {"session_id": chat.id, "title": chat.title, "messages": items}


def message_debug(db: Session, message_id: uuid.UUID, user_id: uuid.UUID | None) -> dict:
    message = db.get(Message, message_id)
    if message is None or message.role != "assistant" or message.session.user_id != user_id:
        raise NotFoundError("Message")
    return {"message_id": message.id, "session_id": message.session_id, **(message.debug or {})}
