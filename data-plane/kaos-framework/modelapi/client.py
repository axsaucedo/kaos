"""
ModelAPI client for OpenAI-compatible servers.

Supports both streaming and non-streaming with proper error handling.
Uses DEBUG_MOCK_RESPONSES env var for deterministic testing.
Uses contextvars for request-specific mock response state (thread-safe).
"""

import json
import logging
import os
from contextvars import ContextVar
from typing import Any, Dict, List, Optional, AsyncIterator, Union
from dataclasses import dataclass
import httpx

logger = logging.getLogger(__name__)

# Context variable for per-request mock responses
# Each async request context gets its own copy
_mock_responses_ctx: ContextVar[Optional[List[str]]] = ContextVar("mock_responses", default=None)


class ModelAPI:
    """ModelAPI client for OpenAI-compatible servers.

    Supports DEBUG_MOCK_RESPONSES env var for deterministic testing.
    When set, bypasses the actual API and returns mock responses in sequence.
    """

    def __init__(
        self,
        model: str,
        api_base: str,
        api_key: Optional[str] = None,
    ):
        """Initialize ModelAPI client.

        Args:
            model: Model name (e.g., "gpt-4o-mini", "smollm2:135m")
            api_base: API base URL (e.g., "http://localhost:8002")
            api_key: Optional API key for authentication
        """
        self.model = model
        self.api_base = api_base.rstrip("/")
        self.api_key = api_key

        # Load mock responses template from env var if present
        # This is the template - each request gets a fresh copy via contextvars
        self._mock_responses_template: Optional[List[str]] = None
        mock_env = os.environ.get("DEBUG_MOCK_RESPONSES")
        if mock_env:
            try:
                responses = json.loads(mock_env)
                self._mock_responses_template = (
                    responses if isinstance(responses, list) else [responses]
                )
            except json.JSONDecodeError:
                self._mock_responses_template = [mock_env]

        # Build headers
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        self.client = httpx.AsyncClient(
            base_url=self.api_base,
            headers=headers,
            timeout=60.0,
        )

        logger.info(f"ModelAPI initialized: model={self.model}, api_base={self.api_base}")
        if self._mock_responses_template:
            logger.info(
                f"ModelAPI using mock responses ({len(self._mock_responses_template)} configured)"
            )

    def reset_mock_responses(self) -> None:
        """Reset mock responses in context for a fresh cycle.

        Call this at the start of each new request to ensure the mock
        responses cycle through from the beginning. Uses contextvars
        so each async request context gets its own isolated copy.
        """
        if self._mock_responses_template:
            _mock_responses_ctx.set(list(self._mock_responses_template))
            logger.debug(
                f"Reset mock responses in context ({len(self._mock_responses_template)} available)"
            )

    @property
    def has_mock_responses(self) -> bool:
        """Check if mock responses are configured."""
        return self._mock_responses_template is not None

    def _get_next_mock_response(self) -> Optional[str]:
        """Get next mock response from context, or None if unavailable."""
        responses = _mock_responses_ctx.get()
        if responses:
            return responses.pop(0)
        return None

    async def process_message(
        self,
        messages: List[Dict[str, str]],
        stream: bool = False,
        seed: Optional[int] = None,
        tools: Optional[List[dict]] = None,
    ) -> Union[str, "ModelResponse", AsyncIterator[str]]:
        """Process messages and return response.

        Args:
            messages: OpenAI-format messages
            stream: If True, returns AsyncIterator[str]; if False, returns str or ModelResponse
            seed: Optional seed for reproducible generation
            tools: Optional list of tool definitions in OpenAI format for native function calling

        Returns:
            str (mock path) or ModelResponse (real API) if stream=False,
            AsyncIterator[str] if stream=True
        """
        # Check for mock response from context
        mock_content = self._get_next_mock_response()
        if mock_content is not None:
            logger.debug(f"Using mock response: {mock_content[:50]}...")
            if stream:

                async def yield_mock():
                    for word in mock_content.split():
                        yield word + " "

                return yield_mock()
            return mock_content

        # Call real API
        if stream:
            return await self._stream_response(messages, seed=seed, tools=tools)
        return await self._complete_response(messages, seed=seed, tools=tools)

    async def _complete_response(
        self,
        messages: List[Dict[str, str]],
        seed: Optional[int] = None,
        tools: Optional[List[dict]] = None,
    ) -> "ModelResponse":
        """Non-streaming completion - returns ModelResponse."""
        payload: Dict[str, Any] = {"model": self.model, "messages": messages, "stream": False}
        if seed is not None:
            payload["seed"] = seed
        if tools is not None:
            payload["tools"] = tools

        try:
            response = await self.client.post("/v1/chat/completions", json=payload)
            response.raise_for_status()
            data = response.json()

            if "choices" not in data or not data["choices"]:
                raise ValueError("Invalid response format: missing choices")

            message = data["choices"][0]["message"]
            content = message.get("content")

            # Extract tool calls if present
            raw_tool_calls = message.get("tool_calls")
            tool_calls = None
            if raw_tool_calls:
                tool_calls = [
                    ToolCall(
                        id=tc["id"],
                        name=tc["function"]["name"],
                        arguments=tc["function"]["arguments"],
                    )
                    for tc in raw_tool_calls
                ]

            return ModelResponse(
                content=content,
                tool_calls=tool_calls if tool_calls else None,
                raw=data,
            )

        except httpx.HTTPError as e:
            logger.error(f"HTTP error in completion: {e}")
            raise
        except json.JSONDecodeError as e:
            logger.error(f"JSON decode error in completion: {e}")
            raise ValueError(f"Invalid JSON response: {e}")

    async def _stream_response(
        self,
        messages: List[Dict[str, str]],
        seed: Optional[int] = None,
        tools: Optional[List[dict]] = None,
    ) -> Union[AsyncIterator[str], "ModelResponse"]:
        """Streaming completion - returns text iterator or ModelResponse.

        When tools are provided, consumes the entire stream and accumulates
        tool call deltas into a ModelResponse (needed for agentic loop Phase 1).
        When no tools, returns an async iterator yielding text chunks.
        """
        if tools:
            return await self._accumulate_stream(messages, seed=seed, tools=tools)
        return self._stream_text(messages, seed=seed)

    async def _stream_text(
        self,
        messages: List[Dict[str, str]],
        seed: Optional[int] = None,
    ) -> AsyncIterator[str]:
        """Stream text content chunks via SSE."""
        payload: Dict[str, Any] = {"model": self.model, "messages": messages, "stream": True}
        if seed is not None:
            payload["seed"] = seed

        try:
            async with self.client.stream(
                "POST",
                "/v1/chat/completions",
                json=payload,
                headers={"Accept": "text/event-stream"},
            ) as response:
                response.raise_for_status()

                async for line in response.aiter_lines():
                    # Parse SSE line inline
                    line = line.strip()
                    if not line or not line.startswith("data: "):
                        continue
                    data_str = line[6:]
                    if data_str == "[DONE]" or not data_str.strip():
                        continue
                    try:
                        data = json.loads(data_str)
                        if "choices" in data and data["choices"]:
                            delta = data["choices"][0].get("delta", {})
                            if "content" in delta:
                                yield delta["content"]
                    except json.JSONDecodeError:
                        pass

        except httpx.HTTPError as e:
            logger.error(f"HTTP error in streaming: {e}")
            raise

    async def _accumulate_stream(
        self,
        messages: List[Dict[str, str]],
        seed: Optional[int] = None,
        tools: Optional[List[dict]] = None,
    ) -> "ModelResponse":
        """Consume stream fully, accumulating tool call deltas into ModelResponse.

        OpenAI streaming sends tool calls as deltas across multiple chunks:
        - First chunk has index, id, function name
        - Subsequent chunks append to function arguments
        This method accumulates all deltas and builds complete ToolCall objects.
        """
        payload: Dict[str, Any] = {"model": self.model, "messages": messages, "stream": True}
        if seed is not None:
            payload["seed"] = seed
        if tools is not None:
            payload["tools"] = tools

        tool_calls_by_index: Dict[int, dict] = {}
        content_parts: List[str] = []

        try:
            async with self.client.stream(
                "POST",
                "/v1/chat/completions",
                json=payload,
                headers={"Accept": "text/event-stream"},
            ) as response:
                response.raise_for_status()

                async for line in response.aiter_lines():
                    line = line.strip()
                    if not line or not line.startswith("data: "):
                        continue
                    data_str = line[6:]
                    if data_str == "[DONE]" or not data_str.strip():
                        continue
                    try:
                        data = json.loads(data_str)
                        if "choices" not in data or not data["choices"]:
                            continue
                        delta = data["choices"][0].get("delta", {})

                        # Accumulate tool call deltas
                        if "tool_calls" in delta:
                            for tc_delta in delta["tool_calls"]:
                                idx = tc_delta["index"]
                                if idx not in tool_calls_by_index:
                                    tool_calls_by_index[idx] = {
                                        "id": "",
                                        "name": "",
                                        "arguments": "",
                                    }
                                if "id" in tc_delta:
                                    tool_calls_by_index[idx]["id"] = tc_delta["id"]
                                if "function" in tc_delta:
                                    fn = tc_delta["function"]
                                    if "name" in fn:
                                        tool_calls_by_index[idx]["name"] += fn["name"]
                                    if "arguments" in fn:
                                        tool_calls_by_index[idx]["arguments"] += fn["arguments"]

                        # Accumulate content
                        if "content" in delta and delta["content"]:
                            content_parts.append(delta["content"])
                    except json.JSONDecodeError:
                        pass

        except httpx.HTTPError as e:
            logger.error(f"HTTP error in stream accumulation: {e}")
            raise

        # Build ToolCall objects sorted by index
        tool_calls = None
        if tool_calls_by_index:
            tool_calls = [
                ToolCall(
                    id=tool_calls_by_index[i]["id"],
                    name=tool_calls_by_index[i]["name"],
                    arguments=tool_calls_by_index[i]["arguments"],
                )
                for i in sorted(tool_calls_by_index.keys())
            ]

        content = "".join(content_parts) if content_parts else None
        return ModelResponse(content=content, tool_calls=tool_calls)

    async def close(self):
        """Close HTTP client and cleanup resources."""
        try:
            await self.client.aclose()
            logger.debug("ModelAPI client closed successfully")
        except Exception as e:
            logger.warning(f"Error closing ModelAPI client: {e}")


@dataclass
class ToolCall:
    """Structured tool call from the model API.

    Represents a native function call returned by the model,
    with the call ID, function name, and JSON-encoded arguments.
    """

    id: str  # tool call ID from the API (e.g. "call_abc123")
    name: str  # function name (e.g. "get_weather", "delegate_to_coder")
    arguments: str  # JSON string of arguments


@dataclass
class ModelResponse:
    """Structured response from the model API.

    Wraps both text content and tool calls in a single type,
    allowing downstream consumers to handle either path.
    """

    content: Optional[str] = None  # text content (may be None if only tool_calls)
    tool_calls: Optional[List[ToolCall]] = None  # structured tool calls from native API
    role: str = "assistant"  # message role
    raw: Optional[dict] = None  # raw API response for debugging


@dataclass
class ModelMessage:
    """Backwards compatibility message model."""

    role: str
    content: str


# For backwards compatibility during migration
LiteLLM = ModelAPI
