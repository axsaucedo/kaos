"""KAOS install/uninstall commands for the Kubernetes operator."""

import shutil
import subprocess
import sys

import typer

# Helm chart repository URL (hosted on GitHub Pages)
HELM_REPO_URL = "https://axsaucedo.github.io/kaos/charts"
HELM_REPO_NAME = "kaos"
HELM_CHART_NAME = "kaos-operator"
DEFAULT_NAMESPACE = "kaos-system"
DEFAULT_RELEASE_NAME = "kaos"


def check_helm_installed() -> bool:
    """Check if helm is installed and available."""
    return shutil.which("helm") is not None


def run_helm_command(
    args: list[str], check: bool = True
) -> subprocess.CompletedProcess:
    """Run a helm command and return the result."""
    cmd = ["helm"] + args
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=check,
        )
        return result
    except subprocess.CalledProcessError as e:
        typer.echo(f"Error running helm: {e.stderr}", err=True)
        raise


MONITORING_BACKENDS = ("signoz", "jaeger")


def _install_signoz() -> bool:
    """Install SigNoz monitoring stack."""
    typer.echo("Installing SigNoz monitoring stack...")

    result = run_helm_command(
        ["repo", "add", "signoz", "https://charts.signoz.io", "--force-update"],
        check=False,
    )
    if result.returncode != 0 and "already exists" not in result.stderr:
        typer.echo(f"Warning adding SigNoz repo: {result.stderr}", err=True)

    run_helm_command(["repo", "update"], check=False)

    result = run_helm_command(
        [
            "upgrade",
            "--install",
            "signoz",
            "signoz/signoz",
            "--namespace",
            "observability",
            "--create-namespace",
            "--wait",
        ],
        check=False,
    )
    if result.returncode != 0:
        typer.echo(f"Error installing SigNoz: {result.stderr}", err=True)
        return False

    typer.echo("✅ SigNoz monitoring installed in 'observability' namespace")
    return True


def _install_jaeger() -> bool:
    """Install Jaeger all-in-one with OTLP collector."""
    typer.echo("Installing Jaeger all-in-one...")

    result = run_helm_command(
        [
            "repo",
            "add",
            "jaegertracing",
            "https://jaegertracing.github.io/helm-charts",
            "--force-update",
        ],
        check=False,
    )
    if result.returncode != 0 and "already exists" not in result.stderr:
        typer.echo(f"Warning adding Jaeger repo: {result.stderr}", err=True)

    run_helm_command(["repo", "update"], check=False)

    result = run_helm_command(
        [
            "upgrade",
            "--install",
            "jaeger",
            "jaegertracing/jaeger",
            "--namespace",
            "observability",
            "--create-namespace",
            "--set",
            "allInOne.enabled=true",
            "--set",
            "collector.enabled=false",
            "--set",
            "query.enabled=false",
            "--set",
            "agent.enabled=false",
            "--set",
            "provisionDataStore.cassandra=false",
            "--wait",
        ],
        check=False,
    )
    if result.returncode != 0:
        typer.echo(f"Error installing Jaeger: {result.stderr}", err=True)
        return False

    typer.echo("✅ Jaeger installed in 'observability' namespace")
    return True


def _install_monitoring(backend: str) -> bool:
    """Install monitoring stack for the given backend."""
    if backend == "jaeger":
        return _install_jaeger()
    return _install_signoz()


def _get_otel_endpoint(backend: str) -> str:
    """Return the OTLP collector endpoint for the given backend."""
    if backend == "jaeger":
        return "http://jaeger-collector.observability:4317"
    return "http://signoz-otel-collector.observability:4317"


def install_command(
    namespace: str,
    release_name: str,
    version: str | None,
    set_values: list[str],
    wait: bool,
    monitoring_enabled: str | None = None,
) -> None:
    """Install the KAOS operator using Helm."""
    if not check_helm_installed():
        typer.echo("Error: helm is not installed. Please install helm first.", err=True)
        typer.echo("See: https://helm.sh/docs/intro/install/", err=True)
        sys.exit(1)

    # Install monitoring first if requested
    if monitoring_enabled:
        if not _install_monitoring(monitoring_enabled):
            typer.echo("Warning: Monitoring installation failed, continuing...", err=True)

    typer.echo(f"Installing KAOS operator to namespace '{namespace}'...")

    # Add the Helm repository
    typer.echo(f"Adding Helm repository '{HELM_REPO_NAME}'...")
    result = run_helm_command(
        ["repo", "add", HELM_REPO_NAME, HELM_REPO_URL, "--force-update"],
        check=False,
    )
    if result.returncode != 0 and "already exists" not in result.stderr:
        typer.echo(f"Warning: {result.stderr}", err=True)

    # Update repositories
    typer.echo("Updating Helm repositories...")
    run_helm_command(["repo", "update"], check=False)

    # Build helm install command
    helm_args = [
        "upgrade",
        "--install",
        release_name,
        f"{HELM_REPO_NAME}/{HELM_CHART_NAME}",
        "--namespace",
        namespace,
        "--create-namespace",
    ]

    if version:
        helm_args.extend(["--version", version])

    if wait:
        helm_args.append("--wait")

    for value in set_values:
        helm_args.extend(["--set", value])

    # Add telemetry settings if monitoring is enabled
    if monitoring_enabled:
        otel_endpoint = _get_otel_endpoint(monitoring_enabled)
        helm_args.extend(["--set", "telemetry.enabled=true"])
        helm_args.extend(["--set", f"telemetry.endpoint={otel_endpoint}"])

    typer.echo(f"Installing chart {HELM_CHART_NAME}...")
    result = run_helm_command(helm_args)

    if result.returncode == 0:
        typer.echo("")
        typer.echo("✅ KAOS operator installed successfully!")
        typer.echo("")
        typer.echo("Next steps:")
        typer.echo(f"  1. Check the operator status: kubectl get pods -n {namespace}")
        typer.echo("  2. Create your first agent: kubectl apply -f your-agent.yaml")
        typer.echo("  3. Open the UI: kaos ui")
    else:
        typer.echo(f"Error: {result.stderr}", err=True)
        sys.exit(1)


def uninstall_command(namespace: str, release_name: str) -> None:
    """Uninstall the KAOS operator using Helm."""
    if not check_helm_installed():
        typer.echo("Error: helm is not installed.", err=True)
        sys.exit(1)

    typer.echo(f"Uninstalling KAOS operator from namespace '{namespace}'...")

    result = run_helm_command(
        ["uninstall", release_name, "--namespace", namespace],
        check=False,
    )

    if result.returncode == 0:
        typer.echo("✅ KAOS operator uninstalled successfully!")
    elif "not found" in result.stderr.lower():
        typer.echo(f"Release '{release_name}' not found in namespace '{namespace}'.")
    else:
        typer.echo(f"Error: {result.stderr}", err=True)
        sys.exit(1)
