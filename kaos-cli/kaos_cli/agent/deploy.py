"""KAOS Agent deploy command - deploy Agent resources."""

import json
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
    mock_responses: list[str] | None,
    expose: bool,
    otel_endpoint: str | None,
) -> None:
    """Deploy an Agent with specified configuration."""
    yaml_content = AGENT_TEMPLATE.format(
        name=name,
        modelapi=modelapi,
        model=model,
    )

    # Add config section if instructions or telemetry provided
    if instructions or otel_endpoint:
        yaml_content += "  config:\n"
        if instructions:
            yaml_content += f"    instructions: |\n      {instructions.replace(chr(10), chr(10) + '      ')}\n"
        if otel_endpoint:
            yaml_content += f"""    telemetry:
      enabled: true
      endpoint: "{otel_endpoint}"
"""

    # Add MCP servers if provided
    if mcp_servers:
        yaml_content += "  mcpServers:\n"
        for mcp in mcp_servers:
            yaml_content += f"  - {mcp}\n"

    # Build agentNetwork section
    has_agent_network = expose or sub_agents
    if has_agent_network:
        yaml_content += "  agentNetwork:\n"
        if expose:
            yaml_content += "    expose: true\n"
        if sub_agents:
            yaml_content += "    access:\n"
            for agent in sub_agents:
                yaml_content += f"    - {agent}\n"

    # Add mock responses as container env if provided
    if mock_responses:
        mock_json = json.dumps(mock_responses)
        mock_json = mock_json.replace("'", "''")
        yaml_content += f"""  container:
    env:
    - name: DEBUG_MOCK_RESPONSES
      value: '{mock_json}'
"""

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
