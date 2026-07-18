"""Central MemoryStore administration commands."""

import json
import subprocess
from enum import Enum
from typing import Any
from urllib.parse import urlparse

import httpx
import typer

from kaos_cli.utils.port_forward import PortForwardError, port_forward


class ScopeChoice(str, Enum):
    SESSION = "session"
    AGENT = "agent"
    USER = "user"
    GROUP = "group"


class MemoryCLIError(RuntimeError):
    """A user-facing memory command error."""


def build_scope(
    level: str,
    namespace: str,
    *,
    session: str | None = None,
    agent: str | None = None,
    user: str | None = None,
) -> dict[str, str]:
    """Build the exact kaos-memory Scope wire shape from CLI owner flags."""
    owners = {"session": session, "agent": agent, "user": user}
    if level not in {choice.value for choice in ScopeChoice}:
        raise ValueError(f"unknown memory scope: {level}")

    supplied = [name for name, value in owners.items() if value is not None]
    if level == "group":
        if supplied:
            raise ValueError("group scope does not take an owner flag")
        return {"level": "group"}

    if supplied != [level]:
        flag = f"--{level}"
        if not supplied:
            raise ValueError(f"{flag} is required for {level} scope")
        raise ValueError(f"{flag} is the only owner flag allowed for {level} scope")

    value = owners[level]
    if value is None or not value.strip():
        raise ValueError(f"--{level} requires a non-empty value")
    value = value.strip()
    if level == "session":
        return {"level": level, "session_id": value}
    if level == "agent":
        return {
            "level": level,
            "agent_client_id": f"kaos://agent/{namespace}/{value}",
        }
    return {"level": level, "principal": value}


