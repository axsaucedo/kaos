"""KAOS ModelAPI deploy command - deploy ModelAPI resources."""

import subprocess
import sys
import tempfile
from pathlib import Path
import typer


MODELAPI_PROXY_TEMPLATE = """apiVersion: kaos.tools/v1alpha1
kind: ModelAPI
metadata:
  name: {name}
spec:
  mode: Proxy
  proxyConfig:
    models: ["*"]
"""

MODELAPI_HOSTED_TEMPLATE = """apiVersion: kaos.tools/v1alpha1
kind: ModelAPI
metadata:
  name: {name}
spec:
  mode: Hosted
  hostedConfig:
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


def deploy_modelapi(
    name: str,
    mode: str,
    model: str | None,
    namespace: str | None,
    env_vars: list[str] | None = None,
    wait: bool = False,
    wait_timeout: int = DEFAULT_WAIT_TIMEOUT,
    dry_run: bool = False,
) -> None:
    """Deploy a ModelAPI with specified configuration."""
    if mode.lower() == "hosted":
        if not model:
            typer.echo("Error: --model is required for Hosted mode", err=True)
            sys.exit(1)
        yaml_content = MODELAPI_HOSTED_TEMPLATE.format(name=name, model=model)
    else:
        yaml_content = MODELAPI_PROXY_TEMPLATE.format(name=name)

    # Add container.env if env vars provided
    parsed_env = _parse_env_vars(env_vars)
    if parsed_env:
        yaml_content += "  container:\n"
        yaml_content += "    env:\n"
        for env_name, env_value in parsed_env:
            yaml_content += f"    - name: {env_name}\n"
            yaml_content += f'      value: "{env_value}"\n'

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
        typer.echo(f"\n✅ Deployed ModelAPI '{name}' with mode '{mode}'")

        # Wait for deployment if requested
        if wait:
            typer.echo("⏳ Waiting for deployment to be available...")
            wait_args = [
                "kubectl",
                "wait",
                f"deployment/modelapi-{name}",
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
