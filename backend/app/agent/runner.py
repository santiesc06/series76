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

from app.agent.schemas import FinalAnswer

PROMPT_PATH = Path(__file__).parent / "prompts" / "system.md"


class AgentError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class AgentRun:
    answer: FinalAnswer
    messages: list[BaseMessage]
    input_tokens: int = 0
    output_tokens: int = 0
    model_calls: int = 0
    tool_names: list[str] = field(default_factory=list)


@lru_cache
def base_system_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def run_agent(
    model: BaseChatModel,
    tools: list[BaseTool],
    system_prompt: str,
    messages: list[BaseMessage],
    max_tool_iterations: int,
) -> AgentRun:
    agent = create_agent(
        model,
        tools,
        system_prompt=system_prompt,
        response_format=ToolStrategy(FinalAnswer),
    )
    # Each tool iteration is two graph steps (model, tools); +3 for the final answer.
    config = {"recursion_limit": 2 * max_tool_iterations + 3}
    try:
        output = agent.invoke({"messages": messages}, config)
    except GraphRecursionError as exc:
        raise AgentError(
            "agent_step_limit", "The assistant could not finish this request in time."
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
        raise AgentError("agent_no_answer", "The assistant did not produce an answer.")

    run = AgentRun(answer=answer, messages=output["messages"])
    for message in run.messages:
        if isinstance(message, AIMessage):
            run.model_calls += 1
            usage = message.usage_metadata or {}
            run.input_tokens += usage.get("input_tokens", 0)
            run.output_tokens += usage.get("output_tokens", 0)
            run.tool_names += [call["name"] for call in message.tool_calls]
    return run
