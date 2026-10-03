"""kaos-harness CLI — serve the driver."""

import os

import typer
import uvicorn

app = typer.Typer(
    name="kaos-harness",
    help="Serve the KAOS Agent HTTP contract in front of a coding harness.",
    no_args_is_help=True,
)


@app.command()
def serve(
    host: str = typer.Option("0.0.0.0", help="Bind address"),
    port: int = typer.Option(int(os.environ.get("AGENT_PORT", "8000")), help="Bind port"),
    log_level: str = typer.Option("info", help="uvicorn log level"),
) -> None:
    """Run the harness driver. All agent configuration comes from env vars."""
    uvicorn.run(
        "kaos_harness.driver:get_app",
        factory=True,
        host=host,
        port=port,
        log_level=log_level,
    )


if __name__ == "__main__":  # pragma: no cover
    app()
