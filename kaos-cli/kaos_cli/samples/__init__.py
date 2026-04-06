"""KAOS samples commands - deploy example configurations."""

import getpass
import subprocess
import tempfile
from pathlib import Path

import typer
import yaml

_API_SECRET_PROMPT = "__PROMPT__"

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
    """Apply CLI overrides to sample YAML content using YAML parser.

    Filters out Namespace kind documents. When modelapi_name is provided,
    filters out ModelAPI kind documents (uses an existing ModelAPI instead).
    """
    docs = list(yaml.safe_load_all(yaml_content))

    # Parse api_secret (must be secretname:key format at this point)
    secret_name = secret_key = None
    if api_secret:
        if ":" in api_secret:
            secret_name, secret_key = api_secret.split(":", 1)
        else:
            raise ValueError(f"Invalid api_secret format: {api_secret!r}. Expected secretname:key.")

    filtered = []
    for doc in docs:
        if not doc or not isinstance(doc, dict):
            continue

        kind = doc.get("kind", "")

        # Skip Namespace resources (samples install into current/provided namespace)
        if kind == "Namespace":
            continue

        # Skip ModelAPI when --modelapi override is used (using existing ModelAPI)
        if kind == "ModelAPI" and modelapi_name:
            continue

        meta = doc.get("metadata", {})

        # Namespace override
        if namespace:
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

        filtered.append(doc)

    return yaml.dump_all(filtered, default_flow_style=False, sort_keys=False)


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


def _create_api_secret(
    name: str, namespace: str | None, api_key: str
) -> tuple[str, str]:
    """Create a Kubernetes secret for API key and return (secret_name, key_name)."""
    secret_name = f"kaos-{name}-api-key"
    key_name = "api-key"
    secret_yaml = (
        f"apiVersion: v1\nkind: Secret\nmetadata:\n  name: {secret_name}\n"
        f"type: Opaque\nstringData:\n  {key_name}: {api_key}\n"
    )
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
            raise typer.Exit(result.returncode)
        typer.echo(f"🔑 Created secret '{secret_name}'")
    finally:
        Path(tmp_path).unlink()
    return secret_name, key_name


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

    # Handle api_secret: bare flag triggers prompt, value must be secretname:key format
    if api_secret == _API_SECRET_PROMPT:
        if dry_run:
            typer.echo(
                "Note: --api-secret without value would prompt for API key",
                err=True,
            )
            secret_name = f"kaos-{name}-api-key"
            api_secret = f"{secret_name}:api-key"
        else:
            api_key = getpass.getpass("Enter API key: ")
            secret_name, secret_key = _create_api_secret(name, namespace, api_key)
            api_secret = f"{secret_name}:{secret_key}"
    elif api_secret and ":" not in api_secret:
        typer.echo(
            f"Error: Invalid --api-secret format '{api_secret}'. Expected secretname:key format.",
            err=True,
        )
        raise typer.Exit(1)

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
            ns = namespace or "default"
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


def delete_sample(
    name: str, namespace: str | None = None, modelapi: str | None = None
) -> None:
    """Delete a sample's resources (excluding Namespace and overridden ModelAPI)."""
    sample_path = _find_sample(name)
    if not sample_path:
        typer.echo(f"Error: Sample '{name}' not found.", err=True)
        typer.echo(f"Available samples: {', '.join(_get_sample_names())}", err=True)
        raise typer.Exit(1)

    raw_content = sample_path.read_text()
    yaml_content = _apply_overrides(
        raw_content,
        modelapi_name=modelapi,
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

    if result.returncode != 0:
        typer.echo(result.stderr or result.stdout, err=True)
        raise typer.Exit(result.returncode)
    typer.echo(result.stdout)
    typer.echo(f"\n✅ Deleted sample '{name}'")


from typer.core import TyperGroup
from kaos_cli.utils import preprocess_optional_value_flag


class _SamplesGroup(TyperGroup):
    """Custom Group that allows --api-secret to be used without a value."""

    def get_command(self, ctx, cmd_name):
        cmd = super().get_command(ctx, cmd_name)
        if cmd and cmd_name == "deploy":
            original_parse = cmd.parse_args

            def patched_parse(ctx, args):
                args = preprocess_optional_value_flag(
                    args, "--api-secret", _API_SECRET_PROMPT
                )
                return original_parse(ctx, args)

            cmd.parse_args = patched_parse
        return cmd


app = typer.Typer(
    cls=_SamplesGroup,
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
        help="API secret (secretname:key format, or pass without value to prompt for key).",
    ),
    provider: str = typer.Option(
        None,
        "--provider",
        help="Override LiteLLM provider for ModelAPI (e.g., openai, nebius).",
    ),
) -> None:
    """Deploy a sample configuration.

    Resources are deployed to the current kubectl context namespace by default.
    Use -n to specify a target namespace. Namespace resources in samples are
    skipped (not created). When --modelapi is used, the sample's built-in
    ModelAPI is skipped (uses your existing ModelAPI instead).

    Examples:
      kaos samples deploy 1-simple-echo-agent -n my-ns
      kaos samples deploy 3-hierarchical-agents --namespace my-ns
      kaos samples deploy 1-simple-echo-agent --model "llama3:8b" --dry-run
      kaos samples deploy 1-simple-echo-agent --api-secret nebius-secrets:api-key
      kaos samples deploy 5-proxy-external-api --provider openai
      kaos samples deploy 1-simple-echo-agent -n my-ns --modelapi existing-api
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
    modelapi: str = typer.Option(
        None,
        "--modelapi",
        help="Skip deleting ModelAPI (use when deployed with --modelapi override).",
    ),
) -> None:
    """Delete a sample's resources.

    Does not delete Namespaces. When --modelapi is provided, skips deleting the
    sample's ModelAPI resources (preserves the external ModelAPI you referenced).

    Examples:
      kaos samples delete 1-simple-echo-agent
      kaos samples delete 1-simple-echo-agent --namespace custom-ns
      kaos samples delete 1-simple-echo-agent --namespace custom-ns --modelapi my-api
    """
    delete_sample(name=name, namespace=namespace, modelapi=modelapi)
