"""KAOS ModelAPI CRUD commands using shared utilities."""

from kaos_cli.utils.crud import (
    list_resources,
    get_resource,
    logs_resource,
    delete_resource,
)

RESOURCE_TYPE = "modelapi"


def list_command(namespace: str | None, output: str) -> None:
    """List ModelAPI resources."""
    list_resources(RESOURCE_TYPE, namespace, output)


def get_command(name: str, namespace: str, output: str) -> None:
    """Get a specific ModelAPI."""
    get_resource(RESOURCE_TYPE, name, namespace, output)


def logs_command(name: str, namespace: str, follow: bool, tail: int | None) -> None:
    """View logs from a ModelAPI pod."""
    logs_resource(RESOURCE_TYPE, name, namespace, follow, tail)


def delete_command(name: str, namespace: str, force: bool) -> None:
    """Delete a ModelAPI."""
    delete_resource(RESOURCE_TYPE, name, namespace, force)
