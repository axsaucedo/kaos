import asyncio
import json

import httpx
import pytest
from opentelemetry import trace
from opentelemetry.trace import NonRecordingSpan, SpanContext, TraceFlags

from kaos_evals.contract import EvalCase
from kaos_evals.targets import HttpTarget, LocalTarget, TargetError, TargetErrorKind


def chat_response(content="Hello", *, headers=None):
    return httpx.Response(
        200,
        headers=headers,
        json={
            "choices": [{"message": {"role": "assistant", "content": content}}],
            "usage": {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3},
        },
    )


@pytest.mark.asyncio
async def test_http_target_success_propagates_trace_and_captures_response_trace():
    captured = {}
    response_trace_id = "b" * 32

    async def handler(request):
        captured.update(request.headers)
        return chat_response(headers={"traceparent": f"00-{response_trace_id}-{'c' * 16}-01"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    target = HttpTarget("http://agent", client=client)
    context = SpanContext(
        trace_id=int("a" * 32, 16),
        span_id=int("d" * 16, 16),
        is_remote=False,
        trace_flags=TraceFlags(TraceFlags.SAMPLED),
    )
    with trace.use_span(NonRecordingSpan(context)):
        result = await target(EvalCase(id="one", prompt="Hi"))

    assert result.output == "Hello"
    assert result.usage["total_tokens"] == 3
    assert result.trace_id == response_trace_id
    assert captured["traceparent"] == f"00-{'a' * 32}-{'d' * 16}-01"
    await client.aclose()


@pytest.mark.asyncio
async def test_http_target_uses_fresh_session_per_invocation():
    sessions = []

    async def handler(request):
        sessions.append(
            (request.headers["x-session-id"], json.loads(request.content)["session_id"])
        )
        return chat_response()

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    target = HttpTarget("http://agent/v1/chat/completions", client=client)
    eval_case = EvalCase(id="one", prompt="Hi")
    await target(eval_case)
    await target(eval_case)

    assert sessions[0][0] == sessions[0][1]
    assert sessions[1][0] == sessions[1][1]
    assert sessions[0][0] != sessions[1][0]
    await client.aclose()


@pytest.mark.asyncio
async def test_timeout_maps_to_typed_error():
    async def handler(request):
        await asyncio.sleep(0.05)
        return chat_response()

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    target = HttpTarget("http://agent", timeout_seconds=0.001, client=client)

    with pytest.raises(TargetError) as error:
        await target(EvalCase(id="one", prompt="Hi"))
    assert error.value.kind == TargetErrorKind.TIMEOUT
    await client.aclose()


@pytest.mark.asyncio
async def test_http_failure_maps_to_typed_error():
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(503, text="unavailable"))
    )
    target = HttpTarget("http://agent", client=client)

    with pytest.raises(TargetError) as error:
        await target(EvalCase(id="one", prompt="Hi"))
    assert error.value.kind == TargetErrorKind.HTTP
    assert error.value.status_code == 503
    await client.aclose()


@pytest.mark.asyncio
async def test_connection_failure_maps_to_typed_error():
    def handler(request):
        raise httpx.ConnectError("refused", request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    target = HttpTarget("http://agent", client=client)

    with pytest.raises(TargetError) as error:
        await target(EvalCase(id="one", prompt="Hi"))
    assert error.value.kind == TargetErrorKind.CONNECTION
    await client.aclose()


@pytest.mark.asyncio
async def test_local_target_uses_in_process_asgi_app():
    async def app(scope, receive, send):
        request = await receive()
        body = json.loads(request["body"])
        assert body["messages"][0]["content"] == "Hi"
        payload = json.dumps({"choices": [{"message": {"content": "Local"}}], "usage": {}}).encode()
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": payload})

    target = LocalTarget(app)
    result = await target(EvalCase(id="one", prompt="Hi"))

    assert result.output == "Local"
    await target.aclose()
