"""Token counting for the working-tier budget.

Uses ``tiktoken`` with the ``cl100k_base`` encoding as a stable, model-agnostic
approximation of token length. The working tier only needs a consistent measure
to bound its verbatim window, not exact per-model accounting.
"""

from __future__ import annotations

import tiktoken

_ENCODING = tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str) -> int:
    """Return the token count of ``text`` under the cl100k_base encoding."""
    if not text:
        return 0
    return len(_ENCODING.encode(text))
