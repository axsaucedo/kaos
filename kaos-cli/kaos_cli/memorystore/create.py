"""Create MemoryStore resources."""

import subprocess
import sys
import tempfile
from pathlib import Path

import typer


def create_memorystore(
    name: str,
    modelapi: str,
    summarization_model: str,
    embedding_model: str,
    short_term_token_budget: int | None,
    medium_term_enabled: bool,
    default_read_scope: str | None,
    failure_mode: str | None,
    namespace: str | None,
    dry_run: bool,
) -> None:
    """Create a local Chroma-backed MemoryStore."""
    yaml_content = f"""apiVersion: kaos.tools/v1alpha1
kind: MemoryStore
metadata:
  name: {name}
spec:
  engine: mem0
  storage:
    type: local
    local:
      provider: chroma
      persistentVolume:
        size: "1Gi"
  models:
    summarization:
      modelAPI: {modelapi}
      model: {summarization_model}
    embedding:
      modelAPI: {modelapi}
      model: {embedding_model}
"""
    if default_read_scope:
        yaml_content += f"  defaultReadScope: {default_read_scope}\n"
    if failure_mode:
        yaml_content += f"  defaultFailureMode: {failure_mode}\n"
    if short_term_token_budget is not None or medium_term_enabled:
        yaml_content += "  container:\n    env:\n"
        if short_term_token_budget is not None:
            yaml_content += "    - name: KAOS_MEMORY_TOKEN_BUDGET\n"
            yaml_content += f'      value: "{short_term_token_budget}"\n'
        if medium_term_enabled:
            yaml_content += "    - name: KAOS_MEMORY_ROLLING_SUMMARY\n"
            yaml_content += '      value: "true"\n'

    if dry_run:
        typer.echo(yaml_content)
        return

    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as file:
        file.write(yaml_content)
        tmp_path = file.name

    try:
        args = ["kubectl", "apply", "-f", tmp_path]
        if namespace:
            args.extend(["-n", namespace])
        result = subprocess.run(args, capture_output=True, text=True)
        if result.returncode != 0:
            typer.echo(result.stderr or result.stdout, err=True)
            sys.exit(result.returncode)
        typer.echo(result.stdout)
        typer.echo(f"\n✅ Created MemoryStore '{name}'")
    finally:
        Path(tmp_path).unlink()
