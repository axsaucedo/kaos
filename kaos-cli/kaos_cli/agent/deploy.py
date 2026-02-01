"""KAOS Agent deploy command - deploy Agent resources."""

import subprocess
import sys
import tempfile
from pathlib import Path
import typer


AGENT_TEMPLATE = """apiVersion: kaos.tools/v1alpha1
kind: Agent
metadata:
  name: {name}
  namespace: {namespace}
spec:
  modelApiRef: {modelapi}
  systemPrompt: |
    {system_prompt}
"""


def deploy_from_yaml(file: str, namespace: str | None) -> None:
    """Deploy an Agent from YAML file."""
    args = ["kubectl", "apply", "-f", file]

    if namespace:
        args.extend(["-n", namespace])

    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode != 0:
        typer.echo(result.stderr or result.stdout, err=True)
        sys.exit(result.returncode)
    typer.echo(result.stdout)


def deploy_agent(
    name: str,
    modelapi: str,
    namespace: str,
    system_prompt: str | None,
    mcp_servers: list[str] | None,
    sub_agents: list[str] | None,
) -> None:
    """Deploy an Agent with specified configuration."""
    prompt = system_prompt or "You are a helpful AI assistant."
    yaml_content = AGENT_TEMPLATE.format(
        name=name,
        namespace=namespace,
        modelapi=modelapi,
        system_prompt=prompt.replace("\n", "\n    "),
    )

    # Add MCP servers if provided
    if mcp_servers:
        yaml_content = yaml_content.rstrip() + "\n  mcpServers:\n"
        for mcp in mcp_servers:
            yaml_content += f"  - {mcp}\n"

    # Add sub-agents if provided
    if sub_agents:
        yaml_content = yaml_content.rstrip() + "\n  subAgents:\n"
        for agent in sub_agents:
            yaml_content += f"  - {agent}\n"

    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(yaml_content)
        tmp_path = f.name

    try:
        args = ["kubectl", "apply", "-f", tmp_path]
        result = subprocess.run(args, capture_output=True, text=True)
        if result.returncode != 0:
            typer.echo(result.stderr or result.stdout, err=True)
            sys.exit(result.returncode)
        typer.echo(result.stdout)
        typer.echo(f"\n✅ Deployed Agent '{name}' with ModelAPI '{modelapi}'")
    finally:
        Path(tmp_path).unlink()
