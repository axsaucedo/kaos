"""Mock ModelAPI for the harness contract tests.

Stands in for a KAOS ModelAPI (LiteLLM proxy) so a harness can be pointed at an
arbitrary base URL with **no real credential and no network egress**, which is
what lets the contract suite run in CI.

Speaks all three wire formats the surveyed harnesses need, because they do not
agree: ``/v1/chat/completions`` (``pi``), ``/v1/responses`` (Codex) and
``/v1/messages`` (Claude Code).

Scripted turns: each request pops the next response off RESPONSES. A response is
either plain text or a tool call, so a harness's tool loop can be exercised.

    python3 mock_modelapi.py [port]
"""

import json
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# Scripted turns, consumed in order. Set via /_script before driving the harness.
RESPONSES = [{"type": "text", "text": "ack"}]
CALLS = []


def _chunk(model, delta, finish=None):
    return {
        "id": "chatcmpl-mock",
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
    }


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args) -> None:
        pass  # keep test output readable

    def _send(self, code, body, ctype="application/json"):
        raw = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path.startswith("/v1/models"):
            self._send(
                200,
                json.dumps(
                    {
                        "object": "list",
                        "data": [{"id": "mock-model", "object": "model", "owned_by": "kaos"}],
                    }
                ),
            )
        elif self.path == "/_calls":
            self._send(200, json.dumps(CALLS))
        else:
            self._send(404, json.dumps({"error": "not found"}))

    def _do_responses(self, req):
        """Minimal OpenAI Responses API. Codex CLI dropped Chat Completions, so a
        harness driver pointed at a KAOS ModelAPI needs this wire format."""
        CALLS.append(
            {
                "wire": "responses",
                "n_messages": len(req.get("input", []) or []),
                "tools": sorted(t.get("name", "?") for t in req.get("tools", []) or []),
                "auth": self.headers.get("Authorization", ""),
            }
        )
        nxt = RESPONSES.pop(0) if RESPONSES else {"type": "text", "text": "done"}
        text = nxt.get("text", "done")
        item = {
            "type": "message",
            "id": "msg_1",
            "status": "completed",
            "role": "assistant",
            "content": [{"type": "output_text", "text": text, "annotations": []}],
        }
        resp = {
            "id": "resp_mock",
            "object": "response",
            "created_at": int(time.time()),
            "status": "completed",
            "model": req.get("model", "mock-model"),
            "output": [item],
            "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
        }

        if not req.get("stream"):
            return self._send(200, json.dumps(resp))

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        seq = [
            ("response.created", {"response": dict(resp, status="in_progress", output=[])}),
            ("response.output_item.added", {"output_index": 0, "item": dict(item, content=[])}),
            (
                "response.output_text.delta",
                {"output_index": 0, "content_index": 0, "item_id": "msg_1", "delta": text},
            ),
            (
                "response.output_text.done",
                {"output_index": 0, "content_index": 0, "item_id": "msg_1", "text": text},
            ),
            ("response.output_item.done", {"output_index": 0, "item": item}),
            ("response.completed", {"response": resp}),
        ]
        for i, (ev, data) in enumerate(seq):
            payload = dict(data, type=ev, sequence_number=i)
            self.wfile.write(f"event: {ev}\ndata: {json.dumps(payload)}\n\n".encode())
        self.wfile.flush()

    def _do_messages(self, req):
        """Minimal Anthropic Messages API. Claude Code speaks this wire format only,
        so a KAOS ModelAPI in front of it must be a `/v1/messages` passthrough."""
        CALLS.append(
            {
                "wire": "messages",
                "n_messages": len(req.get("messages", []) or []),
                "tools": sorted(t.get("name", "?") for t in req.get("tools", []) or []),
                "auth": self.headers.get("Authorization", "") or self.headers.get("x-api-key", ""),
            }
        )
        # Claude Code issues a toolless preflight (title/topic generation) before
        # the real agent turn. It must not consume a scripted response, or every
        # script is off by one and tool calls never reach the agent loop.
        if not (req.get("tools") or []):
            nxt = {"type": "text", "text": "preflight"}
        else:
            nxt = RESPONSES.pop(0) if RESPONSES else {"type": "text", "text": "done"}
        text = nxt.get("text", "done")
        model = req.get("model", "mock-model")
        usage = {"input_tokens": 1, "output_tokens": 1}
        if nxt["type"] == "tool":
            block = {"type": "tool_use", "id": "toolu_1", "name": nxt["name"], "input": nxt["args"]}
            stop = "tool_use"
        else:
            block = {"type": "text", "text": text}
            stop = "end_turn"
        body = {
            "id": "msg_mock",
            "type": "message",
            "role": "assistant",
            "model": model,
            "content": [block],
            "stop_reason": stop,
            "stop_sequence": None,
            "usage": usage,
        }

        if not req.get("stream"):
            return self._send(200, json.dumps(body))

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        if stop == "tool_use":
            start_block = {"type": "tool_use", "id": "toolu_1", "name": nxt["name"], "input": {}}
            delta = {"type": "input_json_delta", "partial_json": json.dumps(nxt["args"])}
        else:
            start_block = {"type": "text", "text": ""}
            delta = {"type": "text_delta", "text": text}
        seq = [
            ("message_start", {"message": dict(body, content=[], stop_reason=None)}),
            ("content_block_start", {"index": 0, "content_block": start_block}),
            ("content_block_delta", {"index": 0, "delta": delta}),
            ("content_block_stop", {"index": 0}),
            (
                "message_delta",
                {
                    "delta": {"stop_reason": stop, "stop_sequence": None},
                    "usage": {"output_tokens": 1},
                },
            ),
            ("message_stop", {}),
        ]
        for ev, data in seq:
            payload = dict(data, type=ev)
            self.wfile.write(f"event: {ev}\ndata: {json.dumps(payload)}\n\n".encode())
        self.wfile.flush()

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(n)
        try:
            req = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            req = {}

        if self.path == "/_script":
            RESPONSES[:] = req.get("responses", [])
            CALLS.clear()
            return self._send(200, json.dumps({"ok": True, "n": len(RESPONSES)}))

        if self.path.startswith("/v1/responses"):
            return self._do_responses(req)

        if self.path.startswith("/v1/messages"):
            return self._do_messages(req)

        if not self.path.startswith("/v1/chat/completions"):
            return self._send(404, json.dumps({"error": "not found"}))

        CALLS.append(
            {
                "n_messages": len(req.get("messages", [])),
                "tools": sorted(
                    t.get("function", {}).get("name", "?") for t in req.get("tools", []) or []
                ),
                "auth": self.headers.get("Authorization", ""),
            }
        )

        model = req.get("model", "mock-model")
        nxt = RESPONSES.pop(0) if RESPONSES else {"type": "text", "text": "done"}

        if nxt["type"] == "tool":
            msg = {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": nxt["name"], "arguments": json.dumps(nxt["args"])},
                    }
                ],
            }
            finish = "tool_calls"
        else:
            msg = {"role": "assistant", "content": nxt["text"]}
            finish = "stop"

        if req.get("stream"):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            delta = dict(msg)
            delta.pop("role", None)
            for c in (
                _chunk(model, {"role": "assistant"}),
                _chunk(model, delta),
                _chunk(model, {}, finish),
            ):
                self.wfile.write(f"data: {json.dumps(c)}\n\n".encode())
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
            return

        self._send(
            200,
            json.dumps(
                {
                    "id": "chatcmpl-mock",
                    "object": "chat.completion",
                    "created": int(time.time()),
                    "model": model,
                    "choices": [{"index": 0, "message": msg, "finish_reason": finish}],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                }
            ),
        )


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8099
    print(f"mock ModelAPI on :{port}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
