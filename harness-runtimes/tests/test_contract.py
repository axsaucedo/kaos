"""Does the driver satisfy the KAOS Agent contract?

Each assertion maps to a real consumer in the KAOS codebase, cited inline. If
they all pass, the operator, kaos-cli and kaos-ui cannot distinguish a harness
pod from a pydantic-ai one.
"""

import concurrent.futures as cf
import json
import os
import time

import httpx
import pytest

# --- operator-facing: agent_controller.go sets these two probes ---------------


def test_liveness_probe(driver):
    response = httpx.get(f"{driver}/health", timeout=5)
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


def test_readiness_probe(driver):
    response = httpx.get(f"{driver}/ready", timeout=5)
    assert response.status_code == 200
    assert response.json()["available"] is True


# --- A2A card: serverutils.AgentCard, consumed by RemoteAgent + kaos-ui -------


def test_agent_card_shape(driver):
    card = httpx.get(f"{driver}/.well-known/agent.json", timeout=5).json()
    for key in (
        "name",
        "description",
        "url",
        "version",
        "protocolVersion",
        "capabilities",
        "skills",
        "supportedProtocols",
        "defaultInputModes",
        "defaultOutputModes",
    ):
        assert key in card, f"AgentCard missing {key}"
    # RemoteAgent.process_message picks the A2A path on this exact check.
    assert "jsonrpc" in card["supportedProtocols"]


def test_tools_listing(driver):
    body = httpx.get(f"{driver}/tools", timeout=5).json()
    assert body["agent"] == "coder"
    assert body["tools"], "harness must advertise its builtin toolset"
    assert all({"name", "description"} <= t.keys() for t in body["tools"])


# --- chat: kaos_cli/agent/invoke.py + kaos-ui lib/agent-client.ts -------------


def test_chat_completions_non_streaming(driver, script):
    script([{"type": "text", "text": "NONSTREAM_OK"}])
    response = httpx.post(
        f"{driver}/v1/chat/completions",
        timeout=180,
        headers={"X-Session-ID": "sess-nonstream"},
        json={"messages": [{"role": "user", "content": "hi"}]},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["object"] == "chat.completion"
    assert body["id"] == "sess-nonstream"
    assert "NONSTREAM_OK" in body["choices"][0]["message"]["content"]
    assert body["choices"][0]["finish_reason"] == "stop"


def test_chat_completions_requires_messages(driver):
    response = httpx.post(f"{driver}/v1/chat/completions", timeout=10, json={})
    assert response.status_code == 400


def test_chat_completions_sse_shape(driver, script):
    """kaos-ui detects progress events by 'content starts with { and parses'
    (agent-client.ts); kaos-cli uses the same heuristic (invoke.py)."""
    script(
        [
            {"type": "tool", "name": "bash", "args": {"command": "echo hi"}},
            {"type": "text", "text": "STREAM_OK"},
        ]
    )
    saw_progress = saw_final = saw_done = saw_stop = False
    with httpx.stream(
        "POST",
        f"{driver}/v1/chat/completions",
        timeout=180,
        headers={"X-Session-ID": "sess-stream"},
        json={"messages": [{"role": "user", "content": "hi"}], "stream": True},
    ) as response:
        assert response.status_code == 200
        for line in response.iter_lines():
            if not line.startswith("data: "):
                continue
            payload = line[6:]
            if payload == "[DONE]":
                saw_done = True
                continue
            chunk = json.loads(payload)
            assert chunk["object"] == "chat.completion.chunk"
            assert chunk["id"] == "sess-stream", "chunk id must carry the session id"
            choice = chunk["choices"][0]
            assert choice["index"] == 0
            if choice["finish_reason"] == "stop":
                saw_stop = True
                continue
            assert choice["finish_reason"] is None
            content = choice["delta"].get("content")
            if content and content.startswith("{"):
                event = json.loads(content)
                if event.get("type") == "progress":
                    assert {"step", "max_steps", "action", "target"} <= event.keys()
                    assert event["action"] == "tool_call"
                    saw_progress = True
            elif content and "STREAM_OK" in content:
                saw_final = True
    assert saw_progress, "no progress event rode inside delta.content"
    assert saw_final and saw_stop and saw_done


# --- A2A JSON-RPC: pais/a2a.py dispatcher, driven by `kaos agent a2a` ---------


def test_a2a_send_get_list_cancel(driver, script):
    script([{"type": "text", "text": "A2A_OK"}])
    send = httpx.post(
        driver,
        timeout=180,
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "SendMessage",
            "params": {
                "message": {"role": "user", "parts": [{"type": "text", "text": "hi"}]},
                "contextId": "sess-a2a",
            },
        },
    ).json()
    assert "error" not in send, send
    task = send["result"]
    assert task["status"]["state"] == "completed"
    assert task["contextId"] == "sess-a2a"
    assert "A2A_OK" in task["artifacts"][0]["parts"][0]["text"]

    got = httpx.post(
        driver,
        timeout=10,
        json={"jsonrpc": "2.0", "id": 2, "method": "GetTask", "params": {"id": task["id"]}},
    ).json()
    assert got["result"]["id"] == task["id"]

    listed = httpx.post(
        driver, timeout=10, json={"jsonrpc": "2.0", "id": 3, "method": "ListTasks", "params": {}}
    ).json()
    assert any(t["id"] == task["id"] for t in listed["result"]["tasks"])

    canceled = httpx.post(
        driver,
        timeout=10,
        json={"jsonrpc": "2.0", "id": 4, "method": "CancelTask", "params": {"id": task["id"]}},
    ).json()
    assert canceled["result"]["status"]["state"] == "canceled"


