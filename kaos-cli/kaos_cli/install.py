"""KAOS install/uninstall commands for the Kubernetes operator."""

import json
import shutil
import subprocess
import sys
import time

import typer

# Helm chart repository URL (hosted on GitHub Pages)
HELM_REPO_URL = "https://axsaucedo.github.io/kaos/charts"
HELM_REPO_NAME = "kaos"
HELM_CHART_NAME = "kaos-operator"
DEFAULT_NAMESPACE = "kaos-system"
DEFAULT_RELEASE_NAME = "kaos"

# Gateway API defaults
GATEWAY_API_VERSION = "v1.4.1"
ENVOY_GATEWAY_VERSION = "v1.4.6"
GATEWAY_CLASS_NAME = "envoy-gateway"

# MetalLB defaults
METALLB_VERSION = "v0.14.9"


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


def _run_kubectl(args: list[str], check: bool = True, **kwargs) -> subprocess.CompletedProcess:
    """Run a kubectl command and return the result."""
    cmd = ["kubectl"] + args
    return subprocess.run(cmd, capture_output=True, text=True, check=check, **kwargs)


def _install_gateway_api() -> bool:
    """Install Gateway API CRDs, Envoy Gateway controller, and GatewayClass."""
    typer.echo(f"Installing Gateway API CRDs ({GATEWAY_API_VERSION})...")
    result = _run_kubectl(
        ["apply", "-f",
         f"https://github.com/kubernetes-sigs/gateway-api/releases/download/{GATEWAY_API_VERSION}/standard-install.yaml"],
        check=False,
    )
    if result.returncode != 0:
        typer.echo(f"Error installing Gateway API CRDs: {result.stderr}", err=True)
        return False

    typer.echo("Waiting for Gateway API CRDs...")
    for crd in ["gateways.gateway.networking.k8s.io",
                "httproutes.gateway.networking.k8s.io",
                "gatewayclasses.gateway.networking.k8s.io"]:
        result = _run_kubectl(
            ["wait", "--for", "condition=established", f"--timeout=60s", f"crd/{crd}"],
            check=False,
        )
        if result.returncode != 0:
            typer.echo(f"Error waiting for CRD {crd}: {result.stderr}", err=True)
            return False

    typer.echo(f"Installing Envoy Gateway ({ENVOY_GATEWAY_VERSION})...")
    result = run_helm_command(
        ["upgrade", "--install", "envoy-gateway",
         "oci://docker.io/envoyproxy/gateway-helm",
         "--version", ENVOY_GATEWAY_VERSION,
         "--namespace", "envoy-gateway-system", "--create-namespace",
         "--skip-crds", "--wait", "--timeout", "120s"],
        check=False,
    )
    if result.returncode != 0:
        typer.echo(f"Error installing Envoy Gateway: {result.stderr}", err=True)
        return False

    typer.echo("Creating GatewayClass...")
    gc_yaml = (
        "apiVersion: gateway.networking.k8s.io/v1\n"
        "kind: GatewayClass\n"
        "metadata:\n"
        f"  name: {GATEWAY_CLASS_NAME}\n"
        "spec:\n"
        "  controllerName: gateway.envoyproxy.io/gatewayclass-controller\n"
    )
    result = _run_kubectl(["apply", "-f", "-"], check=False, input=gc_yaml)
    if result.returncode != 0:
        typer.echo(f"Error creating GatewayClass: {result.stderr}", err=True)
        return False

    # Wait for GatewayClass to be accepted
    typer.echo("Waiting for GatewayClass to be accepted...")
    for i in range(30):
        result = _run_kubectl(
            ["get", "gatewayclass", GATEWAY_CLASS_NAME,
             "-o", "jsonpath={.status.conditions[?(@.type==\"Accepted\")].status}"],
            check=False,
        )
        if result.stdout.strip() == "True":
            break
        time.sleep(2)
    else:
        typer.echo("Warning: GatewayClass not accepted after 60 seconds", err=True)
        return False

    typer.echo("✅ Gateway API and Envoy Gateway installed successfully!")
    return True


