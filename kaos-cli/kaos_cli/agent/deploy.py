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
spec:
  modelAPI: {modelapi}
  model: {model}
"""


def deploy_agent(
    name: str,
    modelapi: str,
    model: str,
    namespace: str | None,
    instructions: str | None,
    mcp_servers: list[str] | None,
    sub_agents: list[str] | None,
) -> None:
    """Deploy an Agent with specified configuration."""
    yaml_content = AGENT_TEMPLATE.format(
        name=name,
        modelapi=modelapi,
        model=model,
    )

    # Add config section if instructions provided
    if instructions:
        yaml_content += f"""  config:
    instructions: |
      {instructions.replace(chr(10), chr(10) + '      ')}
"""

    # Add MCP servers if provided
    if mcp_servers:
        yaml_content += "  mcpServers:\n"
        for mcp in mcp_servers:
            yaml_content += f"  - {mcp}\n"

    # Add sub-agents via agentNetwork.access if provided
    if sub_agents:
        yaml_content += "  agentNetwork:\n    access:\n"
        for agent in sub_agents:
            yaml_content += f"    - {agent}\n"

    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(yaml_content)
        tmp_path = f.name

    try:
        args = ["kubectl", "apply", "-f", tmp_path]
        if namespace:
            args.extend(["-n", namespace])
        result = subprocess.run(args, capture_output=True, text=True)
        if result.returncode != 0:
            typer.echo(result.stderr or result.stdout, err=True)
            sys.exit(result.returncode)
        typer.echo(result.stdout)
        typer.echo(f"\n✅ Deployed Agent '{name}' with ModelAPI '{modelapi}'")
    finally:
        Path(tmp_path).unlink()
