"""Gateway API and MetalLB installation helpers."""

import subprocess
import time

import typer

from . import (
    ENVOY_GATEWAY_VERSION, GATEWAY_CLASS_NAME, METALLB_VERSION,
)


def _root():
    """Resolve shared helpers through the public package for compatibility."""
    import kaos_cli.install as root

    return root
def _install_gateway_api(enable_backend: bool = False) -> bool:
    """Install Envoy Gateway (includes Gateway API CRDs) and create GatewayClass."""
    typer.echo(f"Installing Envoy Gateway ({ENVOY_GATEWAY_VERSION})...")

    # Pre-apply CRDs from the chart to handle field manager conflicts on re-installs
    crds_result = _root().run_helm_command(
        [
            "show",
            "crds",
            "oci://docker.io/envoyproxy/gateway-helm",
            "--version",
            ENVOY_GATEWAY_VERSION,
        ],
        check=False,
    )
    crd_pre_applied = False
    if crds_result.returncode == 0 and crds_result.stdout.strip():
        result = _root()._run_kubectl(
            ["apply", "--server-side", "--force-conflicts", "-f", "-"],
            check=False,
            input=crds_result.stdout,
        )
        if result.returncode == 0:
            crd_pre_applied = True
        else:
            # Stale CRDs with incompatible storedVersions — delete and let helm recreate
            typer.echo("  Cleaning up stale Gateway API CRDs...")
            _root()._run_kubectl(
                [
                    "delete",
                    "crd",
                    "--ignore-not-found",
                    "-l",
                    "gateway.networking.k8s.io/policy",
                ],
                check=False,
            )
            _root()._run_kubectl(
                [
                    "delete",
                    "crd",
                    "--ignore-not-found",
                    "gatewayclasses.gateway.networking.k8s.io",
                    "gateways.gateway.networking.k8s.io",
                    "httproutes.gateway.networking.k8s.io",
                    "grpcroutes.gateway.networking.k8s.io",
                    "referencegrants.gateway.networking.k8s.io",
                    "tcproutes.gateway.networking.k8s.io",
                    "tlsroutes.gateway.networking.k8s.io",
                    "udproutes.gateway.networking.k8s.io",
                    "backendtlspolicies.gateway.networking.k8s.io",
                ],
                check=False,
            )

    helm_args = [
        "upgrade",
        "--install",
        "envoy-gateway",
        "oci://docker.io/envoyproxy/gateway-helm",
        "--version",
        ENVOY_GATEWAY_VERSION,
        "--namespace",
        "envoy-gateway-system",
        "--create-namespace",
    ] + (["--skip-crds"] if crd_pre_applied else [])
    if enable_backend:
        helm_args.extend(
            ["--set", "config.envoyGateway.extensionApis.enableBackend=true"]
        )
    result = _root().run_helm_command(helm_args, check=False)
    if result.returncode != 0:
        typer.echo(f"Error installing Envoy Gateway: {result.stderr}", err=True)
        return False

    typer.echo("✅ Envoy Gateway installed")
    return True

def _wait_for_gateway_class() -> bool:
    """Create GatewayClass and wait for it to be accepted."""
    typer.echo("Creating GatewayClass...")
    gc_yaml = (
        "apiVersion: gateway.networking.k8s.io/v1\n"
        "kind: GatewayClass\n"
        "metadata:\n"
        f"  name: {GATEWAY_CLASS_NAME}\n"
        "spec:\n"
        "  controllerName: gateway.envoyproxy.io/gatewayclass-controller\n"
    )
    result = _root()._run_kubectl(["apply", "-f", "-"], check=False, input=gc_yaml)
    if result.returncode != 0:
        typer.echo(f"Error creating GatewayClass: {result.stderr}", err=True)
        return False

    typer.echo("Waiting for GatewayClass to be accepted...")
    for i in range(30):
        result = _root()._run_kubectl(
            [
                "get",
                "gatewayclass",
                GATEWAY_CLASS_NAME,
                "-o",
                'jsonpath={.status.conditions[?(@.type=="Accepted")].status}',
            ],
            check=False,
        )
        if result.stdout.strip() == "True":
            break
        time.sleep(2)
    else:
        typer.echo("Warning: GatewayClass not accepted after 60 seconds", err=True)
        return False

    typer.echo("✅ GatewayClass accepted")
    return True

