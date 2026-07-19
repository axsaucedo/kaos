"""Server-side rolling summary and forget endpoint tests."""

from fastapi.testclient import TestClient

from kaos_memory.config import ShortTermTierConfig
from kaos_memory.stores import Scope, ScopeLevel
from kaos_memory.app import MemoryService, create_app
from kaos_memory.stores import ShortTermStore

USER_SCOPE = {"level": "user", "principal": "carol", "session_id": "session-1"}


class _RecordingLongTerm:
    def __init__(self):
        self.recalls = []
        self.deleted = []
        self.facts = []

    def recall(self, scope, query, top_k=10):
        return self.facts

    def add(self, scope, messages, infer=True):
        return []

    def delete_scope(self, scope):
        self.deleted.append(scope)

    def ping(self):
        return None


def _client(longterm, short_term):
    return TestClient(
        create_app(
            MemoryService(longterm=longterm, short_term=short_term, scheduler=lambda t: None)
        )
    )


def test_overflow_summarizes_server_side(tmp_path):
    calls = []

    def summarizer(prior, folded):
        calls.append((prior, list(folded)))
        return (prior + " " + " ".join(c for _, c in folded)).strip()

    # Tiny budget forces folding into the rolling summary on the server.
    short_term = ShortTermStore(
        "local",
        str(tmp_path / "w.db"),
        ShortTermTierConfig(token_budget=4, rolling_summary=True),
        summarizer,
    )
    scope = Scope(level=ScopeLevel.USER, principal="carol", session_id="session-1")
    for i in range(5):
        short_term.add(scope, [("user", f"message number {i} with several tokens here")])

    assert calls, "summarizer should have been invoked server-side on overflow"
    assert short_term.summary(scope) != ""


def test_forget_clears_both_tiers(tmp_path):
    short_term = ShortTermStore(
        "local", str(tmp_path / "w.db"), ShortTermTierConfig(), lambda p, f: p
    )
    longterm = _RecordingLongTerm()
    scope = Scope(level=ScopeLevel.USER, principal="carol", session_id="session-1")
    short_term.add(scope, [("user", "something to remember")])
    assert short_term.active_window(scope)

    resp = _client(longterm, short_term).post("/v1/forget", json={"scope": USER_SCOPE})
    assert resp.status_code == 200
    assert resp.json()["forgotten"] is True
    assert short_term.active_window(scope) == []
    assert short_term.summary(scope) == ""
    assert len(longterm.deleted) == 1


def test_forget_soft_degrades_on_longterm_failure(tmp_path):
    class _BrokenDelete(_RecordingLongTerm):
        def delete_scope(self, scope):
            raise RuntimeError("delete failed")

    short_term = ShortTermStore(
        "local", str(tmp_path / "w.db"), ShortTermTierConfig(), lambda p, f: p
    )
    scope = Scope(level=ScopeLevel.USER, principal="carol", session_id="session-1")
    short_term.add(scope, [("user", "x")])

    resp = _client(_BrokenDelete(), short_term).post(
        "/v1/forget", json={"scope": USER_SCOPE, "failure_mode": "soft"}
    )
    assert resp.status_code == 200
    assert resp.json()["degraded"] is True
    # Short-term tier was still cleared despite the long-term failure.
    assert short_term.active_window(scope) == []


def test_user_forget_clears_all_attributed_tiers_and_preserves_other_users(tmp_path):
    class _AttributedLongTerm(_RecordingLongTerm):
        def __init__(self):
            super().__init__()
            self.facts = [
                {"principal": "alice", "agent": "agent-a", "memory": "alice one"},
                {"principal": "alice", "agent": "agent-b", "memory": "alice two"},
                {"principal": "bob", "agent": "agent-a", "memory": "bob control"},
            ]

        def delete_scope(self, scope):
            super().delete_scope(scope)
            self.facts = [fact for fact in self.facts if fact["principal"] != scope.principal]

    short_term = ShortTermStore(
        "local",
        str(tmp_path / "w.db"),
        ShortTermTierConfig(token_budget=4, rolling_summary=True),
        lambda prior, turns: (prior + " " + " ".join(c for _, c in turns)).strip(),
        group="team-a",
    )
    alice_first = Scope(
        level=ScopeLevel.AGENT,
        principal="alice",
        agent_client_id="agent-a",
        session_id="alice-1",
    )
    alice_second = alice_first.model_copy(
        update={"agent_client_id": "agent-b", "session_id": "alice-2"}
    )
    bob = alice_first.model_copy(update={"principal": "bob", "session_id": "bob-1"})
    for scope, marker in (
        (alice_first, "alice first"),
        (alice_second, "alice second"),
        (bob, "bob control"),
    ):
        short_term.add(
            scope,
            [("user", f"remember {marker} across the rolling summary"), ("assistant", marker)],
        )
        assert short_term.summary(scope)
        assert short_term.active_window(scope)

    longterm = _AttributedLongTerm()
    response = _client(longterm, short_term).post(
        "/v1/forget", json={"scope": {"level": "user", "principal": "alice"}}
    )

    assert response.status_code == 200
    for scope in (alice_first, alice_second):
        assert short_term.summary(scope) == ""
        assert short_term.active_window(scope) == []
    assert short_term.summary(bob)
    assert short_term.active_window(bob) == [("assistant", "bob control")]
    assert longterm.facts == [{"principal": "bob", "agent": "agent-a", "memory": "bob control"}]
