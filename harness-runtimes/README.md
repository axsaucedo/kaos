# KAOS harness runtimes

A **harness driver**: a small FastAPI service that runs a real coding harness
(`pi`, Claude Code, …) as a subprocess and serves KAOS's **existing** Agent HTTP
contract in front of it.

The operator never talks to the process inside an agent pod — it resolves
dependencies into env vars and talks HTTP to `:8000`. So a pod that serves the
same routes `pydantic-ai-server` serves is indistinguishable from a pydantic-ai
agent pod to the operator, `kaos-cli` and `kaos-ui`. **No new CRD is needed**;
a harness agent is an ordinary `Agent` with a different `spec.container.image`.

```
harness-runtimes/
├── kaos_harness/
│   ├── driver.py      # FastAPI app serving the KAOS agent contract
│   ├── harnesses.py   # per-harness adapters, selected by HARNESS_DRIVER
│   └── cli.py         # kaos-harness serve
├── tests/             # contract suite + adapter unit tests
└── pi/Dockerfile      # image bundling `pi` + the driver
```

## The contract

| Route | Consumer |
|---|---|
| `GET /health` | operator liveness probe |
| `GET /ready` | operator readiness probe |
| `GET /.well-known/agent.json` | A2A card — `RemoteAgent` branches on `supportedProtocols` containing `"jsonrpc"` |
| `GET /tools` | tool listing |
| `GET /memory/events` | kaos-ui memory tab (2s poll) |
| `GET /memory/sessions` | session listing |
| `POST /v1/chat/completions` | kaos-cli + kaos-ui chat; SSE when `stream: true` |
| `POST /` | A2A JSON-RPC: `SendMessage`/`GetTask`/`ListTasks`/`CancelTask` (+ `tasks/*` aliases) |

`GET /sessions` is a driver extra, not part of the contract — it exposes the
per-session workspace mapping, which has no home on `AgentStatus`.

### SSE chunk shape

Every chunk is an OpenAI `chat.completion.chunk` whose `id` is the **session id**.
Progress events ride **inside `delta.content` as a JSON string**, because that is
how both clients already detect them ("content starts with `{` and parses"):

```
data: {"id":"sess-1","object":"chat.completion.chunk","created":…,"model":…,
       "choices":[{"index":0,"delta":{"content":
         "{\"type\":\"progress\",\"step\":1,\"max_steps\":25,\"action\":\"tool_call\",\"target\":\"bash\"}"
       },"finish_reason":null}]}
data: {… "delta":{"content":"the answer"} …}
data: {… "delta":{}, "finish_reason":"stop"}
data: [DONE]
```

## Configuration

Env vars only — the operator supplies all of them.

| Variable | Default | Meaning |
|---|---|---|
| `AGENT_NAME` | `harness` | Agent name, on the A2A card |
| `AGENT_DESCRIPTION` | `coding harness agent` | A2A card description |
| `AGENT_INSTRUCTIONS` | *(empty)* | Appended to the harness system prompt |
| `AGENT_PORT` | `8000` | Bind port |
| `MODEL_API_URL` | *(empty)* | KAOS `ModelAPI` base URL |
| `MODEL_NAME` | `mock-model` | Model id |
| `MODEL_API_KEY` | `not-needed` | Credential passed to the harness |
| `HARNESS_DRIVER` | `pi` | Adapter: `pi` \| `claude` |
| `HARNESS_WORKSPACE` | `/workspace` | Workspace root; each session gets a subdirectory |
| `HARNESS_STATE_DIR` | `/state` | Harness `HOME`, provider config and session transcripts |
| `HARNESS_BIN` | *(adapter default)* | Override the harness executable path |
| `HARNESS_TIMEOUT_SECONDS` | `600` | Per-turn wall-clock limit |

## Sessions

Sessions are keyed off the `X-Session-ID` header (falling back to a `session_id`
body field, then a fresh UUID). Each session gets its own directory under
`$HARNESS_WORKSPACE/.sessions/<id>`, so **one pod serves N concurrent sessions**.
An `Agent` is always one pod — `replicas` is a literal in the operator — but a pod
is not one session; routing to a session is a header, not a Service endpoint.
What that costs is isolation and per-session resource limits, not concurrency.

## Adding a harness

Subclass `Harness` in `kaos_harness/harnesses.py` and add it to `REGISTRY`:

```python
class DshHarness(Harness):
    name = "dsh"
    default_binary = "dsh"
    builtin_tools = ["bash", "edit", "read", "write"]

    def prepare(self) -> None: ...          # point it at MODEL_API_URL
    def environ(self) -> dict[str, str]: ...  # subprocess environment

    async def run(self, prompt, session_id, workspace):
        yield HarnessEvent(kind="tool_call", target="bash")
        yield HarnessEvent(kind="usage", usage={...})
        yield HarnessEvent(kind="text", text="done")
```

The driver maps `tool_call` to a progress event, `usage` to a memory event, and
`text` to assistant content. Two candidates are known and not implemented:
**DeepSeek Harness** (`dsh`, npm `@deepseek-ai/dsh`, MIT, native ACP and a native
JSON-RPC SDK server) and **Hermes** (`hermes -z`, native `hermes acp`).

### The wire-format constraint

Harnesses do **not** agree on what an LLM endpoint looks like, and this decides
whether an adapter works against a KAOS `ModelAPI` at all.

| Harness | Wire format | Works with `ModelAPI` today | Configured by |
|---|---|---|---|
| `pi` (MIT, KAOS ships the image) | OpenAI `/v1/chat/completions` | **yes** | custom provider in `$HOME/.pi/agent/models.json` |
| Claude Code (proprietary, BYO image) | Anthropic `/v1/messages` **only** | **no** — needs a passthrough `ModelAPI` | `ANTHROPIC_BASE_URL` / `ANTHROPIC_AUTH_TOKEN` |
| Codex CLI | OpenAI `/v1/responses` only | no | `model_providers.*` TOML |

Pointing Claude Code at an OpenAI-shaped endpoint 404s silently and surfaces as
"There's an issue with the selected model". LiteLLM can serve all three formats,
but that is a `ModelAPI` change, not a driver change.

Two further measured gotchas, both easy to get silently wrong:

- `pi` is driven with `--mode rpc`, not `-p`. The RPC stream is LF-delimited
  NDJSON with `tool_execution_*` lifecycle events and per-message token **usage
  and cost**; `-p` gives the final text only. No handshake is needed: write one
  `{"type":"prompt","message":…}` line to stdin, read until `agent_settled`.
- Claude Code's `--disallowedTools` removes tools from the wire.
  `--allowedTools` does **not** — it is a permission allowlist, not an
  availability filter.

## Development

```bash
cd harness-runtimes
uv pip install -e '.[dev]'
uv run pytest tests/ -v
make lint          # black --check + ty
```

The contract suite runs against `tests/mock_modelapi.py`, an
OpenAI/Anthropic-compatible mock, with a **fake credential and no network**. It
still needs the harness binary; when that is absent it **skips** rather than
fails. `pi` is an npm package, so point `HARNESS_BIN` at a local install:

```bash
HARNESS_BIN=/path/to/node_modules/.bin/pi uv run pytest tests/ -v
```

## Image

```bash
make docker-build          # builds pi/Dockerfile from this directory
```

`pi/Dockerfile` bundles `@earendil-works/pi-coding-agent` and the driver, runs as
non-root UID 65532, and serves the driver on `:8000`.
