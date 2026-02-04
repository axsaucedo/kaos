"""KAOS MCP deploy command - deploy MCPServer resources."""

import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path
import typer

try:
    import tomllib
except ImportError:
    import tomli as tomllib


CUSTOM_RUNTIME_TEMPLATE = """apiVersion: kaos.tools/v1alpha1
kind: MCPServer
metadata:
  name: {name}
spec:
  runtime: custom
  container:
    image: {image}
    ports:
    - containerPort: 8000
      name: http
"""

DEFAULT_WAIT_TIMEOUT = 120


def read_project_name(directory: str = ".") -> str | None:
    """Read project name from pyproject.toml if available."""
    pyproject_path = Path(directory) / "pyproject.toml"
    if pyproject_path.exists():
        try:
            with open(pyproject_path, "rb") as f:
                data = tomllib.load(f)
            return data.get("project", {}).get("name")
        except Exception:
            pass
    return None


def infer_image_name(name: str, tag: str = "latest") -> str:
    """Infer image name from project name."""
    return f"{name}:{tag}"


def _wait_for_deployment(name: str, namespace: str | None, timeout: int) -> None:
    """Wait for MCPServer deployment to be available."""
    typer.echo("⏳ Waiting for deployment to be available...")
    wait_args = [
        "kubectl",
        "wait",
        f"deployment/mcpserver-{name}",
        "--for=condition=available",
        f"--timeout={timeout}s",
    ]
    if namespace:
        wait_args.extend(["-n", namespace])
    wait_result = subprocess.run(wait_args, capture_output=True, text=True)
    if wait_result.returncode != 0:
        typer.echo(wait_result.stderr or wait_result.stdout, err=True)
        sys.exit(wait_result.returncode)
    typer.echo("✅ Deployment is available")


def deploy_custom_image(
    name: str,
    image: str,
    namespace: str | None,
    params: str | None,
    service_account: str | None,
    wait: bool = False,
    wait_timeout: int = DEFAULT_WAIT_TIMEOUT,
    dry_run: bool = False,
) -> None:
    """Deploy an MCPServer with a custom runtime image."""
    yaml_content = CUSTOM_RUNTIME_TEMPLATE.format(name=name, image=image)

    # Add optional params via env var
    if params:
        yaml_content = (
            yaml_content.rstrip()
            + f"""
    env:
    - name: MCP_PARAMS
      value: "{params}"
"""
        )

    # Add optional service account
    if service_account:
        yaml_content = (
            yaml_content.rstrip()
            + f"""
  serviceAccountName: {service_account}
"""
        )

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
        typer.echo(f"\n✅ Deployed MCPServer '{name}' with image '{image}'")

        if wait:
            _wait_for_deployment(name, namespace, wait_timeout)
    finally:
        Path(tmp_path).unlink()


def deploy_runtime(
    name: str,
    runtime: str,
    namespace: str | None,
    params: str | None,
    service_account: str | None,
    wait: bool = False,
    wait_timeout: int = DEFAULT_WAIT_TIMEOUT,
    dry_run: bool = False,
) -> None:
    """Deploy an MCPServer with a registered runtime."""
    yaml_content = f"""apiVersion: kaos.tools/v1alpha1
kind: MCPServer
metadata:
  name: {name}
spec:
  runtime: {runtime}
"""

    # Add params - properly indented for YAML
    if params:
        # params should be indented under the params: | block
        indented_params = textwrap.indent(params.strip(), "    ")
        yaml_content = (
            yaml_content.rstrip()
            + f"""
  params: |
{indented_params}
"""
        )

    if service_account:
        yaml_content = (
            yaml_content.rstrip()
            + f"""
  serviceAccountName: {service_account}
"""
        )

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
        typer.echo(f"\n✅ Deployed MCPServer '{name}' with runtime '{runtime}'")

        if wait:
            _wait_for_deployment(name, namespace, wait_timeout)
    finally:
        Path(tmp_path).unlink()
