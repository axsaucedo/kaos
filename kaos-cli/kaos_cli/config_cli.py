"""KAOS config commands."""

from typing import Any

import typer
import yaml

from kaos_cli.config import CONFIG_KEYS, get_value, load_config, save_config, set_value


app = typer.Typer(help="View and update KAOS CLI configuration.", no_args_is_help=True)


def _echo_value(value: Any) -> None:
    if isinstance(value, bool):
        typer.echo(str(value).lower())
    elif isinstance(value, (dict, list)):
        typer.echo(yaml.safe_dump(value, sort_keys=False).rstrip())
    else:
        typer.echo(value)


@app.command(name="show")
def show() -> None:
    """Show the effective KAOS CLI configuration."""
    typer.echo(yaml.safe_dump(load_config(), sort_keys=False).rstrip())


@app.command(name="get")
def get(key: str = typer.Argument(..., help="Dotted configuration key.")) -> None:
    """Get one configuration value."""
    try:
        _echo_value(get_value(load_config(), key))
    except KeyError:
        typer.echo(f"Error: Unknown config key '{key}'", err=True)
        raise typer.Exit(1)


@app.command(name="set")
def set_command(
    key: str = typer.Argument(..., help="Dotted configuration key."),
    value: str = typer.Argument(..., help="Value to store."),
) -> None:
    """Set one configuration value."""
    try:
        parsed = yaml.safe_load(value)
        data = load_config()
        set_value(data, key, parsed)
        path = save_config(data)
    except KeyError:
        typer.echo(
            f"Error: Unknown config key '{key}'. Options: {', '.join(sorted(CONFIG_KEYS))}",
            err=True,
        )
        raise typer.Exit(1)
    typer.echo(f"✓ set {key} in {path}")
