"""Per-harness adapters.

A harness is a coding agent CLI that KAOS drives as a subprocess. Each adapter
owns three things and nothing else:

1. how to point the harness at the operator-supplied ``MODEL_API_URL``,
2. how to invoke it headlessly for one turn,
3. how to turn its output into :class:`HarnessEvent` values the driver can map
   onto KAOS's SSE progress-event contract.

Adding a harness is a subclass plus a ``REGISTRY`` entry. The known next
candidates are DeepSeek Harness (``dsh``, MIT, native ACP + JSON-RPC SDK server)
and Hermes (``hermes -z``, native ``hermes acp``); neither is implemented here.

**Wire format is the constraint, not the CLI.** Harnesses do not agree on what
an LLM endpoint looks like, so an adapter is only usable against a ModelAPI that
speaks its format:

===========  ====================================  ====================================
Harness      Wire format                           Works with KAOS ModelAPI today
===========  ====================================  ====================================
``pi``       OpenAI ``/v1/chat/completions``        yes
``claude``   Anthropic ``/v1/messages`` **only**    no — needs a passthrough ModelAPI
===========  ====================================  ====================================
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Dict, List, Optional, Type


@dataclass
class HarnessConfig:
    """Everything an adapter needs, all of it from the operator's env vars."""

    model_api_url: str = ""
    model_name: str = "mock-model"
    instructions: str = ""
    state_dir: str = "/state"
    binary: str = ""
    api_key: str = "not-needed"
    timeout_seconds: float = 600.0


@dataclass
class HarnessEvent:
    """One thing that happened inside the harness during a turn.

    ``kind`` is one of ``tool_call`` (a tool started), ``text`` (assistant text)
    or ``usage`` (token/cost accounting for one assistant message).
    """

    kind: str
    target: str = ""
    text: str = ""
    usage: Dict[str, Any] = field(default_factory=dict)


class Harness:
    """Base adapter. Subclasses implement :meth:`run`."""

    name: str = ""
    default_binary: str = ""
    builtin_tools: List[str] = []

    def __init__(self, config: HarnessConfig) -> None:
        self.config = config
        self.binary = config.binary or self.default_binary

    # --- discovery ---------------------------------------------------------

    def resolve_binary(self) -> Optional[str]:
        """Absolute path to the harness executable, or None when absent."""
        if os.sep in self.binary:
            return self.binary if os.access(self.binary, os.X_OK) else None
        return shutil.which(self.binary)

    def available(self) -> bool:
        return self.resolve_binary() is not None

    def tools(self) -> List[Dict[str, str]]:
        """Tools the harness owns. KAOS sees the harness toolset as opaque."""
        return [{"name": n, "description": f"{self.name} builtin: {n}"} for n in self.builtin_tools]

    # --- lifecycle ---------------------------------------------------------

    def prepare(self) -> None:
        """One-time setup (provider config, credentials). Called at startup."""

    def environ(self) -> Dict[str, str]:
        """Environment for the subprocess."""
        return dict(os.environ)

    async def run(
        self, prompt: str, session_id: str, workspace: str
    ) -> AsyncIterator[HarnessEvent]:
        """Drive one turn, yielding events as they happen."""
        raise NotImplementedError
        yield  # pragma: no cover - makes this an async generator for subclasses

    # --- helpers for subclasses -------------------------------------------

    async def _spawn(self, argv: List[str], workspace: str) -> asyncio.subprocess.Process:
        return await asyncio.create_subprocess_exec(
            *argv,
            cwd=workspace or None,
            env=self.environ(),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )


