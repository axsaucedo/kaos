"""KAOS MCP server CRUD commands using shared utilities."""

from kaos_cli.utils.crud import (
    list_resources,
    get_resource,
    logs_resource,
    delete_resource,
)

RESOURCE_TYPE = "mcpserver"


def list_command(namespace: str | None, output: str) -> None:
    """List MCPServer resources."""
    list_resources(RESOURCE_TYPE, namespace, output)


def get_command(name: str, namespace: str, output: str) -> None:
    """Get a specific MCPServer."""
    get_resource(RESOURCE_TYPE, name, namespace, output)


def logs_command(name: str, namespace: str, follow: bool, tail: int | None) -> None:
    """View logs from an MCPServer pod."""
    logs_resource(RESOURCE_TYPE, name, namespace, follow, tail)


def delete_command(name: str, namespace: str, force: bool) -> None:
    """Delete an MCPServer."""
    delete_resource(RESOURCE_TYPE, name, namespace, force)