def _uninstall_gateway_api() -> bool:
    """Uninstall Envoy Gateway and Gateway API CRDs."""
    typer.echo("Uninstalling Envoy Gateway...")
    result = run_helm_command(
        ["uninstall", "envoy-gateway", "--namespace", "envoy-gateway-system"],
        check=False,
    )
    if result.returncode != 0 and "not found" not in result.stderr.lower():
        typer.echo(f"Warning: {result.stderr}", err=True)

    _run_kubectl(["delete", "gatewayclass", GATEWAY_CLASS_NAME, "--ignore-not-found"], check=False)
    _run_kubectl(
        ["delete", "-f",
         f"https://github.com/kubernetes-sigs/gateway-api/releases/download/{GATEWAY_API_VERSION}/standard-install.yaml",
         "--ignore-not-found"],
        check=False,
    )
    _run_kubectl(["delete", "namespace", "envoy-gateway-system", "--ignore-not-found"], check=False)
    typer.echo("✅ Gateway API uninstalled")
    return True


def _install_metallb() -> bool:
    """Install MetalLB for LoadBalancer support (KIND/bare-metal clusters)."""
    typer.echo(f"Installing MetalLB ({METALLB_VERSION})...")
    result = _run_kubectl(
        ["apply", "-f",
         f"https://raw.githubusercontent.com/metallb/metallb/{METALLB_VERSION}/config/manifests/metallb-native.yaml"],
        check=False,
    )
    if result.returncode != 0:
        typer.echo(f"Error installing MetalLB: {result.stderr}", err=True)
        return False

    typer.echo("Waiting for MetalLB pods...")
    result = _run_kubectl(
        ["wait", "--namespace", "metallb-system",
         "--for=condition=ready", "pod", "--selector=app=metallb",
         "--timeout=120s"],
        check=False,
    )
    if result.returncode != 0:
        typer.echo(f"Warning: MetalLB pods not ready: {result.stderr}", err=True)

    # Auto-detect KIND network subnet for IP pool
    typer.echo("Configuring MetalLB IP address pool...")
    try:
        net_result = subprocess.run(
            ["docker", "network", "inspect", "kind", "--format",
             "{{(index .IPAM.Config 0).Subnet}}"],
            capture_output=True, text=True, check=False,
        )
        if net_result.returncode == 0 and net_result.stdout.strip():
            cidr = net_result.stdout.strip()
            # Extract first 3 octets (e.g., 172.18.0 from 172.18.0.0/16)
            parts = cidr.split("/")[0].split(".")[:3]
            prefix = ".".join(parts)
            ip_start = f"{prefix}.200"
            ip_end = f"{prefix}.250"
        else:
            # Fallback for non-KIND clusters
            ip_start = "172.18.255.200"
            ip_end = "172.18.255.250"

        pool_yaml = (
            "apiVersion: metallb.io/v1beta1\n"
            "kind: IPAddressPool\n"
            "metadata:\n"
            "  name: kind-pool\n"
            "  namespace: metallb-system\n"
            "spec:\n"
            "  addresses:\n"
            f"  - {ip_start}-{ip_end}\n"
            "---\n"
            "apiVersion: metallb.io/v1beta1\n"
            "kind: L2Advertisement\n"
            "metadata:\n"
            "  name: kind-l2\n"
            "  namespace: metallb-system\n"
            "spec:\n"
            "  ipAddressPools:\n"
            "  - kind-pool\n"
        )
        result = _run_kubectl(["apply", "-f", "-"], check=False, input=pool_yaml)
        if result.returncode != 0:
            typer.echo(f"Warning: Could not configure MetalLB pool: {result.stderr}", err=True)
        else:
            typer.echo(f"  IP range: {ip_start}-{ip_end}")
    except FileNotFoundError:
        typer.echo("Warning: docker not found, skipping MetalLB IP pool configuration", err=True)

    typer.echo("✅ MetalLB installed")
    return True


