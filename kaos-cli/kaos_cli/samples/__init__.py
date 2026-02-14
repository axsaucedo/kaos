"""KAOS samples commands - deploy example configurations."""

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional

import typer

# Resolve samples directory relative to repo root
_CLI_DIR = Path(__file__).resolve().parent.parent.parent
_REPO_ROOT = _CLI_DIR.parent
SAMPLES_DIR = _REPO_ROOT / "operator" / "config" / "samples"

# Override map: CLI param → YAML field replacements
# Each override specifies which YAML patterns to find and replace
MODELAPI_OVERRIDE_FIELDS = {
    "mode": {
        "pattern": r"(spec:\s*\n\s+mode:\s+)\S+",
        "replace": r"\g<1>{value}",
    },
    "model": {
        # Override hostedConfig.model for Hosted mode
        "pattern": r"(hostedConfig:\s*\n\s+model:\s+)\S+",
        "replace": r"\g<1>{value}",
    },
}


def _get_sample_files() -> list[Path]:
    """Return sorted list of sample YAML files (excluding kustomization)."""
    if not SAMPLES_DIR.exists():
        return []
    return sorted(
        f
        for f in SAMPLES_DIR.glob("*.yaml")
        if f.name != "kustomization.yaml"
    )


def _get_sample_names() -> list[str]:
    """Return list of sample names (filename without .yaml extension)."""
    return [f.stem for f in _get_sample_files()]


def _find_sample(name: str) -> Path | None:
    """Find a sample file by name (with or without .yaml extension)."""
    for f in _get_sample_files():
        if f.stem == name or f.name == name:
            return f
    return None


def _parse_sample_description(path: Path) -> str:
    """Extract the first comment line as description."""
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line.startswith("#") and not line.startswith("#!"):
                desc = line.lstrip("# ").strip()
                if desc:
                    return desc
    return ""


def _apply_overrides(
    yaml_content: str,
    modelapi_name: str | None,
    mode: str | None,
    model: str | None,
    api_secret: str | None,
    namespace: str | None,
) -> str:
    """Apply CLI overrides to sample YAML content."""
    # Override namespace in all resources
    if namespace:
        # Replace namespace in metadata
        yaml_content = re.sub(
            r"(metadata:\s*\n\s+name:\s+\S+\s*\n\s+namespace:\s+)\S+",
            rf"\g<1>{namespace}",
            yaml_content,
        )
        # Replace namespace in Namespace resource
        yaml_content = re.sub(
            r"(kind: Namespace\s*\nmetadata:\s*\n\s+name:\s+)\S+",
            rf"\g<1>{namespace}",
            yaml_content,
        )

    # Override ModelAPI reference in Agent specs
    if modelapi_name:
        yaml_content = re.sub(
            r"(spec:\s*\n\s+modelAPI:\s+)\S+",
            rf"\g<1>{modelapi_name}",
            yaml_content,
        )

    # Override mode in ModelAPI specs
    if mode:
        yaml_content = re.sub(
            r"(\bmode:\s+)(Proxy|Hosted)",
            rf"\g<1>{mode}",
            yaml_content,
        )

    # Override model in hostedConfig and Agent model field
    if model:
        yaml_content = re.sub(
            r"(hostedConfig:\s*\n\s+model:\s+)\"?[^\"'\n]+\"?",
            rf'\g<1>"{model}"',
            yaml_content,
        )
        yaml_content = re.sub(
            r"(spec:\s*\n\s+modelAPI:\s+\S+\s*\n\s+model:\s+)\"?[^\"'\n]+\"?",
            rf'\g<1>"{model}"',
            yaml_content,
        )

    # Override API secret in ModelAPI specs
    if api_secret:
        if ":" in api_secret:
            secret_name, key_name = api_secret.split(":", 1)
        else:
            secret_name = api_secret
            key_name = "api-key"
        secret_block = f"""apiKey:
      valueFrom:
        secretKeyRef:
          name: {secret_name}
          key: {key_name}"""
        # If proxyConfig already has apiKey, replace it
        if "apiKey:" in yaml_content:
            yaml_content = re.sub(
                r"apiKey:\s*\n\s+valueFrom:\s*\n\s+secretKeyRef:\s*\n\s+name:\s+\S+\s*\n\s+key:\s+\S+",
                secret_block,
                yaml_content,
            )
        else:
            # Add apiKey to proxyConfig sections
            yaml_content = re.sub(
                r"(proxyConfig:\s*\n(?:\s+\S.*\n)*)",
                rf"\g<1>    {secret_block}\n",
                yaml_content,
            )

    return yaml_content


def list_samples() -> None:
    """List available sample configurations."""
    samples = _get_sample_files()
    if not samples:
        typer.echo("No samples found.")
        return

    typer.echo("Available samples:\n")
    for f in samples:
        desc = _parse_sample_description(f)
        typer.echo(f"  {f.stem}")
        if desc:
            typer.echo(f"    {desc}")
        typer.echo("")


