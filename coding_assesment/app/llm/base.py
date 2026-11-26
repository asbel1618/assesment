"""Provider-agnostic LLM interface, typed errors and output cleanup."""

import re
from typing import Protocol


class LLMError(Exception):
    """Base for LLM failures; ``reason`` is safe to show to API callers."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class LLMUnavailableError(LLMError):
    """The LLM service could not be reached or answered with an error status."""


class LLMTimeoutError(LLMError):
    """The LLM service did not answer in time."""


class LLMResponseError(LLMError):
    """The LLM answered, but with an unusable response (malformed, empty, truncated)."""


class LLMClient(Protocol):
    def generate_sql(self, question: str) -> str:
        """Return the SQL the model proposes for ``question``; raises ``LLMError``."""
        ...


_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_FENCE = re.compile(r"^```[A-Za-z]*\s*\n?(.*?)\n?```$", re.DOTALL)


def extract_sql(content: str) -> str:
    """Strip reasoning blocks and Markdown fences from a model reply."""
    text = _THINK_BLOCK.sub("", content).strip()
    fenced = _FENCE.match(text)
    if fenced:
        text = fenced.group(1).strip()
    if not text:
        raise LLMResponseError("the model returned no SQL")
    return text