def _uninstall_metallb() -> bool:
    """Uninstall MetalLB."""
    typer.echo("Uninstalling MetalLB...")
    _run_kubectl(
        ["delete", "-f",
         f"https://raw.githubusercontent.com/metallb/metallb/{METALLB_VERSION}/config/manifests/metallb-native.yaml",
         "--ignore-not-found"],
        check=False,
    )
    _run_kubectl(["delete", "namespace", "metallb-system", "--ignore-not-found"], check=False)
    typer.echo("✅ MetalLB uninstalled")
    return True


def _create_jaeger_ui_config(namespace: str) -> None:
    """Create ConfigMap with Jaeger UI config for dark theme."""
    ui_config = json.dumps({"themes": {"enabled": True}})
    cm_yaml = (
        f"apiVersion: v1\nkind: ConfigMap\nmetadata:\n"
        f"  name: jaeger-ui-config\n  namespace: {namespace}\n"
        f"data:\n  ui-config.json: '{ui_config}'\n"
    )
    result = subprocess.run(
        ["kubectl", "apply", "-f", "-"],
        input=cm_yaml,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        typer.echo(f"Warning: Could not create Jaeger UI config: {result.stderr}", err=True)


def _install_signoz(namespace: str) -> bool:
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
            namespace,
            "--create-namespace",
            "--wait",
        ],
        check=False,
    )
    if result.returncode != 0:
        typer.echo(f"Error installing SigNoz: {result.stderr}", err=True)
        return False

    typer.echo(f"✅ SigNoz monitoring installed in '{namespace}' namespace")
    return True


def _install_jaeger(namespace: str) -> bool:
    """Install Jaeger all-in-one with OTLP collector and dark mode."""
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

    # Create ConfigMap before Helm install to avoid mount race condition
    subprocess.run(
        ["kubectl", "create", "namespace", namespace],
        capture_output=True,
        text=True,
    )
    _create_jaeger_ui_config(namespace)

    result = run_helm_command(
        [
            "upgrade",
            "--install",
            "jaeger",
            "jaegertracing/jaeger",
            "--namespace",
            namespace,
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
            "--set-json",
            'allInOne.extraEnv=[{"name":"QUERY_UI_CONFIG","value":"/etc/jaeger/ui-config.json"}]',
            "--set-json",
            'allInOne.extraConfigmapMounts=[{"name":"jaeger-ui-config","mountPath":"/etc/jaeger","configMap":"jaeger-ui-config"}]',
            "--wait",
        ],
        check=False,
    )
    if result.returncode != 0:
        typer.echo(f"Error installing Jaeger: {result.stderr}", err=True)
        return False

    typer.echo(f"✅ Jaeger installed in '{namespace}' namespace (dark mode enabled)")
    return True


def _install_monitoring(backend: str, namespace: str) -> bool:
    """Install monitoring stack for the given backend."""
    if backend == "jaeger":
        return _install_jaeger(namespace)
    return _install_signoz(namespace)


def _uninstall_monitoring(backend: str, namespace: str) -> bool:
    """Uninstall monitoring stack for the given backend."""
    release = "jaeger" if backend == "jaeger" else "signoz"
    typer.echo(f"Uninstalling {backend} from namespace '{namespace}'...")

    result = run_helm_command(
        ["uninstall", release, "--namespace", namespace],
        check=False,
    )

    if result.returncode == 0:
        # Clean up Jaeger UI ConfigMap if applicable
        if backend == "jaeger":
            subprocess.run(
                ["kubectl", "delete", "configmap", "jaeger-ui-config",
                 "-n", namespace, "--ignore-not-found"],
                capture_output=True,
                text=True,
            )
        typer.echo(f"✅ {backend.capitalize()} uninstalled from '{namespace}'")
        return True
    elif "not found" in result.stderr.lower():
        typer.echo(f"{backend.capitalize()} release not found in namespace '{namespace}'.")
        return True
    else:
        typer.echo(f"Error uninstalling {backend}: {result.stderr}", err=True)
        return False