def test_a2a_legacy_aliases(driver, script):
    script([{"type": "text", "text": "ALIAS_OK"}])
    send = httpx.post(
        driver,
        timeout=180,
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tasks/send",
            "params": {
                "message": {"role": "user", "parts": [{"type": "text", "text": "hi"}]},
                "contextId": "sess-alias",
            },
        },
    ).json()
    assert "ALIAS_OK" in send["result"]["artifacts"][0]["parts"][0]["text"]

    got = httpx.post(
        driver,
        timeout=10,
        json={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tasks/get",
            "params": {"id": send["result"]["id"]},
        },
    ).json()
    assert got["result"]["id"] == send["result"]["id"]


def test_a2a_unknown_method_is_jsonrpc_error(driver):
    response = httpx.post(
        driver, timeout=10, json={"jsonrpc": "2.0", "id": 9, "method": "Nope", "params": {}}
    ).json()
    assert response["error"]["code"] == -32601


def test_a2a_unknown_task_is_jsonrpc_error(driver):
    response = httpx.post(
        driver,
        timeout=10,
        json={"jsonrpc": "2.0", "id": 10, "method": "GetTask", "params": {"id": "nope"}},
    ).json()
    assert response["error"]["code"] == -32001


# --- kaos-ui memory tab: 2s poll of /memory/events ---------------------------


def test_memory_events_populated(driver):
    body = httpx.get(
        f"{driver}/memory/events", params={"session_id": "sess-stream"}, timeout=5
    ).json()
    assert body["agent"] == "coder"
    kinds = {event["event_type"] for event in body["events"]}
    assert {"user_message", "agent_response"} <= kinds
    assert "tool_call" in kinds, "tool lifecycle must reach memory"
    for event in body["events"]:
        assert {"event_id", "timestamp", "event_type", "content", "metadata"} <= event.keys()


def test_memory_sessions_listed(driver):
    body = httpx.get(f"{driver}/memory/sessions", timeout=5).json()
    assert "sess-stream" in body["sessions"]
    assert body["total"] == len(body["sessions"])


def test_usage_is_recorded(driver):
    """pi's rpc stream reports per-message usage and cost; `claude -p` does not."""
    if os.environ.get("HARNESS_DRIVER", "pi") != "pi":
        pytest.skip("usage accounting is only available on pi's rpc stream")
    events = httpx.get(
        f"{driver}/memory/events", params={"session_id": "sess-stream"}, timeout=5
    ).json()["events"]
    usage = [e for e in events if e["event_type"] == "usage"]
    assert usage, "no usage event captured from the harness stream"
    assert "totalTokens" in usage[0]["content"]


# --- the ceiling: can ONE pod serve N addressable parallel sessions? ---------


def test_parallel_sessions_get_distinct_workspaces(driver, script):
    """An Agent is always one pod, but a pod is not one session: sessions are
    keyed off X-Session-ID and each gets its own workspace directory."""
    n = 4
    script([{"type": "text", "text": f"S{i}"} for i in range(n)] * 4)

    def one(i):
        response = httpx.post(
            f"{driver}/v1/chat/completions",
            timeout=300,
            headers={"X-Session-ID": f"par-{i}"},
            json={"messages": [{"role": "user", "content": f"task {i}"}]},
        )
        return response.status_code, response.json()["id"]

    started = time.time()
    with cf.ThreadPoolExecutor(max_workers=n) as pool:
        results = list(pool.map(one, range(n)))
    elapsed = time.time() - started

    assert all(code == 200 for code, _ in results), results
    assert {sid for _, sid in results} == {f"par-{i}" for i in range(n)}

    sessions = httpx.get(f"{driver}/sessions", timeout=5).json()["sessions"]
    workspaces = {s["id"]: s["workspace"] for s in sessions if s["id"].startswith("par-")}
    assert len(workspaces) == n
    assert len(set(workspaces.values())) == n, f"workspaces collided: {workspaces}"
    print(f"\n  {n} concurrent sessions in one pod in {elapsed:.1f}s, {n} distinct workspaces")


def test_harness_reached_model_with_a_fake_credential(driver, mock_modelapi, script):
    """The suite's premise: no real credential and no network egress."""
    script([{"type": "text", "text": "CREDENTIAL_OK"}])
    httpx.post(
        f"{driver}/v1/chat/completions",
        timeout=180,
        headers={"X-Session-ID": "sess-cred"},
        json={"messages": [{"role": "user", "content": "hi"}]},
    )
    calls = httpx.get(f"{mock_modelapi}/_calls", timeout=5).json()
    assert calls, "no model calls recorded"
    assert calls[0]["auth"].startswith("Bearer "), calls[0]
