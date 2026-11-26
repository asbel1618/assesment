"""LLM client tests. Hermetic: httpx.MockTransport, no network."""

import json
from collections.abc import Callable

import httpx
import pytest

from app.llm.base import (
    LLMError,
    LLMResponseError,
    LLMTimeoutError,
    LLMUnavailableError,
    extract_sql,
)
from app.llm.client import LlamaCppClient, create_llm_client_from_env
from app.llm.prompt import build_messages
from app.validator import ALLOWED_TABLES

BASE_URL = "http://llm.test/v1"
SQL = "SELECT 1 FROM orders"


def _completion(content: str | None, finish_reason: str = "stop") -> dict[str, object]:
    return {
        "choices": [
            {
                "message": {"role": "assistant", "content": content},
                "finish_reason": finish_reason,
            }
        ]
    }


def _client(handler: Callable[[httpx.Request], httpx.Response]) -> LlamaCppClient:
    http = httpx.Client(transport=httpx.MockTransport(handler))
    return LlamaCppClient(BASE_URL, http=http)


def _json_handler(
    body: object, status: int = 200
) -> Callable[[httpx.Request], httpx.Response]:
    return lambda request: httpx.Response(status, json=body)


def test_generate_sql_returns_content_and_sends_deterministic_payload() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=_completion(SQL))

    assert _client(handler).generate_sql("how many orders?") == SQL

    request = seen[0]
    assert str(request.url) == f"{BASE_URL}/chat/completions"
    payload = json.loads(request.content)
    assert payload["temperature"] == 0
    assert "chat_template_kwargs" not in payload
    assert payload["messages"][-1] == {"role": "user", "content": "how many orders?"}


def test_api_key_and_model_are_sent_when_configured() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=_completion(SQL))

    http = httpx.Client(transport=httpx.MockTransport(handler))
    LlamaCppClient(BASE_URL, http=http, api_key="sk-test", model="m1").generate_sql("q")

    assert seen[0].headers["authorization"] == "Bearer sk-test"
    assert json.loads(seen[0].content)["model"] == "m1"


def test_no_auth_header_or_model_by_default() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=_completion(SQL))

    _client(handler).generate_sql("q")

    assert "authorization" not in seen[0].headers
    assert "model" not in json.loads(seen[0].content)


def test_disable_thinking_sends_chat_template_kwargs() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=_completion(SQL))

    http = httpx.Client(transport=httpx.MockTransport(handler))
    LlamaCppClient(BASE_URL, http=http, disable_thinking=True).generate_sql("q")

    assert json.loads(seen[0].content)["chat_template_kwargs"] == {
        "enable_thinking": False
    }


def test_base_url_trailing_slash_is_tolerated() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, json=_completion(SQL))

    http = httpx.Client(transport=httpx.MockTransport(handler))
    LlamaCppClient(BASE_URL + "/", http=http).generate_sql("q")
    assert seen == [f"{BASE_URL}/chat/completions"]


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        (SQL, SQL),
        (f"  {SQL}\n", SQL),
        (f"```sql\n{SQL}\n```", SQL),
        (f"```\n{SQL}\n```", SQL),
        (f"<think>user wants a count</think>\n{SQL}", SQL),
        (f"<think>multi\nline</think>\n```sql\n{SQL}\n```", SQL),
    ],
)
def test_extract_sql_strips_fences_and_reasoning(content: str, expected: str) -> None:
    assert extract_sql(content) == expected


@pytest.mark.parametrize(
    "content", ["", "   \n", "```sql\n```", "<think>only thoughts</think>"]
)
def test_extract_sql_rejects_empty_output(content: str) -> None:
    with pytest.raises(LLMResponseError):
        extract_sql(content)


def test_timeout_maps_to_llm_timeout_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(LLMTimeoutError):
        _client(handler).generate_sql("q")


def test_connection_failure_maps_to_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(LLMUnavailableError):
        _client(handler).generate_sql("q")


def test_http_error_status_maps_to_unavailable() -> None:
    with pytest.raises(LLMUnavailableError):
        _client(_json_handler({"error": "boom"}, status=500)).generate_sql("q")


@pytest.mark.parametrize(
    "body",
    [
        _completion(""),
        _completion(None),
        _completion(SQL, finish_reason="length"),
        {"choices": []},
        {"unexpected": True},
    ],
)
def test_bad_completion_maps_to_response_error(body: object) -> None:
    with pytest.raises(LLMResponseError):
        _client(_json_handler(body)).generate_sql("q")


def test_non_json_body_maps_to_response_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>not json</html>")

    with pytest.raises(LLMResponseError):
        _client(handler).generate_sql("q")


def test_all_failures_share_the_llm_error_base() -> None:
    for error in (LLMUnavailableError, LLMTimeoutError, LLMResponseError):
        assert issubclass(error, LLMError)


def test_error_exposes_reason() -> None:
    assert LLMTimeoutError("took too long").reason == "took too long"


def test_prompt_mentions_every_allowed_table_and_no_catalog_objects() -> None:
    messages = build_messages("q")
    system = messages[0]["content"].lower()
    for table in ALLOWED_TABLES:
        assert table in system
    for forbidden in ("pg_catalog", "information_schema", "pg_"):
        assert forbidden not in system


def test_prompt_states_sales_definition_and_year() -> None:
    system = build_messages("q")[0]["content"]
    assert "status = 'completed'" in system
    assert "2025" in system


def test_prompt_ends_with_the_user_question() -> None:
    messages = build_messages("top customers?")
    assert messages[0]["role"] == "system"
    assert messages[-1] == {"role": "user", "content": "top customers?"}


def test_prompt_few_shot_examples_pass_the_validator() -> None:
    from app.validator import validate_sql

    messages = build_messages("q")
    examples = [m["content"] for m in messages[1:-1] if m["role"] == "assistant"]
    assert len(examples) >= 3
    for sql in examples:
        validate_sql(sql)


def test_factory_requires_llm_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    with pytest.raises(RuntimeError, match="LLM_BASE_URL"):
        create_llm_client_from_env()


def test_factory_reads_optional_api_key_and_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_BASE_URL", BASE_URL)
    monkeypatch.setenv("LLM_API_KEY", "sk-env")
    monkeypatch.setenv("LLM_MODEL", "m-env")
    monkeypatch.setenv("LLM_DISABLE_THINKING", "true")
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=_completion(SQL))

    real_client = httpx.Client
    monkeypatch.setattr(
        "app.llm.client.httpx.Client",
        lambda **_: real_client(transport=httpx.MockTransport(handler)),
    )
    create_llm_client_from_env().generate_sql("q")

    assert seen[0].headers["authorization"] == "Bearer sk-env"
    payload = json.loads(seen[0].content)
    assert payload["model"] == "m-env"
    assert payload["chat_template_kwargs"] == {"enable_thinking": False}
