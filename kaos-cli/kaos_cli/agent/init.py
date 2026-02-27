"""KAOS Agent init command - creates a custom Pydantic AI agent project."""

from pathlib import Path
import typer


TEMPLATE_SERVER_PY = '''"""Custom Pydantic AI Agent."""

from pydantic_ai import Agent

agent = Agent(
    model="test",  # Overridden by KAOS env vars at runtime
    instructions="You are a helpful assistant.",
    name="my-agent",
    defer_model_check=True,
)


@agent.tool_plain
def hello(name: str) -> str:
    """Say hello to someone.

    Args:
        name: The person to greet.

    Returns:
        A greeting string.
    """
    return f"Hello, {name}!"


@agent.tool_plain
def add(a: float, b: float) -> str:
    """Add two numbers.

    Args:
        a: First number.
        b: Second number.

    Returns:
        The sum as a string.
    """
    return str(a + b)
'''

TEMPLATE_PYPROJECT_TOML = """[project]
name = "my-agent"
version = "0.1.0"
description = "A custom Pydantic AI agent created with kaos agent init"
requires-python = ">=3.12"
dependencies = [
    "pydantic-ai[openai]",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["."]
"""

TEMPLATE_README_MD = """# My Custom Agent

A Pydantic AI agent created with `kaos agent init`.

## Development

Install dependencies:

```bash
pip install -e .
```

Run locally:

```bash
AGENT_NAME=my-agent MODEL_API_URL=http://localhost:11434 MODEL_NAME=llama3.2 \\
  pais run
```

Or with kaos CLI:

```bash
kaos agent run
```

## Build and Deploy

Build Docker image:

```bash
kaos agent build --name my-agent
```

Deploy to Kubernetes:

```bash
kaos agent deploy my-agent --modelapi my-api --model llama3.2
```
"""


def init_command(
    directory: str | None,
    force: bool,
) -> None:
    """Initialize a new custom Pydantic AI agent project."""
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

    typer.echo(f"\n🎉 Custom agent project initialized in {target_dir}")
    typer.echo("\nNext steps:")
    typer.echo("  1. Edit server.py to add your tools")
    typer.echo("  2. Run locally: AGENT_NAME=my-agent MODEL_API_URL=... pais run")
    typer.echo("  3. Build: kaos agent build --name my-agent")
    typer.echo("  4. Deploy: kaos agent deploy my-agent --modelapi my-api --model llama3.2")
