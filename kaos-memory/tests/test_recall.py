"""Synchronous recall endpoint tests."""

from fastapi.testclient import TestClient

from kaos_memory.config import ShortTermTierConfig
from kaos_memory.app import MemoryService, create_app
from kaos_memory.stores import ShortTermStore


class _FakeLongTerm:
    def __init__(self, facts=None, fail=False):
        self._facts = facts or []
        self._fail = fail

    def recall(self, scope, query, top_k=10):
        if self._fail:
            raise RuntimeError("vector store unreachable")
        return self._facts

    def add(self, scope, messages, infer=True):
        return []

    def ping(self):
        return None


def _short_term(tmp_path):
    return ShortTermStore("local", str(tmp_path / "w.db"), ShortTermTierConfig(), lambda p, f: p)


def _client(longterm, short_term):
    return TestClient(create_app(MemoryService(longterm=longterm, short_term=short_term)))


USER_SCOPE = {"level": "user", "principal": "alice", "session_id": "s1"}


def test_recall_surfaces_medium_term_digest(tmp_path):
    from kaos_memory.stores import Scope, ScopeLevel

    # A tiny budget with the rolling digest on folds evicted turns into the medium-term
    # summary, which recall must surface distinctly from the verbatim short-term window.
    short_term = ShortTermStore(
        "local",
        str(tmp_path / "w.db"),
        ShortTermTierConfig(token_budget=4, rolling_summary=True),
        lambda prior, turns: (prior + " " + " ".join(c for _, c in turns)).strip(),
    )
    s = Scope(level=ScopeLevel.USER, principal="alice", session_id="s1")
    for i in range(6):
        short_term.add(s, [("user", f"message number {i}")])

    resp = _client(_FakeLongTerm(), short_term).post(
        "/v1/recall", json={"scope": USER_SCOPE, "query": "anything"}
    )
    body = resp.json()
    assert body["medium_term"]["summary"] != ""
    # The digest is surfaced for message-history replay, not duplicated into the block.
    assert "## Conversation summary" not in body["long_term"]["block"]
    # The digest is separate from the verbatim window.
    assert "summary" not in body["short_term"]


