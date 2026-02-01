"""KAOS MCP init command - creates a FastMCP template project."""

import os
from pathlib import Path
import typer

TEMPLATE_SERVER_PY = '''"""FastMCP Server."""

from fastmcp import FastMCP

mcp = FastMCP("my-mcp-server")


@mcp.tool()
def hello(name: str) -> str:
    """Say hello to someone."""
    return f"Hello, {name}!"


@mcp.tool()
def add(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b


if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8000)
'''

TEMPLATE_PYPROJECT_TOML = """[project]
name = "my-mcp-server"
version = "0.1.0"
description = "A FastMCP server created with kaos mcp init"
requires-python = ">=3.11"
dependencies = [
    "fastmcp>=2.0.0",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["."]
"""

TEMPLATE_README_MD = """# My MCP Server

A FastMCP server created with `kaos mcp init`.

## Development

Install dependencies:

```bash
pip install -e .
```

Run locally:

```bash
python server.py
```

## Build and Deploy

Build Docker image:

```bash
kaos mcp build --name my-mcp-server
```

Deploy to Kubernetes:

```bash
kaos mcp deploy --name my-mcp-server --image my-mcp-server:latest
```
"""


def init_command(
    directory: str | None,
    force: bool,
) -> None:
    """Initialize a new FastMCP server project."""
    target_dir = Path(directory) if directory else Path.cwd()

    if not target_dir.exists():
        target_dir.mkdir(parents=True)

    files = {
        "server.py": TEMPLATE_SERVER_PY,
        "pyproject.toml": TEMPLATE_PYPROJECT_TOML,
        "README.md": TEMPLATE_README_MD,
    }

    for filename, content in files.items():
        filepath = target_dir / filename
        if filepath.exists() and not force:
            typer.echo(
                f"⚠️  Skipping {filename} (already exists, use --force to overwrite)"
            )
            continue

        filepath.write_text(content)
        typer.echo(f"✅ Created {filepath}")

    typer.echo(f"\n🎉 FastMCP project initialized in {target_dir}")
    typer.echo("\nNext steps:")
    typer.echo("  1. Edit server.py to add your tools")
    typer.echo("  2. Run locally: python server.py")
    typer.echo("  3. Build: kaos mcp build --name my-mcp")
    typer.echo("  4. Deploy: kaos mcp deploy --name my-mcp --image my-mcp:latest")
