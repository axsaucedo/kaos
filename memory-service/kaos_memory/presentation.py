"""Assemble recalled memory into a deterministic structured block for injection.

The block is plain text the runtime injects into the agent's system context (not as
fabricated prior turns). It is always-on and cheap, rendering whatever context is
available — long-term facts, a rolling summary, recent verbatim turns — and degrades
cleanly to an empty string when nothing is recalled.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple


def _fact_text(fact: Dict[str, Any]) -> str:
    """Extract the human-readable text from a Mem0 result dict."""
    return fact.get("memory") or fact.get("text") or ""


def assemble_block(
    facts: List[Dict[str, Any]],
    summary: str,
    recent: List[Tuple[str, str]],
) -> str:
    """Render the structured memory block. Empty inputs yield an empty block."""
    sections: List[str] = []

    fact_lines = [f"- {_fact_text(f)}" for f in facts if _fact_text(f)]
    if fact_lines:
        sections.append("## Relevant memory\n" + "\n".join(fact_lines))

    if summary.strip():
        sections.append("## Conversation summary\n" + summary.strip())

    if recent:
        turns = "\n".join(f"{role}: {content}" for role, content in recent)
        sections.append("## Recent turns\n" + turns)

    return "\n\n".join(sections)
