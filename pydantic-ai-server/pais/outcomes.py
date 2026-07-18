"""Interpretation of KAOS-gateway access outcomes for the agent runtime.

A KAOS-secured gateway stamps enforcement decisions onto responses (see
``kaos_identity.instrument_httpx``), which the runtime raises as typed :class:`kaos_identity.AccessDenied`
/ :class:`kaos_identity.ReauthenticationRequired` on the instrumented outbound path. These
helpers let the synchronous chat/A2A path and the autonomous loop interpret those
outcomes consistently: find an outcome in a (possibly wrapped) exception, render a
user-facing message, and build a structured event payload. The runtime never
blocks, retries, or grants access in response — it only reports the outcome.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

import kaos_identity


def find_access_outcome(exc: BaseException) -> Optional["kaos_identity.AccessDenied"]:
    """Walk an exception's cause/context chain for a gateway access outcome.

    A gateway denial may be wrapped by the agent framework (e.g. surfaced as a tool
    error) before it reaches the runtime, so the whole chain is inspected. Returns
    the :class:`kaos_identity.AccessDenied` (or its :class:`kaos_identity.ReauthenticationRequired`
    subclass) when present, else ``None``.
    """
    seen: set[int] = set()
    cur: Optional[BaseException] = exc
    while cur is not None and id(cur) not in seen:
        if isinstance(cur, kaos_identity.AccessDenied):
            return cur
        seen.add(id(cur))
        cur = cur.__cause__ or cur.__context__
    return None


def format_access_outcome(outcome: "kaos_identity.AccessDenied") -> str:
    """Render a gateway access outcome as a non-blocking, user-facing message.

    Surfaces the denied resource and machine reason; when the denial is recoverable
    by user re-authentication it includes the re-auth URL. It never blocks, retries,
    or grants access — it only reports what human action (if any) is required.
    """
    decision = outcome.decision
    resource = decision.resource or "the requested resource"
    reason = decision.reason or "access denied"
    if isinstance(outcome, kaos_identity.ReauthenticationRequired) and outcome.reauth_url:
        return (
            f"Access to {resource} requires re-authentication ({reason}). "
            f"Please reconnect at {outcome.reauth_url} and try again."
        )
    return (
        f"Access to {resource} was denied ({reason}). An administrator must approve "
        "this access grant before the action can proceed."
    )


def access_event_data(outcome: "kaos_identity.AccessDenied", *, action: str = "") -> Dict[str, Any]:
    """Build a structured ``user_action_required`` event payload for a task.

    Captures the machine reason, the denied resource, and the re-auth URL when the
    outcome is recoverable, so an operator or API can see exactly what human action
    is needed.
    """
    decision = outcome.decision
    data: Dict[str, Any] = {
        "reason": decision.reason or "access_denied",
        "resource": decision.resource or "",
        "message": format_access_outcome(outcome),
    }
    if action:
        data["action"] = action
    reauth_url = getattr(outcome, "reauth_url", None)
    if reauth_url:
        data["reauth_url"] = reauth_url
    return data
