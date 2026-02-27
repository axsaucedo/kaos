"""KAOS Agent build command - builds a Docker image from a custom agent."""

import subprocess
import sys
from pathlib import Path
import typer


DOCKERFILE_TEMPLATE = """FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir uv

# Install dependencies from pyproject.toml
COPY pyproject.toml README.md* ./
RUN uv pip install --system --no-cache-dir .

# Copy server code
COPY . .

RUN useradd -m -u 65532 agentic && chown -R agentic:agentic /app
USER agentic

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "{entry_point}:get_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
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
    """Build a Docker image from a custom Pydantic AI agent."""
    source_dir = Path(directory)

    if not source_dir.exists():
        typer.echo(f"Error: Directory '{directory}' does not exist", err=True)
        sys.exit(1)

    entry_path = source_dir / entry_point
    if not entry_path.exists():
        typer.echo(
            f"Error: Entry point '{entry_point}' not found in {directory}", err=True
        )
        sys.exit(1)

    pyproject_path = source_dir / "pyproject.toml"
    if not pyproject_path.exists():
        typer.echo(f"Error: pyproject.toml not found in {directory}", err=True)
        typer.echo(
            "Run 'kaos agent init' to create a new project with pyproject.toml",
            err=True,
        )
        sys.exit(1)

    typer.echo("📦 Using pyproject.toml for dependencies")

    dockerfile_path = source_dir / "Dockerfile"
    generated_dockerfile = False

    entry_name = entry_point.replace(".py", "")

    if not dockerfile_path.exists() or create_dockerfile:
        dockerfile_content = DOCKERFILE_TEMPLATE.format(entry_point=entry_name)
        dockerfile_path.write_text(dockerfile_content)
        generated_dockerfile = True
        typer.echo("📝 Generated Dockerfile")

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

    if kind_load:
        typer.echo("📦 Loading image to KIND cluster...")
        result = subprocess.run(["kind", "load", "docker-image", image_tag])

        if result.returncode != 0:
            typer.echo("Error: Failed to load image to KIND", err=True)
            sys.exit(result.returncode)

        typer.echo(f"✅ Loaded {image_tag} to KIND cluster")

    if generated_dockerfile and not create_dockerfile:
        dockerfile_path.unlink()

    typer.echo(
        f"\n🎉 Build complete! Next: kaos agent deploy {name} --modelapi <api> --model <model>"
    )
