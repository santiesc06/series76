"""A scripted chat model: replays prepared AI messages, so agent tests cost nothing.

It runs through the real LangChain `create_agent` loop and the real tools; only the LLM's
decisions (which tool to call, what to answer) are scripted.
"""

from itertools import count
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field

_ids = count()
USAGE = {"input_tokens": 1000, "output_tokens": 100, "total_tokens": 1100}


def tool_call(name: str, **args) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[{"name": name, "args": args, "id": f"call_{next(_ids)}"}],
        usage_metadata=USAGE,
    )


def final(answer_text: str, status: str = "answered", **fields) -> AIMessage:
    args = {"answer_text": answer_text, "status": status, **fields}
    return tool_call("FinalAnswer", **args)


class ScriptedModel(BaseChatModel):
    script: list[Any]  # AIMessage steps, or an Exception to simulate a provider failure
    calls: int = 0
    seen: list = Field(default_factory=list)  # messages received on each call

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        self.seen.append(list(messages))
        step = self.script[self.calls]
        self.calls += 1
        if isinstance(step, Exception):
            raise step
        return ChatResult(generations=[ChatGeneration(message=step)])