def _uninstall_gateway_api() -> bool:
    """Uninstall Envoy Gateway."""
    typer.echo("Uninstalling Envoy Gateway...")
    result = _root().run_helm_command(
        ["uninstall", "envoy-gateway", "--namespace", "envoy-gateway-system"],
        check=False,
    )
    if result.returncode != 0 and "not found" not in result.stderr.lower():
        typer.echo(f"Warning: {result.stderr}", err=True)

    _root()._run_kubectl(
        ["delete", "gatewayclass", GATEWAY_CLASS_NAME, "--ignore-not-found"],
        check=False,
    )
    _root()._run_kubectl(
        ["delete", "namespace", "envoy-gateway-system", "--ignore-not-found"],
        check=False,
    )
    typer.echo("✅ Gateway API uninstalled")
    return True

def _install_metallb() -> bool:
    """Install MetalLB for LoadBalancer support (KIND/bare-metal clusters)."""
    typer.echo(f"Installing MetalLB ({METALLB_VERSION})...")
    result = _root()._run_kubectl(
        [
            "apply",
            "-f",
            f"https://raw.githubusercontent.com/metallb/metallb/{METALLB_VERSION}/config/manifests/metallb-native.yaml",
        ],
        check=False,
    )
    if result.returncode != 0:
        typer.echo(f"Error installing MetalLB: {result.stderr}", err=True)
        return False

    typer.echo("✅ MetalLB installed")
    return True

def _configure_metallb() -> bool:
    """Wait for MetalLB to be ready and configure IP address pool."""
    typer.echo("Waiting for MetalLB pods...")
    result = _root()._run_kubectl(
        [
            "wait",
            "--namespace",
            "metallb-system",
            "--for=condition=ready",
            "pod",
            "--selector=app=metallb",
            "--timeout=120s",
        ],
        check=False,
    )
    if result.returncode != 0:
        typer.echo(f"Warning: MetalLB pods not ready: {result.stderr}", err=True)

    typer.echo("Configuring MetalLB IP address pool...")
    try:
        # Get all IPAM subnets and find the IPv4 one
        net_result = subprocess.run(
            [
                "docker",
                "network",
                "inspect",
                "kind",
                "--format",
                "{{range .IPAM.Config}}{{.Subnet}} {{end}}",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        ip_start = "172.18.255.200"
        ip_end = "172.18.255.250"
        if net_result.returncode == 0 and net_result.stdout.strip():
            for subnet in net_result.stdout.strip().split():
                if "." in subnet and ":" not in subnet:  # IPv4 only
                    parts = subnet.split("/")[0].split(".")[:3]
                    prefix = ".".join(parts)
                    ip_start = f"{prefix}.200"
                    ip_end = f"{prefix}.250"
                    break

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
        result = _root()._run_kubectl(["apply", "-f", "-"], check=False, input=pool_yaml)
        if result.returncode != 0:
            typer.echo(
                f"Warning: Could not configure MetalLB pool: {result.stderr}", err=True
            )
        else:
            typer.echo(f"  IP range: {ip_start}-{ip_end}")
    except FileNotFoundError:
        typer.echo(
            "Warning: docker not found, skipping MetalLB IP pool configuration",
            err=True,
        )

    return True

def _uninstall_metallb() -> bool:
    """Uninstall MetalLB."""
    typer.echo("Uninstalling MetalLB...")
    _root()._run_kubectl(
        [
            "delete",
            "-f",
            f"https://raw.githubusercontent.com/metallb/metallb/{METALLB_VERSION}/config/manifests/metallb-native.yaml",
            "--ignore-not-found",
        ],
        check=False,
    )
    _root()._run_kubectl(
        ["delete", "namespace", "metallb-system", "--ignore-not-found"], check=False
    )
    typer.echo("✅ MetalLB uninstalled")
    return True
