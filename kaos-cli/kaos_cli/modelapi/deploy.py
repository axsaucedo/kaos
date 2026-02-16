"""KAOS ModelAPI deploy command - deploy ModelAPI resources."""

import getpass
import json
import subprocess
import sys
import tempfile
from pathlib import Path
import typer


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


def _create_api_secret(
    name: str, namespace: str | None, api_key: str
) -> tuple[str, str]:
    """Create a Kubernetes secret for API key and return (secret_name, key_name)."""
    secret_name = f"kaos-{name}-api-key"
    key_name = "api-key"

    # Create secret YAML
    secret_yaml = f"""apiVersion: v1
kind: Secret
metadata:
  name: {secret_name}
type: Opaque
stringData:
  {key_name}: {api_key}
"""

    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(secret_yaml)
        tmp_path = f.name

    try:
        args = ["kubectl", "apply", "-f", tmp_path]
        if namespace:
            args.extend(["-n", namespace])
        result = subprocess.run(args, capture_output=True, text=True)
        if result.returncode != 0:
            typer.echo(f"Error creating secret: {result.stderr}", err=True)
            sys.exit(result.returncode)
        typer.echo(f"🔑 Created secret '{secret_name}'")
    finally:
        Path(tmp_path).unlink()

    return secret_name, key_name


def deploy_modelapi(
    name: str,
    mode: str,
    models: list[str] | None,
    namespace: str | None,
    provider: str | None = None,
    base_url: str | None = None,
    api_secret: str | None = None,
    env_vars: list[str] | None = None,
    wait: bool = False,
    wait_timeout: int = DEFAULT_WAIT_TIMEOUT,
    dry_run: bool = False,
) -> None:
    """Deploy a ModelAPI with specified configuration."""
    if mode.lower() == "hosted":
        if not models or len(models) == 0:
            typer.echo("Error: --model is required for Hosted mode", err=True)
            sys.exit(1)
        if len(models) > 1:
            typer.echo(
                "Warning: Hosted mode only supports one model, using first", err=True
            )
        model = models[0]
        yaml_content = f"""apiVersion: kaos.tools/v1alpha1
kind: ModelAPI
metadata:
  name: {name}
spec:
  mode: Hosted
  hostedConfig:
    model: {model}
"""
    else:
        # Proxy mode
        model_list = models if models else ["*"]
        models_json = json.dumps(model_list)
        yaml_content = f"""apiVersion: kaos.tools/v1alpha1
kind: ModelAPI
metadata:
  name: {name}
spec:
  mode: Proxy
  proxyConfig:
    models: {models_json}
"""
        # Add optional proxy config fields
        if provider:
            yaml_content = yaml_content.rstrip() + f"\n    provider: {provider}\n"
        if base_url:
            yaml_content = yaml_content.rstrip() + f"\n    apiBase: {base_url}\n"

        # Handle API secret
        if api_secret:
            if ":" in api_secret:
                secret_name, key_name = api_secret.split(":", 1)
            else:
                # Prompt for API key and create secret
                if dry_run:
                    typer.echo(
                        "Note: --api-secret without secretname:key would prompt for key",
                        err=True,
                    )
                    secret_name = f"kaos-{name}-api-key"
                    key_name = "api-key"
                else:
                    api_key = getpass.getpass("Enter API key: ")
                    secret_name, key_name = _create_api_secret(name, namespace, api_key)
            yaml_content = (
                yaml_content.rstrip()
                + f"""
    apiKey:
      valueFrom:
        secretKeyRef:
          name: {secret_name}
          key: {key_name}
"""
            )

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
