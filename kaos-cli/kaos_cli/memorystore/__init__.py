"""KAOS MemoryStore commands."""

import typer

from kaos_cli.memorystore.create import create_memorystore


app = typer.Typer(
    help="MemoryStore management commands.",
    no_args_is_help=True,
)


@app.command(name="create")
def create_memorystore_cmd(
    name: str = typer.Argument(..., help="Name for the MemoryStore."),
    modelapi: str = typer.Option(
        ..., "--modelapi", help="ModelAPI reference for both models."
    ),
    summarization_model: str = typer.Option(
        "gpt-4o-mini", "--summarization-model", help="Summarization model name."
    ),
    embedding_model: str = typer.Option(
        "text-embedding-3-small", "--embedding-model", help="Embedding model name."
    ),
    short_term_token_budget: int = typer.Option(
        None, "--short-term-token-budget", help="Short-term memory token budget."
    ),
    medium_term_enabled: bool = typer.Option(
        False, "--medium-term-enabled", help="Enable rolling medium-term summaries."
    ),
    max_read_scope: str = typer.Option(
        None, "--max-read-scope", help="Maximum memory read scope."
    ),
    failure_mode: str = typer.Option(
        None, "--failure-mode", help="Default failure mode: soft or strict."
    ),
    namespace: str = typer.Option(
        None, "--namespace", "-n", help="Namespace to create in."
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Print YAML instead of creating."
    ),
) -> None:
    """Create a local Chroma-backed MemoryStore."""
    if failure_mode not in (None, "soft", "strict"):
        raise typer.BadParameter(
            "must be 'soft' or 'strict'", param_hint="--failure-mode"
        )

    create_memorystore(
        name=name,
        modelapi=modelapi,
        summarization_model=summarization_model,
        embedding_model=embedding_model,
        short_term_token_budget=short_term_token_budget,
        medium_term_enabled=medium_term_enabled,
        max_read_scope=max_read_scope,
        failure_mode=failure_mode,
        namespace=namespace,
        dry_run=dry_run,
    )
