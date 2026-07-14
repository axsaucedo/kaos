"""AccessGrant generation and kubectl operations."""

import subprocess
from typing import Any

import typer
import yaml

from kaos_cli.config import load_config


RESOURCE_KINDS = {
    "agent": "Agent",
    "mcp": "MCPServer",
    "mcpserver": "MCPServer",
    "modelapi": "ModelAPI",
    "memory": "MemoryStore",
    "memorystore": "MemoryStore",
}


class _IndentDumper(yaml.SafeDumper):
    """Indent sequences beneath mapping keys for readable CLI YAML."""

    def increase_indent(self, flow=False, indentless=False):
        return super().increase_indent(flow, False)


def _resources(values: list[str]) -> list[dict[str, str]]:
    result = []
    for value in values:
        for item in value.split(","):
            try:
                kind, name = item.strip().split("/", 1)
                result.append({"kind": RESOURCE_KINDS[kind.lower()], "name": name})
            except (ValueError, KeyError):
                raise ValueError(f"Invalid resource '{item}'; expected kind/name")
    if not result:
        raise ValueError("At least one --resource is required")
    return result


def build_access_grant(
    *,
    group: str | None,
    user: str | None,
    agent: str | None,
    resources: list[str],
    name: str | None = None,
    namespace: str | None = None,
) -> dict[str, Any]:
    """Build an AccessGrant object from CLI-shaped inputs."""
    subjects = [("Group", group), ("User", user), ("Agent", agent)]
    selected = [(kind, value) for kind, value in subjects if value]
    if len(selected) != 1:
        raise ValueError("Set exactly one of --group, --user, or --agent")
    resource_refs = _resources(resources)
    subject_kind, subject_name = selected[0]
    if name is None:
        targets = "-and-".join(item["name"] for item in resource_refs)
        name = f"{subject_name}-to-{targets}".lower().replace("_", "-")
    metadata = {"name": name}
    if namespace:
        metadata["namespace"] = namespace
    return {
        "apiVersion": "kaos.tools/v1alpha1",
        "kind": "AccessGrant",
        "metadata": metadata,
        "spec": {
            "subjects": [{"kind": subject_kind, "name": subject_name}],
            "resources": resource_refs,
        },
    }


def create_grant_command(
    group: str | None,
    user: str | None,
    agent: str | None,
    resources: list[str],
    name: str | None,
    namespace: str | None,
    dry_run: bool,
) -> None:
    effective_namespace = namespace or load_config().get("namespace") or None
    try:
        grant = build_access_grant(
            group=group, user=user, agent=agent, resources=resources,
            name=name, namespace=namespace,
        )
    except ValueError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1)
    content = yaml.dump(grant, Dumper=_IndentDumper, sort_keys=False)
    if dry_run:
        typer.echo(content.rstrip())
        return
    args = ["kubectl", "apply", "-f", "-"]
    if effective_namespace:
        args.extend(["-n", effective_namespace])
    result = subprocess.run(args, input=content, capture_output=True, text=True)
    if result.returncode != 0:
        typer.echo(result.stderr or result.stdout, err=True)
        raise typer.Exit(result.returncode)
    typer.echo(f"✓ created AccessGrant {grant['metadata']['name']}")


def list_grants_command(namespace: str | None) -> None:
    args = [
        "kubectl", "get", "accessgrants",
        "-o", "custom-columns=NAME:.metadata.name,SUBJECTS:.spec.subjects[*].name,RESOURCES:.spec.resources[*].name",
    ]
    namespace = namespace or load_config().get("namespace")
    if namespace:
        args.extend(["-n", namespace])
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode != 0:
        typer.echo(result.stderr or result.stdout, err=True)
        raise typer.Exit(result.returncode)
    typer.echo(result.stdout.rstrip())


def delete_grant_command(name: str, namespace: str | None) -> None:
    args = ["kubectl", "delete", "accessgrant", name]
    namespace = namespace or load_config().get("namespace")
    if namespace:
        args.extend(["-n", namespace])
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode != 0:
        typer.echo(result.stderr or result.stdout, err=True)
        raise typer.Exit(result.returncode)
    typer.echo(f"✓ deleted AccessGrant {name}")
