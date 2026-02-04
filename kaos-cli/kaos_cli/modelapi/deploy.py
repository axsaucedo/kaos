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


def deploy_modelapi(
    name: str,
    mode: str,
    model: str | None,
    namespace: str | None,
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
