"""KAOS MCP build command - builds a Docker image from FastMCP server."""

import os
import subprocess
import sys
from pathlib import Path
import typer


DOCKERFILE_TEMPLATE = """FROM python:3.12-slim

WORKDIR /app

# Install dependencies from pyproject.toml
COPY pyproject.toml README.md* ./
RUN pip install --no-cache-dir .

# Copy server code
COPY . .

EXPOSE 8000

CMD ["fastmcp", "run", "{entry_point}:mcp", "--transport", "streamable-http", "--host", "0.0.0.0", "--port", "8000"]
"""


def build_command(
    name: str,
    tag: str,
    directory: str,
    entry_point: str,
    kind_load: bool,
    create_dockerfile: bool,
    platform: str | None,
) -> None:
    """Build a Docker image from a FastMCP server."""
    source_dir = Path(directory)

    if not source_dir.exists():
        typer.echo(f"Error: Directory '{directory}' does not exist", err=True)
        sys.exit(1)

    # Check for entry point
    entry_path = source_dir / entry_point
    if not entry_path.exists():
        typer.echo(
            f"Error: Entry point '{entry_point}' not found in {directory}", err=True
        )
        sys.exit(1)

    # Check for pyproject.toml (required)
    pyproject_path = source_dir / "pyproject.toml"
    if not pyproject_path.exists():
        typer.echo(f"Error: pyproject.toml not found in {directory}", err=True)
        typer.echo(
            "Run 'kaos mcp init' to create a new project with pyproject.toml", err=True
        )
        sys.exit(1)

    typer.echo(f"📦 Using pyproject.toml for dependencies")

    # Generate or use existing Dockerfile
    dockerfile_path = source_dir / "Dockerfile"
    generated_dockerfile = False

    # Remove .py extension for fastmcp run command
    entry_name = entry_point.replace(".py", "")

    if not dockerfile_path.exists() or create_dockerfile:
        dockerfile_content = DOCKERFILE_TEMPLATE.format(entry_point=entry_name)
        dockerfile_path.write_text(dockerfile_content)
        generated_dockerfile = True
        typer.echo(f"📝 Generated Dockerfile")

    # Build image
    image_tag = f"{name}:{tag}"
    typer.echo(f"🔨 Building image {image_tag}...")

    build_args = ["docker", "build", "-t", image_tag, str(source_dir)]

    if platform:
        build_args.extend(["--platform", platform])

    result = subprocess.run(build_args)

    if result.returncode != 0:
        typer.echo("Error: Docker build failed", err=True)
        sys.exit(result.returncode)

    typer.echo(f"✅ Built image {image_tag}")

    # Load to KIND if requested
    if kind_load:
        typer.echo(f"📦 Loading image to KIND cluster...")
        result = subprocess.run(["kind", "load", "docker-image", image_tag])

        if result.returncode != 0:
            typer.echo("Error: Failed to load image to KIND", err=True)
            sys.exit(result.returncode)

        typer.echo(f"✅ Loaded {image_tag} to KIND cluster")

    # Clean up generated Dockerfile if requested
    if generated_dockerfile and not create_dockerfile:
        dockerfile_path.unlink()

    typer.echo(
        f"\n🎉 Build complete! Next: kaos mcp deploy --name {name} --image {image_tag}"
    )