class PiHarness(Harness):
    """`pi` (MIT) — driven over its native ``--mode rpc`` NDJSON stream.

    ``--mode rpc`` is preferred over ``-p`` because it is the only surface that
    reports per-tool-call lifecycle and per-message token usage and cost, which
    is what KAOS's progress events and (future) cost attribution need. The
    protocol needs no handshake: write one ``{"type":"prompt",...}`` line on
    stdin and read events until ``agent_settled``; closing stdin then exits 0.

    ``pi`` speaks OpenAI chat completions, so a KAOS ModelAPI works unchanged —
    the adapter writes a custom provider into ``$HOME/.pi/agent/models.json``
    with ``HOME`` pointed at the state dir.
    """

    name = "pi"
    default_binary = "pi"
    builtin_tools = ["bash", "edit", "read", "write"]
    PROVIDER = "kaos-modelapi"

    def prepare(self) -> None:
        cfg_dir = os.path.join(self.config.state_dir, ".pi", "agent")
        os.makedirs(cfg_dir, exist_ok=True)
        base_url = (
            f"{self.config.model_api_url.rstrip('/')}/v1" if self.config.model_api_url else ""
        )
        with open(os.path.join(cfg_dir, "models.json"), "w") as fh:
            json.dump(
                {
                    "providers": {
                        self.PROVIDER: {
                            "name": "KAOS ModelAPI",
                            "baseUrl": base_url,
                            "apiKey": self.config.api_key,
                            "api": "openai-completions",
                            "models": [
                                {
                                    "id": self.config.model_name,
                                    "name": self.config.model_name,
                                    "contextWindow": 128000,
                                    "maxTokens": 8192,
                                }
                            ],
                        }
                    }
                },
                fh,
            )

    def environ(self) -> Dict[str, str]:
        # pi reads its provider config from $HOME/.pi; the state dir is the HOME
        # so the config survives restarts on a mounted volume.
        return {**os.environ, "HOME": self.config.state_dir}

    def argv(self, session_id: str) -> List[str]:
        argv = [
            self.resolve_binary() or self.binary,
            "--mode",
            "rpc",
            "--provider",
            self.PROVIDER,
            "--model",
            self.config.model_name,
            "--session-dir",
            os.path.join(self.config.state_dir, "sessions"),
            "--session-id",
            session_id,
            "--no-extensions",
            "--no-skills",
            "--no-context-files",
        ]
        if self.config.instructions:
            argv += ["--append-system-prompt", self.config.instructions]
        return argv

    async def run(
        self, prompt: str, session_id: str, workspace: str
    ) -> AsyncIterator[HarnessEvent]:
        os.makedirs(os.path.join(self.config.state_dir, "sessions"), exist_ok=True)
        proc = await self._spawn(self.argv(session_id), workspace)
        assert proc.stdin is not None and proc.stdout is not None

        proc.stdin.write((json.dumps({"type": "prompt", "message": prompt}) + "\n").encode())
        await proc.stdin.drain()

        # Drain stderr concurrently: a full pipe buffer would otherwise block the
        # harness mid-turn, and it is the only diagnostic when a turn produces
        # no assistant text at all.
        stderr_task = asyncio.ensure_future(proc.stderr.read()) if proc.stderr else None

        saw_text = False
        try:
            async for event in self._read_events(proc):
                if event.kind == "text":
                    saw_text = True
                yield event
        finally:
            await self._shutdown(proc)

        if not saw_text:
            yield HarnessEvent(
                kind="text", text=await _drain(stderr_task) or "(harness produced no output)"
            )

    async def _read_events(self, proc: asyncio.subprocess.Process) -> AsyncIterator[HarnessEvent]:
        """Translate pi's NDJSON event stream into HarnessEvents.

        The stream is LF-delimited only, so lines are read rather than framed.
        """
        assert proc.stdout is not None
        deadline = asyncio.get_running_loop().time() + self.config.timeout_seconds
        while True:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                break
            try:
                raw = await asyncio.wait_for(proc.stdout.readline(), timeout=remaining)
            except asyncio.TimeoutError:
                break
            if not raw:
                break
            line = raw.decode(errors="replace").strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue

            etype = event.get("type")
            if etype == "tool_execution_start":
                yield HarnessEvent(kind="tool_call", target=event.get("toolName", "tool"))
            elif etype == "message_end":
                message = event.get("message") or {}
                if message.get("role") != "assistant":
                    continue
                usage = message.get("usage")
                if usage:
                    yield HarnessEvent(kind="usage", usage=usage)
                text = "".join(
                    part.get("text", "")
                    for part in message.get("content", [])
                    if part.get("type") == "text"
                )
                if text:
                    yield HarnessEvent(kind="text", text=text)
            elif etype == "agent_settled":
                break

    async def _shutdown(self, proc: asyncio.subprocess.Process) -> None:
        if proc.stdin is not None and not proc.stdin.is_closing():
            proc.stdin.close()
        try:
            await asyncio.wait_for(proc.wait(), timeout=10)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()


