"""Smoke test: the short-term and long-term stores compose for one scope.

Drives both stores together in local mode (no service, no operator) to prove they
share the same Scope abstraction and operate side by side: short-term turns flow into
the short-term window while durable facts land in the long-term store and recall
back, all under one owner.
"""

from kaos_memory.config import (
    LocalStorage,
    ModelConfig,
    StorageConfig,
    ShortTermTierConfig,
)
from kaos_memory.longterm import LongTermStore
from kaos_memory.scope import Scope, ScopeLevel
from kaos_memory.shortterm import ShortTermStore
from tests._fakes import DeterministicEmbedder

OFFLINE = ModelConfig(base_url="http://127.0.0.1:0/v1", model="offline", api_key="t")


def _fake_summarizer(prior, folded):
    return f"{prior} | " + " ".join(c for _, c in folded)


def test_short_term_and_longterm_compose(tmp_path):
    scope = Scope(level=ScopeLevel.USER, principal="alice")

    short_term = ShortTermStore(
        "local",
        str(tmp_path / "shortterm.db"),
        ShortTermTierConfig(token_budget=10_000),
        _fake_summarizer,
    )
    storage = StorageConfig(type="local", local=LocalStorage(path=str(tmp_path / "lt")))
    longterm = LongTermStore(storage, OFFLINE, OFFLINE)
    longterm._memory.embedding_model = DeterministicEmbedder()

    # Short-term: conversational turns flow into the short-term window.
    short_term.append(scope, "user", "what port does the deployment use")
    short_term.append(scope, "assistant", "the deployment uses port 8080")
    assert short_term.recent(scope) == [
        ("user", "what port does the deployment use"),
        ("assistant", "the deployment uses port 8080"),
    ]

    # Long-term: a durable fact is written and recalled back under the same scope.
    longterm.write(scope, "the deployment uses port 8080", infer=False)
    hits = longterm.recall(scope, "what port does the deployment use", top_k=5)
    assert any("8080" in h["memory"] for h in hits)

    # The two tiers are independent stores keyed by the same scope.
    short_term.clear(scope)
    assert short_term.recent(scope) == []
    assert longterm.recall(scope, "what port does the deployment use", top_k=5)
