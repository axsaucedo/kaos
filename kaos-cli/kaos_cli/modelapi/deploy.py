"""KAOS ModelAPI deploy command - deploy ModelAPI resources."""

import subprocess
import sys
import tempfile
from pathlib import Path
import typer


MODELAPI_LITELLM_TEMPLATE = """apiVersion: kaos.tools/v1alpha1
kind: ModelAPI
metadata:
  name: {name}
  namespace: {namespace}
spec:
  backend: litellm
  model: {model}
"""

MODELAPI_OLLAMA_TEMPLATE = """apiVersion: kaos.tools/v1alpha1
kind: ModelAPI
metadata:
  name: {name}
  namespace: {namespace}
spec:
  backend: ollama
  model: {model}
"""


def deploy_from_yaml(file: str, namespace: str | None) -> None:
    """Deploy a ModelAPI from YAML file."""
    args = ["kubectl", "apply", "-f", file]

    if namespace:
        args.extend(["-n", namespace])

    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode != 0:
        typer.echo(result.stderr or result.stdout, err=True)
        sys.exit(result.returncode)
    typer.echo(result.stdout)


def deploy_modelapi(
    name: str,
    backend: str,
    model: str,
    namespace: str,
) -> None:
    """Deploy a ModelAPI with specified configuration."""
    if backend == "ollama":
        yaml_content = MODELAPI_OLLAMA_TEMPLATE.format(
            name=name,
            namespace=namespace,
            model=model,
        )
    else:
        yaml_content = MODELAPI_LITELLM_TEMPLATE.format(
            name=name,
            namespace=namespace,
            model=model,
        )

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
        typer.echo(f"\n✅ Deployed ModelAPI '{name}' with backend '{backend}'")
    finally:
        Path(tmp_path).unlink()
