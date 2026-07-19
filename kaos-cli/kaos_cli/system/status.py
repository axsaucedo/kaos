"""KAOS system component status."""

import json
import subprocess

import typer


COMPONENTS = (
    ("gateway", ("envoy-gateway",)),
    ("login service", ("keycloak",)),
    ("access-control", ("kaos-pdp", "access-control")),
    ("sync service", ("kaos-operator", "controller-manager")),
)


def _find_deployment(items: list[dict], names: tuple[str, ...]) -> dict | None:
    for item in items:
        name = item.get("metadata", {}).get("name", "").lower()
        if any(part in name for part in names):
            return item
    return None


def status_command(namespace: str) -> None:
    """Print readiness for the authorization path's four components."""
    try:
        result = subprocess.run(
            ["kubectl", "get", "deployment", "--all-namespaces", "-o", "json"],
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        typer.echo("Error: kubectl not found", err=True)
        raise typer.Exit(1)
    if result.returncode != 0:
        typer.echo(result.stderr or "Error: unable to read system status", err=True)
        raise typer.Exit(result.returncode)

    items = json.loads(result.stdout or "{}").get("items", [])
    for label, names in COMPONENTS:
        deployment = _find_deployment(items, names)
        if deployment is None:
            state = "not installed"
            detail = ""
        else:
            desired = deployment.get("spec", {}).get("replicas", 1)
            ready = deployment.get("status", {}).get("readyReplicas", 0)
            state = "ready" if desired > 0 and ready >= desired else "not ready"
            detail = ""
            if label == "access-control":
                detail = f"   ({ready}/{desired} replicas)"
            elif label == "login service" and "keycloak" in deployment["metadata"]["name"]:
                detail = "   (keycloak)"
        typer.echo(f"{label:<18}{state}{detail}")
