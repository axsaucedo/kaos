"""KAOS samples commands - deploy example configurations."""

import subprocess
import tempfile
from pathlib import Path

import typer
import yaml

# Resolve samples directory: bundled package data (copied at build time), or repo path
_PACKAGE_DATA_DIR = Path(__file__).resolve().parent / "data"
_REPO_SAMPLES_DIR = (
    Path(__file__).resolve().parent.parent.parent.parent
    / "operator"
    / "config"
    / "samples"
)

def _resolve_samples_dir() -> Path:
    """Resolve samples directory, preferring bundled data, falling back to repo."""
    pkg_yamls = list(_PACKAGE_DATA_DIR.glob("*.yaml")) if _PACKAGE_DATA_DIR.exists() else []
    if pkg_yamls:
        return _PACKAGE_DATA_DIR
    if _REPO_SAMPLES_DIR.exists():
        return _REPO_SAMPLES_DIR
    return _PACKAGE_DATA_DIR  # will be empty, handled by _get_sample_files

SAMPLES_DIR = _resolve_samples_dir()


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
    provider: str | None = None,
) -> str:
    """Apply CLI overrides to sample YAML content using YAML parser."""
    docs = list(yaml.safe_load_all(yaml_content))

    # Parse api_secret once
    secret_name = secret_key = None
    if api_secret:
        if ":" in api_secret:
            secret_name, secret_key = api_secret.split(":", 1)
        else:
            secret_name, secret_key = api_secret, "api-key"

    for doc in docs:
        if not doc or not isinstance(doc, dict):
            continue

        kind = doc.get("kind", "")
        meta = doc.get("metadata", {})

        # Namespace override
        if namespace:
            if kind == "Namespace":
                meta["name"] = namespace
            else:
                meta["namespace"] = namespace

        spec = doc.get("spec", {})

        if kind == "Agent":
            if modelapi_name:
                spec["modelAPI"] = modelapi_name
            if model:
                spec["model"] = model

        if kind == "ModelAPI":
            if mode:
                spec["mode"] = mode
            hosted = spec.get("hostedConfig")
            if hosted and model:
                hosted["model"] = model
            proxy = spec.get("proxyConfig")
            if proxy and provider:
                proxy["provider"] = provider
            if proxy and secret_name:
                proxy["apiKey"] = {
                    "valueFrom": {
                        "secretKeyRef": {
                            "name": secret_name,
                            "key": secret_key,
                        }
                    }
                }

    return yaml.dump_all(docs, default_flow_style=False, sort_keys=False)


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
    provider: str | None = None,
) -> None:
    """Deploy a sample configuration."""
    sample_path = _find_sample(name)
    if not sample_path:
        typer.echo(f"Error: Sample '{name}' not found.", err=True)
        typer.echo(f"Available samples: {', '.join(_get_sample_names())}", err=True)
        raise typer.Exit(1)

    raw_content = sample_path.read_text()

    # Apply overrides
    yaml_content = _apply_overrides(
        raw_content,
        modelapi_name=modelapi,
        mode=mode,
        model=model,
        api_secret=api_secret,
        namespace=namespace,
        provider=provider,
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
            raise typer.Exit(result.returncode)
        typer.echo(result.stdout)
        typer.echo(f"\n✅ Deployed sample '{name}'")

        if wait:
            # Determine the namespace to wait in
            ns = namespace
            if not ns:
                docs = list(yaml.safe_load_all(yaml_content))
                for doc in docs:
                    if doc and doc.get("kind") == "Namespace":
                        ns = doc["metadata"]["name"]
                        break
                ns = ns or "default"
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


def delete_sample(name: str, namespace: str | None = None) -> None:
    """Delete a sample's resources."""
    sample_path = _find_sample(name)
    if not sample_path:
        typer.echo(f"Error: Sample '{name}' not found.", err=True)
        typer.echo(f"Available samples: {', '.join(_get_sample_names())}", err=True)
        raise typer.Exit(1)

    if namespace:
        # Apply namespace override and delete from temp file
        raw_content = sample_path.read_text()
        yaml_content = _apply_overrides(
            raw_content,
            modelapi_name=None,
            mode=None,
            model=None,
            api_secret=None,
            namespace=namespace,
        )
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            tmp_path = f.name
        try:
            args = ["kubectl", "delete", "-f", tmp_path, "--ignore-not-found"]
            result = subprocess.run(args, capture_output=True, text=True)
        finally:
            Path(tmp_path).unlink()
    else:
        args = ["kubectl", "delete", "-f", str(sample_path), "--ignore-not-found"]
        result = subprocess.run(args, capture_output=True, text=True)

    if result.returncode != 0:
        typer.echo(result.stderr or result.stdout, err=True)
        raise typer.Exit(result.returncode)
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
    provider: str = typer.Option(
        None,
        "--provider",
        help="Override LiteLLM provider for ModelAPI (e.g., openai, nebius).",
    ),
) -> None:
    """Deploy a sample configuration.

    Examples:
      kaos samples deploy 1-simple-echo-agent
      kaos samples deploy 3-hierarchical-agents --namespace my-ns
      kaos samples deploy 1-simple-echo-agent --model "llama3:8b" --dry-run
      kaos samples deploy 1-simple-echo-agent --api-secret nebius-secrets:api-key
      kaos samples deploy 5-proxy-external-api --provider openai
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
        provider=provider,
    )


@app.command(name="delete")
def delete_cmd(
    name: str = typer.Argument(..., help="Name of the sample to delete."),
    namespace: str = typer.Option(
        None,
        "--namespace",
        "-n",
        help="Namespace override (must match the namespace used during deploy).",
    ),
) -> None:
    """Delete a sample's resources.

    Examples:
      kaos samples delete 1-simple-echo-agent
      kaos samples delete 1-simple-echo-agent --namespace custom-ns
    """
    delete_sample(name=name, namespace=namespace)