async def _drain(task: "Optional[asyncio.Future[bytes]]") -> str:
    """Collect a backgrounded stderr read without letting it hang shutdown."""
    if task is None:
        return ""
    try:
        return (await asyncio.wait_for(task, timeout=5)).decode(errors="replace").strip()
    except (asyncio.TimeoutError, asyncio.CancelledError):
        return ""


class ClaudeHarness(Harness):
    """Claude Code (proprietary) — BYO image, driven headlessly with ``-p``.

    Claude Code speaks the Anthropic ``/v1/messages`` wire format **only**; an
    OpenAI-shaped endpoint 404s and surfaces as "There's an issue with the
    selected model". The bound ModelAPI must therefore be a ``/v1/messages``
    passthrough, which LiteLLM supports but KAOS's ModelAPI does not serve yet.

    Tool availability is controlled with ``--disallowedTools``. ``--allowedTools``
    is a *permission* allowlist and does **not** remove tools from the wire —
    conflating the two is a silent failure.
    """

    name = "claude"
    default_binary = "claude"
    builtin_tools = ["Bash", "Edit", "Read", "Write", "Glob", "Grep"]

    def environ(self) -> Dict[str, str]:
        env = {**os.environ, "HOME": self.config.state_dir}
        if self.config.model_api_url:
            env["ANTHROPIC_BASE_URL"] = self.config.model_api_url.rstrip("/")
        env["ANTHROPIC_AUTH_TOKEN"] = self.config.api_key
        env["ANTHROPIC_MODEL"] = self.config.model_name
        return env

    def prepare(self) -> None:
        os.makedirs(self.config.state_dir, exist_ok=True)

    def argv(self, prompt: str) -> List[str]:
        argv = [self.resolve_binary() or self.binary, "-p", "--model", self.config.model_name]
        if self.config.instructions:
            argv += ["--append-system-prompt", self.config.instructions]
        argv.append(prompt)
        return argv

    async def run(
        self, prompt: str, session_id: str, workspace: str
    ) -> AsyncIterator[HarnessEvent]:
        proc = await self._spawn(self.argv(prompt), workspace)
        if proc.stdin is not None:
            proc.stdin.close()
        # `-p` emits the final answer only; there is no per-tool-call surface to
        # map, so one synthetic progress event stands in for the whole turn.
        yield HarnessEvent(kind="tool_call", target=self.name)
        try:
            out, err = await asyncio.wait_for(
                proc.communicate(), timeout=self.config.timeout_seconds
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            yield HarnessEvent(kind="text", text="(harness timed out)")
            return
        text = (out or b"").decode().strip() or (err or b"").decode().strip()
        yield HarnessEvent(kind="text", text=text or "(harness produced no output)")


REGISTRY: Dict[str, Type[Harness]] = {
    PiHarness.name: PiHarness,
    ClaudeHarness.name: ClaudeHarness,
}


def get_harness(name: str, config: HarnessConfig) -> Harness:
    """Instantiate the adapter selected by ``HARNESS_DRIVER``."""
    try:
        cls = REGISTRY[name]
    except KeyError:
        raise ValueError(
            f"unknown harness {name!r}; available: {', '.join(sorted(REGISTRY))}"
        ) from None
    return cls(config)
