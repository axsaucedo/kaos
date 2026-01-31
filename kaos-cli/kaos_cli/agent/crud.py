"""KAOS Agent CRUD commands using shared utilities."""

from kaos_cli.utils.crud import (
    list_resources,
    get_resource,
    logs_resource,
    delete_resource,
)

RESOURCE_TYPE = "agent"


def list_command(namespace: str | None, output: str) -> None:
    """List Agent resources."""
    list_resources(RESOURCE_TYPE, namespace, output)


def get_command(name: str, namespace: str, output: str) -> None:
    """Get a specific Agent."""
    get_resource(RESOURCE_TYPE, name, namespace, output)


def logs_command(name: str, namespace: str, follow: bool, tail: int | None) -> None:
    """View logs from an Agent pod."""
    logs_resource(RESOURCE_TYPE, name, namespace, follow, tail)


def delete_command(name: str, namespace: str, force: bool) -> None:
    """Delete an Agent."""
    delete_resource(RESOURCE_TYPE, name, namespace, force)
