"""OpenAI-compatible HTTP and in-process target adapters."""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol

import httpx
from opentelemetry import propagate, trace

from kaos_evals.contract import EvalCase


class TargetErrorKind(StrEnum):
    TIMEOUT = "timeout"
    HTTP = "http"
    CONNECTION = "connection"


class TargetError(RuntimeError):
    def __init__(
        self,
        kind: TargetErrorKind,
        message: str,
        *,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.status_code = status_code


@dataclass
class TargetResponse:
    output: Any
    duration_seconds: float
    usage: dict[str, float | int] = field(default_factory=dict)
    trace_id: str | None = None


class TargetAdapter(Protocol):
    async def __call__(self, case: EvalCase) -> TargetResponse: ...


class HttpTarget:
    def __init__(
        self,
        url: str,
        *,
        model: str = "agent",
        timeout_seconds: float = 60,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.url = _chat_url(url)
        self.model = model
        self.timeout_seconds = timeout_seconds
        self._client = client or httpx.AsyncClient()
        self._owns_client = client is None

    async def __call__(self, case: EvalCase) -> TargetResponse:
        session_id = str(uuid.uuid4())
        headers = {"X-Session-ID": session_id}
        propagate.inject(headers)
        payload = {
            "model": self.model,
            "messages": _messages(case),
            "stream": False,
            "session_id": session_id,
        }
        started = time.perf_counter()
        try:
            async with asyncio.timeout(self.timeout_seconds):
                response = await self._client.post(self.url, json=payload, headers=headers)
        except TimeoutError as exc:
            raise TargetError(
                TargetErrorKind.TIMEOUT,
                f"target timed out after {self.timeout_seconds}s",
            ) from exc
        except httpx.RequestError as exc:
            raise TargetError(
                TargetErrorKind.CONNECTION, f"target connection failed: {exc}"
            ) from exc
        duration = time.perf_counter() - started
        if response.is_error:
            raise TargetError(
                TargetErrorKind.HTTP,
                f"target returned HTTP {response.status_code}: {response.text}",
                status_code=response.status_code,
            )
        try:
            body = response.json()
            output = body["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise TargetError(
                TargetErrorKind.HTTP,
                "target returned an invalid OpenAI chat response",
                status_code=response.status_code,
            ) from exc
        return TargetResponse(
            output=output,
            duration_seconds=duration,
            usage=_usage(body.get("usage")),
            trace_id=_trace_id(response, body),
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()


class LocalTarget(HttpTarget):
    def __init__(
        self,
        app: Any | None = None,
        *,
        url: str = "http://kaos-local",
        model: str = "agent",
        timeout_seconds: float = 60,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if app is not None and client is not None:
            raise ValueError("provide app or client, not both")
        local_client = client
        if app is not None:
            local_client = httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url=url,
            )
        super().__init__(
            url,
            model=model,
            timeout_seconds=timeout_seconds,
            client=local_client,
        )
        self._owns_client = app is not None or client is None


def _chat_url(url: str) -> str:
    return (
        url.rstrip("/")
        if url.rstrip("/").endswith("/v1/chat/completions")
        else f"{url.rstrip('/')}/v1/chat/completions"
    )


def _messages(case: EvalCase) -> list[dict[str, Any]]:
    if case.messages is not None:
        return case.messages
    return [{"role": "user", "content": case.prompt}]


def _usage(value: Any) -> dict[str, float | int]:
    if not isinstance(value, dict):
        return {}
    return {
        str(key): number
        for key, number in value.items()
        if isinstance(number, (int, float)) and not isinstance(number, bool)
    }


def _trace_id(response: httpx.Response, body: dict[str, Any]) -> str | None:
    direct = response.headers.get("x-trace-id") or body.get("trace_id")
    if isinstance(direct, str) and re_full_trace_id(direct):
        return direct.lower()
    traceparent = response.headers.get("traceparent")
    if traceparent:
        parts = traceparent.split("-")
        if len(parts) == 4 and re_full_trace_id(parts[1]):
            return parts[1].lower()
    context = trace.get_current_span().get_span_context()
    return format(context.trace_id, "032x") if context.is_valid else None


def re_full_trace_id(value: str) -> bool:
    return (
        len(value) == 32
        and value != "0" * 32
        and all(char in "0123456789abcdefABCDEF" for char in value)
    )


__all__ = [
    "HttpTarget",
    "LocalTarget",
    "TargetAdapter",
    "TargetError",
    "TargetErrorKind",
    "TargetResponse",
]
