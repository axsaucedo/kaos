"""Model client binding the stores to a resolved OpenAI-compatible endpoint.

The short-term tier needs an LLM to produce its rolling summary; Mem0 needs the same
kind of endpoint for extraction and embeddings. Both are described by a single
``ModelConfig`` (an OpenAI-compatible base URL, a model name, and a key) so one
binding drives the whole stack. This client wraps the chat-completions call used
for summarization; Mem0 owns its own embedding/extraction calls via the same
``ModelConfig`` values.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

import httpx

from kaos_memory.config import ModelConfig
from kaos_memory.shortterm import Summarizer

_SUMMARY_SYSTEM = (
    "You maintain a concise rolling summary of a conversation. Fold the prior summary "
    "and the provided older turns into an updated summary that preserves durable facts, "
    "decisions, and entities. Return only the summary text."
)


class ModelClient:
    """Calls an OpenAI-compatible chat endpoint for short-term tier summarization."""

    def __init__(self, config: ModelConfig, client: Optional[httpx.Client] = None) -> None:
        self.config = config
        self._client = client or httpx.Client(timeout=30.0)

    def summarize(self, prior_summary: str, folded_turns: List[Tuple[str, str]]) -> str:
        """Fold ``prior_summary`` and ``folded_turns`` into an updated rolling summary."""
        turns_text = "\n".join(f"{role}: {content}" for role, content in folded_turns)
        user = (
            f"Prior summary:\n{prior_summary or '(none)'}\n\nOlder turns to fold in:\n{turns_text}"
        )
        resp = self._client.post(
            f"{self.config.base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {self.config.api_key}"},
            json={
                "model": self.config.model,
                "messages": [
                    {"role": "system", "content": _SUMMARY_SYSTEM},
                    {"role": "user", "content": user},
                ],
            },
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

    def as_summarizer(self) -> Summarizer:
        """Return a ``Summarizer`` callable for use by the short-term store."""
        return self.summarize

    def close(self) -> None:
        self._client.close()
