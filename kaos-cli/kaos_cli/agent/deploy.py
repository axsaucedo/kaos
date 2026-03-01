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

DEFAULT_WAIT_TIMEOUT = 120


def _parse_env_vars(env_list: list[str] | None) -> list[tuple[str, str]]:
    """Parse NAME=value format env vars into list of (name, value) tuples."""
    if not env_list:
        return []
    result = []
    for env in env_list:
        if "=" in env:
            name, value = env.split("=", 1)
            result.append((name.strip(), value))
        else:
            typer.echo(
                f"Warning: Invalid env format '{env}', expected NAME=value", err=True
            )
    return result


def deploy_agent(
    name: str,
    modelapi: str,
    model: str,
    image: str | None,
    namespace: str | None,
    description: str | None,
    instructions: str | None,
    mcp_servers: list[str] | None,
    sub_agents: list[str] | None,
    mock_responses: list[str] | None,
    expose: bool,
    otel_endpoint: str | None,
    env_vars: list[str] | None = None,
    wait: bool = False,
    wait_timeout: int = DEFAULT_WAIT_TIMEOUT,
    dry_run: bool = False,
) -> None:
    """Deploy an Agent with specified configuration."""
    yaml_content = AGENT_TEMPLATE.format(
        name=name,
        modelapi=modelapi,
        model=model,
    )

    # Add config section if description, instructions or telemetry provided
    if description or instructions or otel_endpoint:
        yaml_content += "  config:\n"
        if description:
            yaml_content += f'    description: "{description}"\n'
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

    # Build container section (image + env vars)
    env_entries = []
    parsed_env = _parse_env_vars(env_vars)
    for env_name, env_value in parsed_env:
        env_entries.append((env_name, env_value))

    if mock_responses:
        mock_json = json.dumps(mock_responses)
        env_entries.append(("DEBUG_MOCK_RESPONSES", mock_json))

    has_container = image or env_entries
    if has_container:
        yaml_content += "  container:\n"
        if image:
            yaml_content += f"    image: {image}\n"
        if env_entries:
            yaml_content += "    env:\n"
            for env_name, env_value in env_entries:
                yaml_content += f"    - name: {env_name}\n"
                # Use YAML single-quoted to preserve backslashes and special chars as-is
                escaped = env_value.replace("'", "''")
                yaml_content += f"      value: '{escaped}'\n"

    # Dry run: print YAML and exit
    if dry_run:
        typer.echo(yaml_content)
        return

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

        # Wait for deployment if requested
        if wait:
            typer.echo("⏳ Waiting for deployment to be available...")
            wait_args = [
                "kubectl",
                "wait",
                f"deployment/agent-{name}",
                "--for=condition=available",
                f"--timeout={wait_timeout}s",
            ]
            if namespace:
                wait_args.extend(["-n", namespace])
            wait_result = subprocess.run(wait_args, capture_output=True, text=True)
            if wait_result.returncode != 0:
                typer.echo(wait_result.stderr or wait_result.stdout, err=True)
                sys.exit(wait_result.returncode)
            typer.echo("✅ Deployment is available")
    finally:
        Path(tmp_path).unlink()
