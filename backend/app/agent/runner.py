"""Runs one agent turn with LangChain's `create_agent` (design B1).

The agent loops "model -> tools -> model" until it returns the structured FinalAnswer (forced by
ToolStrategy), with a cap on tool iterations. LLM provider failures become AgentError with a code
the API turns into a clear error response.
"""

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import openai
from langchain.agents import create_agent
from langchain.agents.structured_output import ToolStrategy
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.tools import BaseTool
from langgraph.errors import GraphRecursionError
from pydantic import ValidationError

from app.agent.schemas import FinalAnswer

PROMPT_PATH = Path(__file__).parent / "prompts" / "system.md"


class AgentError(RuntimeError):
    """`message` is shown to the user; `detail` goes to the server log only."""

    def __init__(self, code: str, message: str, detail: str | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail


# Sent back to the model when its FinalAnswer call is invalid (design B3a). Plainer than the raw
# pydantic error, and it names the mistake seen in practice: fields written as XML inside
# answer_text, so required fields such as `status` go missing.
RETRY_MESSAGE = (
    "Your FinalAnswer call was invalid ({problem}). Call FinalAnswer again with every field as "
    "its own JSON argument; `status` is required. Do not write <parameter> tags or other fields "
    "inside answer_text."
)


class FinalAnswerErrors:
    """Turns each invalid FinalAnswer into a retry message and remembers it for the log."""

    def __init__(self) -> None:
        self.problems: list[str] = []

    def __call__(self, exc: Exception) -> str:
        problem = _describe(exc)
        self.problems.append(problem)
        return RETRY_MESSAGE.format(problem=problem)

    def summary(self) -> str | None:
        if not self.problems:
            return None
        return f"{len(self.problems)} invalid FinalAnswer call(s); last: {self.problems[-1]}"


def _describe(exc: Exception) -> str:
    """Short, content-free description: which fields failed and why (no user text)."""
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, ValidationError):
            return "; ".join(
                f"{'.'.join(str(part) for part in error['loc']) or 'arguments'}: {error['type']}"
                for error in current.errors()
            )
        current = getattr(current, "source", None) or current.__cause__ or current.__context__
    return type(exc).__name__


@dataclass
class AgentRun:
    answer: FinalAnswer
    messages: list[BaseMessage]
    input_tokens: int = 0
    output_tokens: int = 0
    model_calls: int = 0
    tool_names: list[str] = field(default_factory=list)
    format_retries: int = 0  # invalid FinalAnswer calls the model had to redo (B3a)


@lru_cache
def base_system_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def run_agent(
    model: BaseChatModel,
    tools: list[BaseTool],
    system_prompt: str,
    messages: list[BaseMessage],
    max_tool_iterations: int,
    run_config: dict | None = None,
) -> AgentRun:
    format_errors = FinalAnswerErrors()
    agent = create_agent(
        model,
        tools,
        system_prompt=system_prompt,
        response_format=ToolStrategy(FinalAnswer, handle_errors=format_errors),
    )
    # Each tool iteration is two graph steps (model, tools); +3 for the final answer.
    # run_config adds optional tracing callbacks and metadata (design Q6).
    config = {**(run_config or {}), "recursion_limit": 2 * max_tool_iterations + 3}
    try:
        output = agent.invoke({"messages": messages}, config)
    except GraphRecursionError as exc:
        raise AgentError(
            "agent_step_limit",
            "The assistant could not finish this request in time.",
            detail=format_errors.summary() or "tool step limit reached",
        ) from exc
    except openai.APIStatusError as exc:
        if exc.status_code == 402:
            raise AgentError(
                "llm_budget_exhausted", "The language model budget is used up."
            ) from exc
        if exc.status_code in (401, 403):
            raise AgentError("llm_auth", "The language model rejected the API key.") from exc
        if exc.status_code == 429:
            raise AgentError("llm_rate_limited", "The language model is busy; retry.") from exc
        raise AgentError("llm_unavailable", "The language model returned an error.") from exc
    except (openai.APIConnectionError, openai.APITimeoutError) as exc:
        raise AgentError("llm_unavailable", "The language model could not be reached.") from exc

    answer = output.get("structured_response")
    if not isinstance(answer, FinalAnswer):
        raise AgentError(
            "agent_no_answer",
            "The assistant did not produce an answer.",
            detail=format_errors.summary(),
        )

    run = AgentRun(
        answer=answer, messages=output["messages"], format_retries=len(format_errors.problems)
    )
    for message in run.messages:
        if isinstance(message, AIMessage):
            run.model_calls += 1
            usage = message.usage_metadata or {}
            run.input_tokens += usage.get("input_tokens", 0)
            run.output_tokens += usage.get("output_tokens", 0)
            run.tool_names += [call["name"] for call in message.tool_calls]
    return run