def _effective_namespace(namespace: str | None) -> str:
    if namespace:
        return namespace
    result = subprocess.run(
        [
            "kubectl",
            "config",
            "view",
            "--minify",
            "--output",
            "jsonpath={..namespace}",
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip()
    return "default"


def _memory_stores(namespace: str) -> list[dict[str, Any]]:
    result = subprocess.run(
        [
            "kubectl",
            "get",
            "memorystores.kaos.tools",
            "-n",
            namespace,
            "-o",
            "json",
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise MemoryCLIError(result.stderr.strip() or "failed to list MemoryStores")
    try:
        return list(json.loads(result.stdout).get("items", []))
    except (json.JSONDecodeError, AttributeError) as exc:
        raise MemoryCLIError("kubectl returned invalid MemoryStore data") from exc


def resolve_memory_store(store: str | None, namespace: str) -> tuple[str, str, int]:
    """Resolve a MemoryStore name to a port-forward Service target and port."""
    stores = _memory_stores(namespace)
    if store:
        matches = [
            item for item in stores if item.get("metadata", {}).get("name") == store
        ]
        if not matches:
            raise MemoryCLIError(
                f"MemoryStore '{store}' not found in namespace '{namespace}'"
            )
        selected = matches[0]
    elif len(stores) == 1:
        selected = stores[0]
        store = selected.get("metadata", {}).get("name")
    elif not stores:
        raise MemoryCLIError(f"No MemoryStore found in namespace '{namespace}'")
    else:
        raise MemoryCLIError(
            f"--store is required because namespace '{namespace}' has multiple MemoryStores"
        )

    if not store:
        raise MemoryCLIError("MemoryStore has no metadata.name")
    endpoint = selected.get("status", {}).get("endpoint", "")
    if not endpoint:
        return store, f"svc/memorystore-{store}", 8080

    parsed = urlparse(endpoint if "://" in endpoint else f"http://{endpoint}")
    if not parsed.hostname:
        return store, f"svc/memorystore-{store}", 8080
    return store, f"svc/{parsed.hostname.split('.')[0]}", parsed.port or 8080


def _request(
    method: str,
    path: str,
    payload: dict[str, Any],
    target: str,
    remote_port: int,
    namespace: str,
) -> dict[str, Any]:
    try:
        with port_forward(target, remote_port, namespace, "/healthz") as base_url:
            response = httpx.request(
                method, f"{base_url}{path}", json=payload, timeout=30.0
            )
    except PortForwardError as exc:
        raise MemoryCLIError(f"port-forward failed: {exc}") from exc
    except httpx.HTTPError as exc:
        raise MemoryCLIError(f"memory service request failed: {exc}") from exc

    if response.status_code >= 400:
        try:
            detail = response.json().get("error") or response.json().get("detail")
        except (json.JSONDecodeError, AttributeError):
            detail = response.text
        raise MemoryCLIError(f"HTTP {response.status_code}: {detail or response.text}")
    try:
        return response.json()
    except json.JSONDecodeError as exc:
        raise MemoryCLIError("memory service returned invalid JSON") from exc


def _print_recall(data: dict[str, Any], scope: dict[str, str]) -> None:
    typer.echo(f"Scope: {json.dumps(scope, sort_keys=True)}")
    facts = data.get("facts", [])
    typer.echo(f"Long-term records: {len(facts)}")
    for fact in facts:
        typer.echo(f"  - {fact.get('memory', json.dumps(fact, sort_keys=True))}")

    summary = (data.get("medium_term") or {}).get("summary", "")
    recent = (data.get("short_term") or {}).get("recent", [])
    if summary:
        typer.echo(f"Medium-term summary: {summary}")
    if recent:
        typer.echo("Short-term turns:")
        for role, content in recent:
            typer.echo(f"  [{role}] {content}")
    if data.get("degraded"):
        typer.echo("Warning: long-term memory is degraded", err=True)


def _scope_from_options(
    level: ScopeChoice,
    namespace: str,
    session: str | None,
    agent: str | None,
    user: str | None,
) -> dict[str, str]:
    try:
        return build_scope(
            level.value,
            namespace,
            session=session,
            agent=agent,
            user=user,
        )
    except ValueError as exc:
        raise MemoryCLIError(str(exc)) from exc


app = typer.Typer(help="Inspect and erase central memory stores.", no_args_is_help=True)


@app.command(name="recall")
def recall_memory(
    store: str = typer.Option(None, "--store", help="MemoryStore name."),
    scope: ScopeChoice = typer.Option(..., "--scope", help="Memory scope level."),
    session: str = typer.Option(None, "--session", help="Session owner ID."),
    agent: str = typer.Option(None, "--agent", help="Agent owner name."),
    user: str = typer.Option(None, "--user", help="User principal owner."),
    query: str = typer.Option(None, "--query", help="Semantic recall query."),
    all_records: bool = typer.Option(False, "--all", help="List every scoped record."),
    short_term: bool = typer.Option(
        False, "--short-term", help="Include conversational memory tiers."
    ),
    top_k: int = typer.Option(10, "--top-k", min=1, help="Maximum semantic results."),
    namespace: str = typer.Option(
        None, "--namespace", "-n", help="Kubernetes namespace."
    ),
    output_json: bool = typer.Option(False, "--json", help="Output JSON."),
) -> None:
    """Recall semantic or complete memory at one scope."""
    try:
        if (query is None and not all_records) or (query is not None and all_records):
            raise MemoryCLIError("exactly one of --query or --all is required")
        if query is not None and not query.strip():
            raise MemoryCLIError("--query requires non-empty text")

        # Validate owner flags before consulting Kubernetes for the default namespace.
        _scope_from_options(scope, namespace or "default", session, agent, user)
        resolved_namespace = _effective_namespace(namespace)
        resolved_scope = _scope_from_options(
            scope, resolved_namespace, session, agent, user
        )
        store_name, target, remote_port = resolve_memory_store(
            store, resolved_namespace
        )

        payload: dict[str, Any] = {
            "scope": resolved_scope,
            "include_short_term": short_term,
        }
        if all_records:
            path = "/v1/list"
        else:
            path = "/v1/recall"
            payload.update({"query": query, "top_k": top_k})
        data = _request("POST", path, payload, target, remote_port, resolved_namespace)

        if output_json:
            typer.echo(json.dumps(data, indent=2))
        else:
            typer.echo(f"MemoryStore: {store_name}")
            _print_recall(data, resolved_scope)
    except MemoryCLIError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1)


@app.command(name="forget")
def forget_memory(
    store: str = typer.Option(None, "--store", help="MemoryStore name."),
    scope: ScopeChoice = typer.Option(..., "--scope", help="Memory scope level."),
    session: str = typer.Option(None, "--session", help="Session owner ID."),
    agent: str = typer.Option(None, "--agent", help="Agent owner name."),
    user: str = typer.Option(None, "--user", help="User principal owner."),
    namespace: str = typer.Option(
        None, "--namespace", "-n", help="Kubernetes namespace."
    ),
    yes: bool = typer.Option(False, "--yes", help="Skip the confirmation prompt."),
) -> None:
    """Erase all long- and conversational memory at one scope."""
    try:
        _scope_from_options(scope, namespace or "default", session, agent, user)
        resolved_namespace = _effective_namespace(namespace)
        resolved_scope = _scope_from_options(
            scope, resolved_namespace, session, agent, user
        )
        store_name, target, remote_port = resolve_memory_store(
            store, resolved_namespace
        )

        scope_text = json.dumps(resolved_scope, sort_keys=True)
        typer.echo(f"MemoryStore: {store_name}")
        typer.echo(f"Resolved scope: {scope_text}")
        typer.echo(
            "Will erase all matching long-term records and conversational memory."
        )
        if not yes and not typer.confirm(
            f"Erase all memory at scope {scope_text}?", default=False
        ):
            typer.echo("Aborted.")
            return

        data = _request(
            "POST",
            "/v1/forget",
            {"scope": resolved_scope},
            target,
            remote_port,
            resolved_namespace,
        )
        result = {
            "forgotten": bool(data.get("forgotten", False)),
            "degraded": bool(data.get("degraded", False)),
        }
        typer.echo(json.dumps(result))
        if not result["forgotten"] or result["degraded"]:
            raise typer.Exit(1)
    except MemoryCLIError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1)