def test_recall_returns_facts_and_short_term_context(tmp_path):
    short_term = _short_term(tmp_path)
    longterm = _FakeLongTerm(facts=[{"memory": "alice prefers dark mode", "score": 0.9}])
    # Seed short-term turns under the same owner key.
    from kaos_memory.stores import Scope, ScopeLevel

    s = Scope(level=ScopeLevel.USER, principal="alice", session_id="s1")
    short_term.add(s, [("user", "hello there")])
    short_term.add(s, [("assistant", "hi alice")])

    resp = _client(longterm, short_term).post(
        "/v1/recall", json={"scope": USER_SCOPE, "query": "preferences"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["degraded"] is False
    # Native Mem0 fields pass through unmodified.
    assert body["long_term"]["facts"][0]["score"] == 0.9
    assert body["short_term"]["window"] == [["user", "hello there"], ["assistant", "hi alice"]]
    assert "alice prefers dark mode" in body["long_term"]["block"]
    # The verbatim window is replayed as message history, not rendered into the block.
    assert "## Recent turns" not in body["long_term"]["block"]


def test_recall_degrades_to_short_term_only_on_longterm_failure(tmp_path):
    short_term = _short_term(tmp_path)
    from kaos_memory.stores import Scope, ScopeLevel

    short_term.add(
        Scope(level=ScopeLevel.USER, principal="alice", session_id="s1"),
        [("user", "remember the budget is 5000")],
    )
    longterm = _FakeLongTerm(fail=True)

    resp = _client(longterm, short_term).post(
        "/v1/recall", json={"scope": USER_SCOPE, "query": "budget"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["degraded"] is True
    assert body["long_term"]["facts"] == []
    # Long-term degraded: the block carries no facts, but the verbatim window survives
    # for message-history replay.
    assert body["long_term"]["block"] == ""
    assert ["user", "remember the budget is 5000"] in body["short_term"]["window"]


def test_recall_can_exclude_short_term(tmp_path):
    short_term = _short_term(tmp_path)
    longterm = _FakeLongTerm(facts=[{"memory": "fact one"}])
    resp = _client(longterm, short_term).post(
        "/v1/recall",
        json={"scope": USER_SCOPE, "query": "x", "include": ["long_term"]},
    )
    body = resp.json()
    assert "short_term" not in body
    assert "medium_term" not in body
    assert "fact one" in body["long_term"]["block"]
    assert "## Recent turns" not in body["long_term"]["block"]


def test_recall_rejects_unknown_include_tier(tmp_path):
    response = _client(_FakeLongTerm(), _short_term(tmp_path)).post(
        "/v1/recall",
        json={"scope": USER_SCOPE, "query": "x", "include": ["archive"]},
    )

    assert response.status_code == 422


def test_recall_omits_unrequested_tiers(tmp_path):
    response = _client(_FakeLongTerm(), _short_term(tmp_path)).post(
        "/v1/recall",
        json={"scope": USER_SCOPE, "query": "x", "include": ["medium_term"]},
    )

    assert response.status_code == 200
    assert response.json() == {"medium_term": {"summary": ""}, "degraded": False}


def test_session_conversation_read_is_bound_to_principal(tmp_path):
    short_term = _short_term(tmp_path)
    from kaos_memory.stores import Scope, ScopeLevel

    short_term.add(
        Scope(level=ScopeLevel.SESSION, principal="alice", session_id="s1"),
        [("user", "alice secret")],
    )
    client = _client(_FakeLongTerm(), short_term)

    matched = client.post(
        "/v1/recall",
        json={
            "scope": {"level": "session", "principal": "alice", "session_id": "s1"},
            "query": "x",
        },
    ).json()
    mismatched = client.post(
        "/v1/recall",
        json={"scope": {"level": "session", "principal": "bob", "session_id": "s1"}, "query": "x"},
    ).json()

    assert matched["short_term"]["window"] == [["user", "alice secret"]]
    assert mismatched["short_term"]["window"] == []
    assert mismatched["medium_term"]["summary"] == ""


def test_store_scope_is_admin_only_when_actor_header_is_present(tmp_path):
    client = _client(_FakeLongTerm(), _short_term(tmp_path))
    payload = {"scope": {"level": "store"}, "query": "x"}

    assert client.post("/v1/recall", json=payload).status_code == 200
    assert (
        client.post("/v1/recall", json=payload, headers={"x-actor": "agent-a"}).status_code == 403
    )
    assert (
        client.post(
            "/v1/list", json={"scope": {"level": "store"}}, headers={"x-actor": "agent-a"}
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/v1/forget", json={"scope": {"level": "store"}}, headers={"x-actor": "agent-a"}
        ).status_code
        == 403
    )


def test_user_recall_without_session_returns_long_term_and_empty_conversation(tmp_path):
    longterm = _FakeLongTerm(facts=[{"memory": "alice prefers dark mode"}])

    response = _client(longterm, _short_term(tmp_path)).post(
        "/v1/recall",
        json={"scope": {"level": "user", "principal": "alice"}, "query": "preferences"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["long_term"]["facts"] == [{"memory": "alice prefers dark mode"}]
    assert body["short_term"]["window"] == []
    assert body["medium_term"]["summary"] == ""
    assert body["degraded"] is False


def test_recall_rejects_incomplete_scope_before_fail_soft_recall(tmp_path):
    response = _client(_FakeLongTerm(), _short_term(tmp_path)).post(
        "/v1/recall",
        json={
            "scope": {
                "level": "agent",
                "principal": "alice",
            },
            "query": "anything",
        },
    )

    assert response.status_code == 400
    assert response.json() == {"error": "incomplete agent scope"}


def test_conversation_round_trips_across_recall_scopes_without_session_leakage(tmp_path):
    short_term = ShortTermStore(
        "local",
        str(tmp_path / "w.db"),
        ShortTermTierConfig(token_budget=4, rolling_summary=True),
        lambda prior, turns: (prior + " " + " ".join(c for _, c in turns)).strip(),
        group="team-a",
    )
    client = _client(_FakeLongTerm(), short_term)
    base_scope = {
        "level": "agent",
        "principal": "alice",
        "agent_client_id": "agent-a",
    }
    for session_id, marker in (("session-1", "amber notebook"), ("session-2", "silver compass")):
        response = client.post(
            "/v1/write",
            json={
                "attribution": {**base_scope, "session_id": session_id},
                "turns": [
                    {"role": "user", "content": f"remember the {marker} in this session"},
                    {"role": "assistant", "content": f"noted {marker}"},
                ],
            },
        )
        assert response.status_code == 202

    recalled = []
    for session_id in ("session-1", "session-2"):
        response = client.post(
            "/v1/recall",
            json={
                "scope": {**base_scope, "level": "session", "session_id": session_id},
                "query": "notebook compass",
            },
        )
        assert response.status_code == 200
        recalled.append(response.json())

    for level_scope in (
        {**base_scope, "session_id": "session-1"},
        {"level": "store", "session_id": "session-1"},
    ):
        response = client.post(
            "/v1/recall",
            json={"scope": level_scope, "query": "notebook compass"},
        )
        assert response.status_code == 200
        body = response.json()
        assert "amber notebook" in body["medium_term"]["summary"]
        assert body["short_term"]["window"] == [["assistant", "noted amber notebook"]]
        assert "silver compass" not in str(body)

    assert "amber notebook" in recalled[0]["medium_term"]["summary"]
    assert recalled[0]["short_term"]["window"] == [["assistant", "noted amber notebook"]]
    assert "silver compass" not in str(recalled[0])
    assert "silver compass" in recalled[1]["medium_term"]["summary"]
    assert recalled[1]["short_term"]["window"] == [["assistant", "noted silver compass"]]
    assert "amber notebook" not in str(recalled[1])
