"""Unit tests for the model client (endpoint binding for summarization)."""

import httpx
import pytest

from kaos_memory.config import ModelConfig
from kaos_memory.models import ModelClient


def _mock_client(captured):
    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("Authorization")
        import json

        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"role": "assistant", "content": "rolled-up summary"}}]},
        )

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_summarize_honours_base_url_and_model():
    captured = {}
    cfg = ModelConfig(base_url="http://modelapi:8000/v1", model="gpt-4o-mini", api_key="secret")
    client = ModelClient(cfg, client=_mock_client(captured))

    out = client.summarize("prior", [("user", "older turn one"), ("assistant", "older turn two")])

    assert out == "rolled-up summary"
    assert captured["url"] == "http://modelapi:8000/v1/chat/completions"
    assert captured["auth"] == "Bearer secret"
    assert captured["body"]["model"] == "gpt-4o-mini"
    # The folded turns are carried into the user message.
    user_msg = captured["body"]["messages"][-1]["content"]
    assert "older turn one" in user_msg and "older turn two" in user_msg


def test_as_summarizer_returns_callable_usable_by_short_term_store():
    captured = {}
    cfg = ModelConfig(base_url="http://modelapi:8000/v1/", model="m")
    client = ModelClient(cfg, client=_mock_client(captured))
    summarizer = client.as_summarizer()
    result = summarizer("", [("user", "fold me")])
    assert result == "rolled-up summary"
    # Trailing slash on the base URL is normalised.
    assert captured["url"] == "http://modelapi:8000/v1/chat/completions"


def test_summarize_raises_on_http_error():
    def handler(request):
        return httpx.Response(500, json={"error": "boom"})

    cfg = ModelConfig(base_url="http://x/v1", model="m")
    client = ModelClient(cfg, client=httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(httpx.HTTPStatusError):
        client.summarize("", [("user", "x")])
