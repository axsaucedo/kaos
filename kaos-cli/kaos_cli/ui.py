"""KAOS UI command - starts a CORS-enabled K8s API proxy."""

import signal
import sys
import threading
import time
import webbrowser
from urllib.parse import urlencode

import typer
import uvicorn

from kaos_cli import __version__

# KAOS UI hosted on GitHub Pages
KAOS_UI_BASE = "https://axsaucedo.github.io/kaos-ui"


def get_ui_version(override_version: str | None) -> str:
    """Determine the UI version path based on CLI version or override."""
    if override_version:
        # User explicitly set version - "dev" stays as is, others get v prefix
        if override_version.lower() == "dev":
            return "dev"
        return override_version if override_version.startswith("v") else f"v{override_version}"
    
    # Use CLI version - if it's a dev version, use /dev/
    cli_version = __version__
    if "dev" in cli_version.lower() or cli_version.startswith("0.0"):
        return "dev"
    
    # For release versions, use the version number
    return f"v{cli_version}" if not cli_version.startswith("v") else cli_version


def ui_command(k8s_url: str | None, expose_port: int, namespace: str, no_browser: bool, version: str | None = None) -> None:
    """Start a CORS-enabled proxy to the Kubernetes API server."""
    from kaos_cli.proxy import create_proxy_app

    app = create_proxy_app(k8s_url=k8s_url)

    typer.echo(f"Starting KAOS UI proxy on http://localhost:{expose_port}")
    
    # Determine UI version
    ui_version = get_ui_version(version)
    base_url = f"{KAOS_UI_BASE}/{ui_version}/"
    
    # Build UI URL with query parameters
    query_params = {}
    # Only add kubernetesUrl if not using default port
    if expose_port != 8010:
        query_params["kubernetesUrl"] = f"http://localhost:{expose_port}"
    # Only add namespace if not using default
    if namespace and namespace != "default":
        query_params["namespace"] = namespace
    
    ui_url = base_url
    if query_params:
        ui_url = f"{base_url}?{urlencode(query_params)}"
    
    typer.echo(f"KAOS UI: {ui_url}")
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
            webbrowser.open(ui_url)

        browser_thread = threading.Thread(target=open_browser, daemon=True)
        browser_thread.start()

    uvicorn.run(app, host="0.0.0.0", port=expose_port, log_level="info")
