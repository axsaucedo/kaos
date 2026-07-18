"""Pydantic AI adapters for KAOS memory.

These bridge the Pydantic AI runtime to the memory contract without the memory
code depending on the agent framework's internals:

- :func:`scope_from_deps` derives the server-side :class:`~kaos_memory.contract.Scope`
  from the run dependencies and the agent's verifiable identity, never from
  model- or tool-supplied arguments;
- :func:`pydantic_message_to_turns` renders a Pydantic AI message into short-term
  tier ``(role, content)`` turns;
- :func:`reconstruct_message_history` rebuilds Pydantic AI ``message_history`` from
  short-term tier turns.

Pydantic AI is imported lazily inside the message functions so this module is
importable without the framework when only :func:`scope_from_deps` is needed.
"""

from __future__ import annotations

import json
from typing import Any, List, Optional, Tuple, Union

from kaos_memory.contract import Scope, ScopeLevel


def scope_from_deps(
    deps: Any,
    *,
    level: Union[ScopeLevel, str],
    agent_identity: Optional[str] = None,
) -> Scope:
    """Build the request :class:`~kaos_memory.contract.Scope` from server-derived identity.

    The scope is derived only from the authenticated request context (principal,
    session) carried on ``deps`` and the agent's verifiable identity (its minted
    actor identity, or the operator-provided ``agent_identity``). It deliberately
    accepts no scope argument from the model or a tool, so a caller can never
    widen or redirect the scope it is entitled to; the ``level`` is fixed by the
    agent's configuration, not by request content.

    Fails closed on ambiguous ownership: an ``AGENT`` scope must resolve to a
    concrete, agent-unique owner (the qualified ``kaos://agent/{namespace}/{name}``
    identity, threaded via ``agent_identity`` or the request actor). Without one,
    every agent lacking an identity would collapse onto the same empty owner and
    silently share one agent partition, so this raises rather than cross-contaminate.
    """
    resolved_level = level if isinstance(level, ScopeLevel) else ScopeLevel(str(level))
    security_context = getattr(deps, "security_context", None) or {}
    agent_client_id = agent_identity or security_context.get("actor") or None
    if resolved_level is ScopeLevel.AGENT and not agent_client_id:
        raise ValueError(
            "AGENT memory scope requires a stable agent identity; refusing to "
            "operate on an ambiguously-owned agent partition"
        )
    return Scope(
        level=resolved_level,
        principal=security_context.get("principal") or None,
        agent_client_id=agent_client_id,
        session_id=getattr(deps, "session_id", None) or None,
    )


def pydantic_message_to_turns(msg: Any) -> List[Tuple[str, str]]:
    """Render a Pydantic AI message into short-term tier turns, preserving fidelity.

    Returns a list of ``(role, content)`` turns capturing every replay-relevant
    part — user prompts, assistant text, tool calls, tool returns, and delegation
    requests/responses — as readable text. The short-term tier stores turns as text,
    so a tool call is recorded as a faithful description (the model sees that it
    already invoked the tool) rather than as a raw tool-call part that could be
    replayed without its matching return. Returns an empty list for parts with no
    replay value.
    """
    from pydantic_ai.messages import (
        ModelRequest,
        ModelResponse as PydanticModelResponse,
        TextPart,
        ToolCallPart,
        ToolReturnPart,
        UserPromptPart,
    )

    turns: List[Tuple[str, str]] = []

    def _stringify(value: Any) -> str:
        if isinstance(value, str):
            return value
        try:
            return json.dumps(value, default=str)
        except (TypeError, ValueError):
            return str(value)

    if isinstance(msg, PydanticModelResponse):
        for part in msg.parts:
            if isinstance(part, TextPart):
                if part.content:
                    turns.append(("assistant", part.content))
            elif isinstance(part, ToolCallPart):
                is_deleg = part.tool_name.startswith("delegate_to_")
                verb = "delegated to" if is_deleg else "called tool"
                turns.append(("assistant", f"[{verb} {part.tool_name}({_stringify(part.args)})]"))
    elif isinstance(msg, ModelRequest):
        for part in msg.parts:
            if isinstance(part, UserPromptPart):
                content = part.content
                turns.append(("user", content if isinstance(content, str) else _stringify(content)))
            elif isinstance(part, ToolReturnPart):
                is_deleg = part.tool_name.startswith("delegate_to_")
                label = "delegation result" if is_deleg else "tool result"
                turns.append(("tool", f"[{label} {part.tool_name}: {_stringify(part.content)}]"))
    return turns


def reconstruct_message_history(
    recent: List[Tuple[str, str]],
    summary: str = "",
    context_limit: Optional[int] = None,
) -> Optional[list]:
    """Rebuild Pydantic AI ``message_history`` from short-term tier turns.

    ``recent`` is the short-term tier's ``(role, content)`` turns, oldest first.
    ``summary`` is the rolling summary of older turns that overflowed the budget;
    it is prepended as a leading context note so overflow is represented by
    summarization rather than truncation. ``context_limit`` bounds how many recent
    turns are replayed verbatim (the summary still carries the rest). Returns
    ``None`` when there is nothing to replay.
    """
    from pydantic_ai.messages import (
        ModelRequest,
        ModelResponse as PydanticModelResponse,
        TextPart,
        UserPromptPart,
    )

    turns = list(recent)
    if context_limit and len(turns) > context_limit:
        turns = turns[-context_limit:]

    history: list = []
    if summary:
        history.append(
            ModelRequest(
                parts=[UserPromptPart(content=f"Summary of earlier conversation:\n{summary}")]
            )
        )
    for role, content in turns:
        text = content if isinstance(content, str) else str(content)
        if role == "user":
            history.append(ModelRequest(parts=[UserPromptPart(content=text)]))
        else:
            history.append(PydanticModelResponse(parts=[TextPart(content=text)]))
    return history or None
