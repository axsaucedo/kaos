"""KAOS Agent build command - builds a Docker image from a custom agent."""

import subprocess
import sys
from pathlib import Path
import typer


def _get_default_base_image() -> str:
    """Get the default base image using the installed kaos-cli version."""
    try:
        from importlib.metadata import version

        ver = version("kaos-cli")
        if "dev" in ver:
            return "axsauze/kaos-agent:latest"
        return f"axsauze/kaos-agent:{ver}"
    except Exception:
        return "axsauze/kaos-agent:latest"


DOCKERFILE_TEMPLATE = """FROM {base_image}

WORKDIR /app

ENV PATH="/home/agentic/.local/bin:$PATH"

# Install custom agent and its dependencies
COPY pyproject.toml README.md* ./
RUN pip install --no-cache-dir . 2>/dev/null || true

# Ensure pais CLI is available (needed for CMD)
RUN pip install --no-cache-dir "pydantic-ai-server[cli]" 2>/dev/null || true

# Copy custom agent code
COPY . .

CMD ["pais", "run", "{target}"]
"""


def build_command(
    target: str,
    image: str,
    directory: str,
    kind_load: bool,
    push: bool,
    create_dockerfile: bool,
    platform: str | None,
    base_image: str | None,
) -> None:
    """Build a Docker image from a custom Pydantic AI agent."""
    source_dir = Path(directory)

    if not source_dir.exists():
        typer.echo(f"Error: Directory '{directory}' does not exist", err=True)
        sys.exit(1)

    # Parse target module:object — resolve to file path for validation
    if ":" in target:
        module_part, attr_part = target.rsplit(":", 1)
    else:
        module_part = target
        attr_part = None

    entry_path = source_dir / f"{module_part}.py"
    if not entry_path.exists():
        typer.echo(
            f"Error: Module '{module_part}.py' not found in {directory}", err=True
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

    resolved_base = base_image or _get_default_base_image()

    if not dockerfile_path.exists() or create_dockerfile:
        # Convert module:object target to file.py:object for pais run
        run_target = f"{module_part}.py:{attr_part}" if attr_part else f"{module_part}.py"
        dockerfile_content = DOCKERFILE_TEMPLATE.format(
            target=run_target, base_image=resolved_base
        )
        dockerfile_path.write_text(dockerfile_content)
        generated_dockerfile = True
        typer.echo(f"📝 Generated Dockerfile (base: {resolved_base})")

    typer.echo(f"🔨 Building image {image}...")

    build_args = ["docker", "build", "-t", image, str(source_dir)]

    if platform:
        build_args.extend(["--platform", platform])

    result = subprocess.run(build_args)

    if result.returncode != 0:
        typer.echo("Error: Docker build failed", err=True)
        sys.exit(result.returncode)

    typer.echo(f"✅ Built image {image}")

    if kind_load:
        typer.echo("📦 Loading image to KIND cluster...")
        # Auto-detect KIND cluster name
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

    if generated_dockerfile and not create_dockerfile:
        dockerfile_path.unlink()

    typer.echo(
        f"\n🎉 Build complete! Next: kaos agent deploy <name> --image {image} --modelapi <api> --model <model>"
    )
