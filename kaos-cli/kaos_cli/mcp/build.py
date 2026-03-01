"""KAOS MCP build command - builds a Docker image from FastMCP server."""

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

CMD ["fastmcp", "run", "{target}", "--transport", "streamable-http", "--host", "0.0.0.0", "--port", "8000"]
"""


def build_command(
    target: str,
    image: str,
    directory: str,
    kind_load: bool,
    push: bool,
    create_dockerfile: bool,
    platform: str | None,
) -> None:
    """Build a Docker image from a FastMCP server."""
    source_dir = Path(directory)

    if not source_dir.exists():
        typer.echo(f"Error: Directory '{directory}' does not exist", err=True)
        sys.exit(1)

    # Parse target module:object — resolve to file path for validation
    if ":" in target:
        module_part, _ = target.rsplit(":", 1)
    else:
        module_part = target

    entry_path = source_dir / f"{module_part}.py"
    if not entry_path.exists():
        typer.echo(
            f"Error: Module '{module_part}.py' not found in {directory}", err=True
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

    typer.echo("📦 Using pyproject.toml for dependencies")

    # Generate or use existing Dockerfile
    dockerfile_path = source_dir / "Dockerfile"
    generated_dockerfile = False

    if not dockerfile_path.exists() or create_dockerfile:
        dockerfile_content = DOCKERFILE_TEMPLATE.format(target=target)
        dockerfile_path.write_text(dockerfile_content)
        generated_dockerfile = True
        typer.echo("📝 Generated Dockerfile")

    # Build image
    typer.echo(f"🔨 Building image {image}...")

    build_args = ["docker", "build", "-t", image, str(source_dir)]

    if platform:
        build_args.extend(["--platform", platform])

    result = subprocess.run(build_args)

    if result.returncode != 0:
        typer.echo("Error: Docker build failed", err=True)
        sys.exit(result.returncode)

    typer.echo(f"✅ Built image {image}")

    # Load to KIND if requested
    if kind_load:
        typer.echo("📦 Loading image to KIND cluster...")
        detect = subprocess.run(
            ["kind", "get", "clusters"],
            capture_output=True,
            text=True,
        )
        clusters = [c.strip() for c in detect.stdout.strip().split("\n") if c.strip()]
        cmd = ["kind", "load", "docker-image", image]
        if len(clusters) == 1:
            cmd += ["--name", clusters[0]]
        result = subprocess.run(cmd)

        if result.returncode != 0:
            typer.echo("Error: Failed to load image to KIND", err=True)
            sys.exit(result.returncode)

        typer.echo(f"✅ Loaded {image} to KIND cluster")

    if push:
        typer.echo(f"📤 Pushing image {image}...")
        result = subprocess.run(["docker", "push", image])

        if result.returncode != 0:
            typer.echo("Error: Docker push failed", err=True)
            sys.exit(result.returncode)

        typer.echo(f"✅ Pushed {image}")

    # Clean up generated Dockerfile if requested
    if generated_dockerfile and not create_dockerfile:
        dockerfile_path.unlink()

    typer.echo(
        f"\n🎉 Build complete! Next: kaos mcp deploy <name> --image {image}"
    )
