"""llama.cpp (OpenAI-compatible) implementation of ``LLMClient``."""

import os

import httpx

from app.llm.base import (
    LLMResponseError,
    LLMTimeoutError,
    LLMUnavailableError,
    extract_sql,
)
from app.llm.prompt import build_messages

TIMEOUT_SECONDS = 60.0
MAX_TOKENS = 512
_TRUTHY = {"1", "true", "yes", "on"}


class LlamaCppClient:
    def __init__(
        self,
        base_url: str,
        http: httpx.Client | None = None,
        api_key: str | None = None,
        model: str | None = None,
        disable_thinking: bool = False,
    ) -> None:
        self._url = f"{base_url.rstrip('/')}/chat/completions"
        self._http = http or httpx.Client(timeout=TIMEOUT_SECONDS)
        self._headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._model = model
        self._disable_thinking = disable_thinking

    def generate_sql(self, question: str) -> str:
        payload = {
            "messages": build_messages(question),
            "temperature": 0,
            "max_tokens": MAX_TOKENS,
        }
        if self._disable_thinking:
            # Qwen3.x reasons by default: ~8x slower and can exhaust max_tokens
            # before emitting any content. Needs llama-server --jinja. Opt-in
            # because strict providers (e.g. OpenAI) reject unknown fields.
            payload["chat_template_kwargs"] = {"enable_thinking": False}
        if self._model:
            payload["model"] = self._model
        try:
            response = self._http.post(self._url, json=payload, headers=self._headers)
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise LLMTimeoutError("the LLM service timed out") from exc
        except httpx.HTTPStatusError as exc:
            raise LLMUnavailableError(
                f"the LLM service returned HTTP {exc.response.status_code}"
            ) from exc
        except httpx.HTTPError as exc:
            raise LLMUnavailableError("the LLM service is unreachable") from exc
        return extract_sql(_message_content(response))


def _message_content(response: httpx.Response) -> str:
    try:
        choice = response.json()["choices"][0]
        content = choice["message"]["content"]
        finish_reason = choice.get("finish_reason")
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise LLMResponseError("the LLM response was malformed") from exc
    if finish_reason == "length":
        raise LLMResponseError("the LLM response was truncated")
    if not isinstance(content, str):
        raise LLMResponseError("the model returned no SQL")
    return content


def create_llm_client_from_env() -> LlamaCppClient:
    """Build the client from ``LLM_BASE_URL`` (+ optional ``LLM_API_KEY``, ``LLM_MODEL``, ``LLM_DISABLE_THINKING``)."""
    base_url = os.environ.get("LLM_BASE_URL")
    if not base_url:
        raise RuntimeError("environment variable LLM_BASE_URL is not set")
    return LlamaCppClient(
        base_url,
        api_key=os.environ.get("LLM_API_KEY") or None,
        model=os.environ.get("LLM_MODEL") or None,
        disable_thinking=os.environ.get("LLM_DISABLE_THINKING", "").lower() in _TRUTHY,
    )
