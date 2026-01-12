"""
ModelAPI client for OpenAI-compatible servers.

Supports both streaming and non-streaming with proper error handling.
Uses DEBUG_MOCK_RESPONSES env var for deterministic testing.
"""

import json
import logging
import os
from typing import Dict, List, Optional, AsyncIterator
from dataclasses import dataclass
import httpx

logger = logging.getLogger(__name__)


def get_mock_responses() -> Optional[List[str]]:
    """Get mock responses from DEBUG_MOCK_RESPONSES env var.

    Format: JSON array of strings, e.g.:
    ["first response", "second response"]

    Supports multiline responses in the JSON array.
    """
    mock_env = os.environ.get("DEBUG_MOCK_RESPONSES")
    if not mock_env:
        return None
    try:
        responses = json.loads(mock_env)
        if isinstance(responses, list):
            return responses
        # Single string - wrap in list
        return [responses]
    except json.JSONDecodeError:
        # Treat as single plain text response
        return [mock_env]


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
        self.api_base = api_base.rstrip("/")  # Clean trailing slash
        self.api_key = api_key
        self._mock_responses = get_mock_responses()
        self._mock_step = 0

        # Build headers
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        self.client = httpx.AsyncClient(
            base_url=self.api_base,
            headers=headers,
            timeout=60.0,  # Longer timeout for LLM responses
        )

        logger.info(f"ModelAPI initialized: model={self.model}, api_base={self.api_base}")
        if self._mock_responses:
            logger.info(f"ModelAPI using mock responses ({len(self._mock_responses)} configured)")

    async def process_message(
        self,
        messages: List[Dict[str, str]],
        stream: bool = False,
    ) -> str:
        """Process messages and return response content (non-streaming).

        Args:
            messages: OpenAI-format messages
            stream: Ignored - for API compatibility only

        Returns:
            Response content string
        """
        # Check for mock response
        if self._mock_responses and self._mock_step < len(self._mock_responses):
            content = self._mock_responses[self._mock_step]
            self._mock_step += 1
            logger.debug(f"Using mock response {self._mock_step}: {content[:50]}...")
            return content

        # Call real API
        return await self._complete_response(messages)

    async def process_message_stream(
        self,
        messages: List[Dict[str, str]],
    ) -> AsyncIterator[str]:
        """Process messages with streaming response.

        Args:
            messages: OpenAI-format messages

        Yields:
            Response content chunks
        """
        # Check for mock response
        if self._mock_responses and self._mock_step < len(self._mock_responses):
            content = self._mock_responses[self._mock_step]
            self._mock_step += 1
            logger.debug(f"Using mock response {self._mock_step}: {content[:50]}...")
            for word in content.split():
                yield word + " "
            return

        # Call real API
        async for chunk in self._stream_response(messages):
            yield chunk

    async def _complete_response(self, messages: List[Dict[str, str]]) -> str:
        """Non-streaming completion - returns content string."""
        payload = {"model": self.model, "messages": messages, "stream": False}

        try:
            response = await self.client.post("/v1/chat/completions", json=payload)
            response.raise_for_status()
            data = response.json()

            if "choices" not in data or not data["choices"]:
                raise ValueError("Invalid response format: missing choices")

            return data["choices"][0]["message"]["content"]

        except httpx.HTTPError as e:
            logger.error(f"HTTP error in completion: {e}")
            raise
        except json.JSONDecodeError as e:
            logger.error(f"JSON decode error in completion: {e}")
            raise ValueError(f"Invalid JSON response: {e}")

    async def _stream_response(self, messages: List[Dict[str, str]]) -> AsyncIterator[str]:
        """Streaming completion - yields content chunks."""
        payload = {"model": self.model, "messages": messages, "stream": True}

        try:
            async with self.client.stream(
                "POST",
                "/v1/chat/completions",
                json=payload,
                headers={"Accept": "text/event-stream"},
            ) as response:
                response.raise_for_status()

                async for line in response.aiter_lines():
                    content = self._parse_sse_line(line)
                    if content is not None:
                        yield content

        except httpx.HTTPError as e:
            logger.error(f"HTTP error in streaming: {e}")
            raise

    def _parse_sse_line(self, line: str) -> Optional[str]:
        """Parse a single SSE line and extract content."""
        line = line.strip()
        if not line or not line.startswith("data: "):
            return None

        data_str = line[6:]
        if data_str == "[DONE]" or not data_str.strip():
            return None

        try:
            data = json.loads(data_str)
            if "choices" in data and data["choices"]:
                delta = data["choices"][0].get("delta", {})
                if "content" in delta:
                    return delta["content"]
        except json.JSONDecodeError:
            pass
        return None

    async def close(self):
        """Close HTTP client and cleanup resources."""
        try:
            await self.client.aclose()
            logger.debug("ModelAPI client closed successfully")
        except Exception as e:
            logger.warning(f"Error closing ModelAPI client: {e}")


@dataclass
class ModelMessage:
    """Backwards compatibility message model."""

    role: str
    content: str


@dataclass
class ModelResponse:
    """Backwards compatibility response model."""

    content: str
    finish_reason: str


# For backwards compatibility during migration
LiteLLM = ModelAPI
