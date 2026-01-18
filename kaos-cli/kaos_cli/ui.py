"""KAOS UI command - starts a CORS-enabled K8s API proxy."""

import signal
import sys
import threading
import time
import webbrowser

import typer
import uvicorn

# KAOS UI hosted on GitHub Pages
KAOS_UI_URL = "https://axsaucedo.github.io/kaos-ui/"


def ui_command(k8s_url: str | None, expose_port: int, no_browser: bool) -> None:
    """Start a CORS-enabled proxy to the Kubernetes API server."""
    from kaos_cli.proxy import create_proxy_app

    app = create_proxy_app(k8s_url=k8s_url)

    typer.echo(f"Starting KAOS UI proxy on http://localhost:{expose_port}")
    typer.echo(f"KAOS UI: {KAOS_UI_URL}")
    typer.echo("Press Ctrl+C to stop")

    def handle_signal(signum: int, frame: object) -> None:
        typer.echo("\nShutting down...")
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    # Open browser after a short delay to allow server to start
    if not no_browser:
        def open_browser() -> None:
            time.sleep(1.5)
            webbrowser.open(KAOS_UI_URL)

        browser_thread = threading.Thread(target=open_browser, daemon=True)
        browser_thread.start()

    uvicorn.run(app, host="0.0.0.0", port=expose_port, log_level="info")