def deploy_sample(
    name: str,
    namespace: str | None = None,
    wait: bool = False,
    wait_timeout: int = 120,
    dry_run: bool = False,
    modelapi: str | None = None,
    mode: str | None = None,
    model: str | None = None,
    api_secret: str | None = None,
) -> None:
    """Deploy a sample configuration."""
    sample_path = _find_sample(name)
    if not sample_path:
        typer.echo(f"Error: Sample '{name}' not found.", err=True)
        typer.echo(f"Available samples: {', '.join(_get_sample_names())}", err=True)
        sys.exit(1)

    yaml_content = sample_path.read_text()

    # Apply overrides
    yaml_content = _apply_overrides(
        yaml_content,
        modelapi_name=modelapi,
        mode=mode,
        model=model,
        api_secret=api_secret,
        namespace=namespace,
    )

    if dry_run:
        typer.echo(yaml_content)
        return

    # Write to temp file and apply
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(yaml_content)
        tmp_path = f.name

    try:
        args = ["kubectl", "apply", "--server-side", "-f", tmp_path]
        result = subprocess.run(args, capture_output=True, text=True)
        if result.returncode != 0:
            typer.echo(result.stderr or result.stdout, err=True)
            sys.exit(result.returncode)
        typer.echo(result.stdout)
        typer.echo(f"\n✅ Deployed sample '{name}'")

        if wait:
            # Determine the namespace to wait in
            ns = namespace
            if not ns:
                # Extract first namespace from the YAML
                ns_match = re.search(
                    r"kind: Namespace\s*\nmetadata:\s*\n\s+name:\s+(\S+)", yaml_content
                )
                ns = ns_match.group(1) if ns_match else "default"
            typer.echo(f"⏳ Waiting for resources in namespace '{ns}'...")
            wait_args = [
                "kubectl",
                "wait",
                "--for=condition=available",
                "deployment",
                "--all",
                "-n",
                ns,
                f"--timeout={wait_timeout}s",
            ]
            wait_result = subprocess.run(wait_args, capture_output=True, text=True)
            if wait_result.returncode != 0:
                typer.echo(wait_result.stderr or wait_result.stdout, err=True)
            else:
                typer.echo("✅ All deployments are available")
    finally:
        Path(tmp_path).unlink()


def delete_sample(name: str) -> None:
    """Delete a sample's resources."""
    sample_path = _find_sample(name)
    if not sample_path:
        typer.echo(f"Error: Sample '{name}' not found.", err=True)
        typer.echo(f"Available samples: {', '.join(_get_sample_names())}", err=True)
        sys.exit(1)

    args = ["kubectl", "delete", "-f", str(sample_path), "--ignore-not-found"]
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode != 0:
        typer.echo(result.stderr or result.stdout, err=True)
        sys.exit(result.returncode)
    typer.echo(result.stdout)
    typer.echo(f"\n✅ Deleted sample '{name}'")


app = typer.Typer(
    help="Deploy and manage example configurations.",
    no_args_is_help=True,
)


@app.command(name="list")
def list_cmd() -> None:
    """List available sample configurations."""
    list_samples()


@app.command(name="deploy")
def deploy_cmd(
    name: str = typer.Argument(..., help="Name of the sample to deploy."),
    namespace: str = typer.Option(
        None,
        "--namespace",
        "-n",
        help="Override namespace for all resources.",
    ),
    wait: bool = typer.Option(
        False, "--wait", help="Wait for deployments to be available."
    ),
    wait_timeout: int = typer.Option(
        120, "--wait-timeout", help="Timeout in seconds for --wait."
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Print YAML instead of deploying."
    ),
    modelapi: str = typer.Option(
        None, "--modelapi", help="Override ModelAPI name reference in Agent specs."
    ),
    mode: str = typer.Option(
        None, "--mode", help="Override ModelAPI mode (Proxy or Hosted)."
    ),
    model: str = typer.Option(
        None, "--model", "-m", help="Override model name."
    ),
    api_secret: str = typer.Option(
        None,
        "--api-secret",
        help="Override API secret (secretname:key format).",
    ),
) -> None:
    """Deploy a sample configuration.

    Examples:
      kaos samples deploy 1-simple-echo-agent
      kaos samples deploy 3-hierarchical-agents --namespace my-ns
      kaos samples deploy 1-simple-echo-agent --model "llama3:8b" --dry-run
      kaos samples deploy 1-simple-echo-agent --api-secret nebius-secrets:api-key
    """
    deploy_sample(
        name=name,
        namespace=namespace,
        wait=wait,
        wait_timeout=wait_timeout,
        dry_run=dry_run,
        modelapi=modelapi,
        mode=mode,
        model=model,
        api_secret=api_secret,
    )


@app.command(name="delete")
def delete_cmd(
    name: str = typer.Argument(..., help="Name of the sample to delete."),
) -> None:
    """Delete a sample's resources.

    Examples:
      kaos samples delete 1-simple-echo-agent
    """
    delete_sample(name=name)
