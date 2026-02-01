"""KAOS UI command - starts a CORS-enabled K8s API proxy."""

import signal
import subprocess
import sys
import threading
import time
import webbrowser
from urllib.parse import urlencode

import typer
import uvicorn

from kaos_cli import __version__

# Default monitoring configuration
DEFAULT_MONITORING_NAMESPACE = "monitoring"
SIGNOZ_SERVICE_NAME = "signoz"
SIGNOZ_SERVICE_PORT = 8080
SIGNOZ_LOCAL_PORT = 8011

# KAOS UI hosted on GitHub Pages
KAOS_UI_BASE = "https://axsaucedo.github.io/kaos-ui"


def get_ui_version(override_version: str | None) -> str:
    """Determine the UI version path based on CLI version or override."""
    if override_version:
        # User explicitly set version - "dev" stays as is, others get v prefix
        if override_version.lower() == "dev":
            return "dev"
        return (
            override_version
            if override_version.startswith("v")
            else f"v{override_version}"
        )

    # Use CLI version - if it's a dev version, use /dev/
    cli_version = __version__
    if "dev" in cli_version.lower() or cli_version.startswith("0.0"):
        return "dev"

    # For release versions, use the version number
    return f"v{cli_version}" if not cli_version.startswith("v") else cli_version


def check_signoz_service(namespace: str) -> bool:
    """Check if SigNoz frontend service exists in the specified namespace."""
    try:
        result = subprocess.run(
            ["kubectl", "get", "svc", SIGNOZ_SERVICE_NAME, "-n", namespace],
            capture_output=True,
            text=True,
        )
        return result.returncode == 0
    except Exception:
        return False


def start_signoz_port_forward(namespace: str) -> subprocess.Popen | None:
    """Start kubectl port-forward for SigNoz frontend service."""
    try:
        process = subprocess.Popen(
            [
                "kubectl",
                "port-forward",
                f"svc/{SIGNOZ_SERVICE_NAME}",
                f"{SIGNOZ_LOCAL_PORT}:{SIGNOZ_SERVICE_PORT}",
                "-n",
                namespace,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return process
    except Exception as e:
        typer.echo(f"Failed to start SigNoz port-forward: {e}", err=True)
        return None


def ui_command(
    k8s_url: str | None,
    expose_port: int,
    namespace: str,
    no_browser: bool,
    version: str | None = None,
    monitoring_enabled: bool = False,
    monitoring_namespace: str = DEFAULT_MONITORING_NAMESPACE,
) -> None:
    """Start a CORS-enabled proxy to the Kubernetes API server."""
    from kaos_cli.proxy import create_proxy_app

    signoz_process: subprocess.Popen | None = None

    # Check and start SigNoz port-forward if monitoring enabled
    if monitoring_enabled:
        typer.echo(f"Checking for SigNoz in namespace '{monitoring_namespace}'...")
        if check_signoz_service(monitoring_namespace):
            signoz_process = start_signoz_port_forward(monitoring_namespace)
            if signoz_process:
                typer.echo(
                    f"SigNoz UI available at http://localhost:{SIGNOZ_LOCAL_PORT}"
                )
            else:
                typer.echo("Warning: Failed to start SigNoz port-forward", err=True)
        else:
            typer.echo(
                f"Error: SigNoz service '{SIGNOZ_SERVICE_NAME}' not found in namespace '{monitoring_namespace}'.",
                err=True,
            )
            typer.echo(
                "To install SigNoz, follow the docs: https://axsaucedo.github.io/kaos/latest/operator/telemetry/",
                err=True,
            )
            typer.echo(
                f"  1. Install SigNoz in the '{monitoring_namespace}' namespace",
                err=True,
            )
            typer.echo(
                "  2. Install KAOS with telemetry enabled: kaos install --set telemetry.enabled=true --set telemetry.endpoint=http://signoz-otel-collector.monitoring:4317",
                err=True,
            )
            raise typer.Exit(1)

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
        if signoz_process:
            signoz_process.terminate()
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