def _get_otel_endpoint(backend: str, namespace: str) -> str:
    """Return the OTLP collector endpoint for the given backend."""
    if backend == "jaeger":
        return f"http://jaeger.{namespace}:4317"
    return f"http://signoz-otel-collector.{namespace}:4317"


def install_command(
    namespace: str,
    release_name: str,
    version: str | None,
    set_values: list[str],
    wait: bool,
    monitoring_enabled: str | None = None,
    gateway_enabled: bool = False,
    metallb_enabled: bool = False,
    chart_path: str | None = None,
) -> None:
    """Install the KAOS operator using Helm."""
    if not check_helm_installed():
        typer.echo("Error: helm is not installed. Please install helm first.", err=True)
        typer.echo("See: https://helm.sh/docs/intro/install/", err=True)
        sys.exit(1)

    # Install MetalLB first if requested (needed before Gateway)
    if metallb_enabled:
        if not _install_metallb():
            typer.echo("Warning: MetalLB installation failed, continuing...", err=True)

    # Install Gateway API if requested
    if gateway_enabled:
        if not _install_gateway_api():
            typer.echo("Warning: Gateway API installation failed, continuing...", err=True)

    # Install monitoring if requested (in same namespace as operator)
    if monitoring_enabled:
        if not _install_monitoring(monitoring_enabled, namespace):
            typer.echo("Warning: Monitoring installation failed, continuing...", err=True)

    typer.echo(f"Installing KAOS operator to namespace '{namespace}'...")

    # Determine chart reference: local path or published repo
    if chart_path:
        chart_ref = chart_path
        typer.echo(f"Using local chart: {chart_path}")
    else:
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
        chart_ref = f"{HELM_REPO_NAME}/{HELM_CHART_NAME}"

    # Build helm install command
    helm_args = [
        "upgrade",
        "--install",
        release_name,
        chart_ref,
        "--namespace",
        namespace,
        "--create-namespace",
        "--force-conflicts",
    ]

    if version:
        helm_args.extend(["--version", version])

    if wait:
        helm_args.append("--wait")

    for value in set_values:
        helm_args.extend(["--set", value])

    # Add telemetry settings if monitoring is enabled
    if monitoring_enabled:
        otel_endpoint = _get_otel_endpoint(monitoring_enabled, namespace)
        helm_args.extend(["--set", "telemetry.enabled=true"])
        helm_args.extend(["--set", f"telemetry.endpoint={otel_endpoint}"])

    # Add Gateway API settings if gateway is enabled
    if gateway_enabled:
        helm_args.extend(["--set", "gatewayAPI.enabled=true"])
        helm_args.extend(["--set", "gatewayAPI.createGateway=true"])
        helm_args.extend(["--set", f"gatewayAPI.gatewayClassName={GATEWAY_CLASS_NAME}"])

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


def uninstall_command(
    namespace: str,
    release_name: str,
    monitoring_enabled: str | None = None,
    gateway_enabled: bool = False,
    metallb_enabled: bool = False,
) -> None:
    """Uninstall the KAOS operator using Helm."""
    if not check_helm_installed():
        typer.echo("Error: helm is not installed.", err=True)
        sys.exit(1)

    # Uninstall monitoring if requested
    if monitoring_enabled:
        _uninstall_monitoring(monitoring_enabled, namespace)

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

    # Uninstall Gateway API if requested
    if gateway_enabled:
        _uninstall_gateway_api()

    # Uninstall MetalLB if requested
    if metallb_enabled:
        _uninstall_metallb()
