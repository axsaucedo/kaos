"""
ModelAPI client for OpenAI-compatible servers.

Supports both streaming and non-streaming with proper error handling.
Uses DEBUG_MOCK_RESPONSES env var for deterministic testing.
Uses contextvars for request-specific mock response state (thread-safe).
Supports native OpenAI function calling via tools parameter.
"""

import json
import logging
import os
from contextvars import ContextVar
from typing import Dict, List, Optional, AsyncIterator, Union, Any
from dataclasses import dataclass, field
import httpx

logger = logging.getLogger(__name__)

# Context variable for per-request mock responses
# Each async request context gets its own copy
_mock_responses_ctx: ContextVar[Optional[List[str]]] = ContextVar("mock_responses", default=None)


@dataclass
class ToolCall:
    """Represents a tool call from the model response."""

    id: str
    name: str
    arguments: Union[Dict[str, Any], str]

    def __post_init__(self):
        """Normalize arguments: parse JSON strings to dict."""
        if isinstance(self.arguments, str):
            try:
                self.arguments = json.loads(self.arguments)
            except json.JSONDecodeError:
                logger.warning(f"Malformed tool call arguments (invalid JSON): {self.arguments}")
                self.arguments = {}

    @classmethod
    def from_openai(cls, tc: Dict[str, Any]) -> "ToolCall":
        """Create ToolCall from OpenAI API format."""
        func = tc.get("function", {})
        return cls(
            id=tc.get("id", ""),
            name=func.get("name", ""),
            arguments=func.get("arguments", "{}"),
        )


@dataclass
class ModelResponse:
    """Structured response from the model API.

    Contains content text and/or tool calls from native function calling.
    """

    content: Optional[str] = None
    tool_calls: List[ToolCall] = field(default_factory=list)
    finish_reason: str = "stop"

    @property
    def has_tool_calls(self) -> bool:
        return len(self.tool_calls) > 0


class ModelAPI:
    """ModelAPI client for OpenAI-compatible servers.

    Supports DEBUG_MOCK_RESPONSES env var for deterministic testing.
    When set, bypasses the actual API and returns mock responses in sequence.
    Supports native function calling via OpenAI tools parameter.
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

    def _parse_mock_response(self, mock_content: str) -> ModelResponse:
        """Parse a mock response string into a ModelResponse.

        Mock responses can be:
        - Plain text: returned as content
        - JSON with tool_calls: parsed into ToolCall objects
        """
        try:
            parsed = json.loads(mock_content)
            if isinstance(parsed, dict) and "tool_calls" in parsed:
                tool_calls = [
                    ToolCall(
                        id=tc.get("id", f"call_{i}"),
                        name=tc.get("name", ""),
                        arguments=tc.get("arguments", {}),
                    )
                    for i, tc in enumerate(parsed["tool_calls"])
                ]
                return ModelResponse(
                    content=parsed.get("content"),
                    tool_calls=tool_calls,
                    finish_reason="tool_calls",
                )
        except (json.JSONDecodeError, TypeError):
            pass
        return ModelResponse(content=mock_content, finish_reason="stop")

    async def process_message(
        self,
        messages: List[Dict[str, str]],
        stream: bool = False,
        seed: Optional[int] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> Union[ModelResponse, AsyncIterator[str]]:
        """Process messages and return response.

        Args:
            messages: OpenAI-format messages
            stream: If True, returns AsyncIterator[str]; if False, returns ModelResponse
            seed: Optional seed for reproducible generation
            tools: Optional list of tool definitions in OpenAI format

        Returns:
            ModelResponse if stream=False, AsyncIterator[str] if stream=True
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
            return self._parse_mock_response(mock_content)

        # Call real API
        if stream:
            return self._stream_response(messages, seed=seed)
        return await self._complete_response(messages, seed=seed, tools=tools)

    async def _complete_response(
        self,
        messages: List[Dict[str, str]],
        seed: Optional[int] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> ModelResponse:
        """Non-streaming completion - returns ModelResponse."""
        payload: Dict[str, Any] = {"model": self.model, "messages": messages, "stream": False}
        if seed is not None:
            payload["seed"] = seed
        if tools:
            payload["tools"] = tools

        try:
            response = await self.client.post("/v1/chat/completions", json=payload)
            response.raise_for_status()
            data = response.json()

            if "choices" not in data or not data["choices"]:
                raise ValueError("Invalid response format: missing choices")

            message = data["choices"][0]["message"]
            finish_reason = data["choices"][0].get("finish_reason", "stop")

            # Extract tool calls if present
            tool_calls = []
            if message.get("tool_calls"):
                tool_calls = [ToolCall.from_openai(tc) for tc in message["tool_calls"]]
                finish_reason = "tool_calls"

            return ModelResponse(
                content=message.get("content"),
                tool_calls=tool_calls,
                finish_reason=finish_reason,
            )

        except httpx.HTTPError as e:
            logger.error(f"HTTP error in completion: {e}")
            raise
        except json.JSONDecodeError as e:
            logger.error(f"JSON decode error in completion: {e}")
            raise ValueError(f"Invalid JSON response: {e}")

    async def _stream_response(
        self, messages: List[Dict[str, str]], seed: Optional[int] = None
    ) -> AsyncIterator[str]:
        """Streaming completion - yields content chunks."""
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

    async def close(self):
        """Close HTTP client and cleanup resources."""
        try:
            await self.client.aclose()
            logger.debug("ModelAPI client closed successfully")
        except Exception as e:
            logger.warning(f"Error closing ModelAPI client: {e}")


# For backwards compatibility during migration
LiteLLM = ModelAPI
