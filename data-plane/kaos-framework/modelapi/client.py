"""
ModelAPI client for OpenAI-compatible servers.

Supports both streaming and non-streaming with proper error handling.
Uses DEBUG_MOCK_RESPONSES env var for deterministic testing.
"""

import json
import logging
import os
from typing import Dict, List, Optional, AsyncIterator, Union
from dataclasses import dataclass
import httpx

logger = logging.getLogger(__name__)


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

        # Load mock responses from env var if present
        self._mock_responses: Optional[List[str]] = None
        mock_env = os.environ.get("DEBUG_MOCK_RESPONSES")
        if mock_env:
            try:
                responses = json.loads(mock_env)
                self._mock_responses = responses if isinstance(responses, list) else [responses]
            except json.JSONDecodeError:
                self._mock_responses = [mock_env]

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
        if self._mock_responses:
            logger.info(f"ModelAPI using mock responses ({len(self._mock_responses)} configured)")

    async def process_message(
        self,
        messages: List[Dict[str, str]],
        stream: bool = False,
    ) -> Union[str, AsyncIterator[str]]:
        """Process messages and return response.

        Args:
            messages: OpenAI-format messages
            stream: If True, returns AsyncIterator[str]; if False, returns str

        Returns:
            str if stream=False, AsyncIterator[str] if stream=True
        """
        # Check for mock response
        if self._mock_responses:
            mock_content = self._mock_responses.pop(0)
            logger.debug(f"Using mock response: {mock_content[:50]}...")
            if stream:

                async def yield_mock():
                    for word in mock_content.split():
                        yield word + " "

                return yield_mock()
            return mock_content

        # Call real API
        if stream:
            return self._stream_response(messages)
        return await self._complete_response(messages)

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
