"""KAOS system commands."""

import subprocess
import sys

import typer
from typer.core import TyperGroup

from kaos_cli.system.install import install_command, uninstall_command
from kaos_cli.system.create_rbac import create_rbac_command
from kaos_cli.system.status import status_command
from kaos_cli.install import DEFAULT_RELEASE_NAME, MONITORING_BACKENDS
from kaos_cli.system.runtimes import runtimes_command
from kaos_cli.utils import DEFAULT_MONITORING_BACKEND, preprocess_optional_value_flag


class _SystemGroup(TyperGroup):
    """Custom Group that allows --monitoring-enabled without a value (defaults to signoz)."""

    def get_command(self, ctx, cmd_name):
        cmd = super().get_command(ctx, cmd_name)
        if cmd and cmd_name in ("install", "uninstall"):
            original_parse = cmd.parse_args

            def patched_parse(ctx, args):
                args = preprocess_optional_value_flag(
                    args, "--monitoring-enabled", DEFAULT_MONITORING_BACKEND
                )
                return original_parse(ctx, args)

            cmd.parse_args = patched_parse
        return cmd


app = typer.Typer(
    cls=_SystemGroup,
    help="System management commands for KAOS operator.",
    no_args_is_help=True,
)


@app.command(name="install")
def install(
    namespace: str = typer.Option(
        "kaos-system",
        "--namespace",
        "-n",
        help="Kubernetes namespace to install into.",
    ),
    release_name: str = typer.Option(
        DEFAULT_RELEASE_NAME,
        "--release-name",
        help="Helm release name.",
    ),
    version: str = typer.Option(
        None,
        "--version",
        help="Chart version to install. Defaults to latest.",
    ),
    set_values: list[str] = typer.Option(
        [],
        "--set",
        help="Set Helm values (can be used multiple times).",
    ),
    wait: bool = typer.Option(
        False,
        "--wait",
        help="Wait for pods to be ready before returning.",
    ),
    monitoring_enabled: str | None = typer.Option(
        None,
        "--monitoring-enabled",
        help=f"Install monitoring stack and enable telemetry. Options: {', '.join(MONITORING_BACKENDS)}.",
    ),
    gateway_enabled: bool = typer.Option(
        False,
        "--gateway-enabled",
        help="Install Gateway API (Envoy Gateway) and configure routing.",
    ),
    metallb_enabled: bool = typer.Option(
        False,
        "--metallb-enabled",
        help="Install MetalLB for LoadBalancer support (KIND/bare-metal clusters).",
    ),
    redis_enabled: bool = typer.Option(
        False,
        "--redis-enabled",
        help="Enable Redis for distributed agent memory.",
    ),
    chart_path: str | None = typer.Option(
        None,
        "--chart-path",
        help="Path to local Helm chart directory (for development). Uses published chart if not set.",
    ),
    auth_enabled: bool = typer.Option(
        False,
        "--auth-enabled",
        help="Enable agent authentication: wire the operator to the identity broker, "
        "mount per-agent credentials, and optionally install the broker and sync service.",
    ),
    auth_namespace: str = typer.Option(
        "aib-system",
        "--auth-namespace",
        help="Namespace for the identity broker and sync service.",
    ),
    ext_authz_url: str | None = typer.Option(
        None,
        "--ext-authz-url",
        help="Override the access-check gRPC backend host:port. Defaults to the "
        "conventional service in the auth namespace.",
    ),
    auth_issuer: str | None = typer.Option(
        None,
        "--auth-issuer",
        help="Override the broker issuer URL propagated to agent pods. Defaults to the "
        "broker enduser service in the auth namespace.",
    ),
    token_exchange: bool = typer.Option(
        True,
        "--token-exchange/--no-token-exchange",
        help="Enable the RFC 8693 token-exchange path: deploy the broker ExtProc "
        "component and wire the gateway ext_proc backend. Effective only with "
        "--auth-enabled.",
    ),
    ext_proc_url: str | None = typer.Option(
        None,
        "--ext-proc-url",
        help="Override the token-exchange ext_proc gRPC backend host:port. Defaults "
        "to the broker ExtProc service in the auth namespace.",
    ),
    aib_chart_path: str | None = typer.Option(
        None,
        "--aib-chart-path",
        help="Path to a local identity broker Helm chart to install (unpublished/dev path).",
    ),
    aib_values_path: str | None = typer.Option(
        None,
        "--aib-values",
        help="Values file for the identity broker chart (e.g. the dev preset).",
    ),
    sync_chart_path: str | None = typer.Option(
        None,
        "--sync-chart-path",
        help="Path to the sync service Helm chart to deploy.",
    ),
    sync_image_repository: str | None = typer.Option(
        None,
        "--sync-image-repository",
        help="Override the sync service image repository (for local/dev images).",
    ),
    sync_image_tag: str | None = typer.Option(
        None,
        "--sync-image-tag",
        help="Override the sync service image tag (for local/dev images).",
    ),
    user_auth: bool = typer.Option(
        True,
        "--user-auth/--no-user-auth",
        help="Install the human user identity provider (Keycloak) and wire user "
        "subject-token validation at the gateway. Effective only with --auth-enabled.",
    ),
    keycloak_namespace: str = typer.Option(
        "keycloak",
        "--keycloak-namespace",
        help="Namespace for the user identity provider (Keycloak).",
    ),
    keycloak_chart_path: str | None = typer.Option(
        None,
        "--keycloak-chart-path",
        help="Path to a local Keycloak Helm chart to install. When omitted, a "
        "self-contained dev deployment is applied instead.",
    ),
    user_auth_issuer: str | None = typer.Option(
        None,
        "--user-auth-issuer",
        help="Override the user-auth OIDC issuer URL. Defaults to the bootstrapped "
        "Keycloak realm in the keycloak namespace.",
    ),
    user_auth_audience: str = typer.Option(
        "kaos",
        "--user-auth-audience",
        help="Expected audience claim for user subject tokens.",
    ),
    network_policy: bool = typer.Option(
        True,
        "--network-policy/--no-network-policy",
        help="Generate NetworkPolicies that deny direct workload-to-workload traffic "
        "so the Envoy Gateway cannot be bypassed. Effective only with --auth-enabled.",
    ),
    network_policy_egress: bool = typer.Option(
        False,
        "--network-policy-egress/--no-network-policy-egress",
        help="Add egress default-deny rules to generated NetworkPolicies. Effective "
        "only with --auth-enabled and --network-policy.",
    ),
    gateway_routing: bool = typer.Option(
        False,
        "--gateway-routing/--no-gateway-routing",
        help="Route internal agent->ModelAPI/MCP/peer traffic through the gateway so "
        "gateway authentication and authorization apply to it. Effective only with "
        "--auth-enabled.",
    ),
    gateway_host: str | None = typer.Option(
        None,
        "--gateway-host",
        help="In-cluster host[:port] of the Envoy Gateway used for gateway routing. "
        "Defaults to the Gateway resource's status address.",
    ),
    tls_mode: str | None = typer.Option(
        None,
        "--tls-mode",
        help="Enable HTTPS termination on the gateway. One of: selfSigned, "
        "certManager, provided.",
    ),
    tls_issuer_name: str | None = typer.Option(
        None,
        "--tls-issuer-name",
        help="cert-manager Issuer/ClusterIssuer name (with --tls-mode certManager).",
    ),
    tls_issuer_kind: str = typer.Option(
        "ClusterIssuer",
        "--tls-issuer-kind",
        help="cert-manager issuer kind: Issuer or ClusterIssuer.",
    ),
    tls_secret_name: str | None = typer.Option(
        None,
        "--tls-secret-name",
        help="Existing kubernetes.io/tls Secret name (with --tls-mode provided).",
    ),
) -> None:
    """Install the KAOS operator using Helm."""
    # Default to signoz if flag provided without value
    if monitoring_enabled is not None and monitoring_enabled not in MONITORING_BACKENDS:
        typer.echo(
            f"Error: Invalid monitoring backend '{monitoring_enabled}'. Options: {', '.join(MONITORING_BACKENDS)}",
            err=True,
        )
        raise typer.Exit(1)
    install_command(
        namespace=namespace,
        release_name=release_name,
        version=version,
        set_values=list(set_values),
        wait=wait,
        monitoring_enabled=monitoring_enabled,
        gateway_enabled=gateway_enabled,
        metallb_enabled=metallb_enabled,
        redis_enabled=redis_enabled,
        chart_path=chart_path,
        auth_enabled=auth_enabled,
        auth_namespace=auth_namespace,
        ext_authz_url=ext_authz_url,
        auth_issuer=auth_issuer,
        token_exchange=token_exchange,
        ext_proc_url=ext_proc_url,
        aib_chart_path=aib_chart_path,
        aib_values_path=aib_values_path,
        sync_chart_path=sync_chart_path,
        sync_image_repository=sync_image_repository,
        sync_image_tag=sync_image_tag,
        user_auth=user_auth,
        keycloak_namespace=keycloak_namespace,
        keycloak_release="keycloak",
        keycloak_chart_path=keycloak_chart_path,
        user_auth_issuer=user_auth_issuer,
        user_auth_audience=user_auth_audience,
        network_policy=network_policy,
        network_policy_egress=network_policy_egress,
        gateway_routing=gateway_routing,
        gateway_host=gateway_host,
        tls_mode=tls_mode,
        tls_issuer_name=tls_issuer_name,
        tls_issuer_kind=tls_issuer_kind,
        tls_secret_name=tls_secret_name,
    )


@app.command(name="uninstall")
def uninstall(
    namespace: str = typer.Option(
        "kaos-system",
        "--namespace",
        "-n",
        help="Kubernetes namespace to uninstall from.",
    ),
    release_name: str = typer.Option(
        DEFAULT_RELEASE_NAME,
        "--release-name",
        help="Helm release name.",
    ),
    monitoring_enabled: str | None = typer.Option(
        None,
        "--monitoring-enabled",
        help=f"Also uninstall monitoring stack. Options: {', '.join(MONITORING_BACKENDS)}.",
    ),
    gateway_enabled: bool = typer.Option(
        False,
        "--gateway-enabled",
        help="Also uninstall Gateway API (Envoy Gateway).",
    ),
    metallb_enabled: bool = typer.Option(
        False,
        "--metallb-enabled",
        help="Also uninstall MetalLB.",
    ),
    redis_enabled: bool = typer.Option(
        False,
        "--redis-enabled",
        help="Also uninstall Redis.",
    ),
) -> None:
    """Uninstall the KAOS operator."""
    if monitoring_enabled is not None and monitoring_enabled not in MONITORING_BACKENDS:
        typer.echo(
            f"Error: Invalid monitoring backend '{monitoring_enabled}'. Options: {', '.join(MONITORING_BACKENDS)}",
            err=True,
        )
        raise typer.Exit(1)
    uninstall_command(
        namespace=namespace,
        release_name=release_name,
        monitoring_enabled=monitoring_enabled,
        gateway_enabled=gateway_enabled,
        metallb_enabled=metallb_enabled,
        redis_enabled=redis_enabled,
    )


@app.command(name="create-rbac")
def create_rbac(
    name: str = typer.Argument(..., help="Name for the ServiceAccount and Role."),
    namespace: str = typer.Option(
        None,
        "--namespace",
        "-n",
        help="Namespace for the ServiceAccount. Uses current context if not specified.",
    ),
    namespaces: list[str] = typer.Option(
        [],
        "--namespaces",
        help="Additional namespaces for RoleBindings (can be used multiple times).",
    ),
    resources: list[str] = typer.Option(
        [],
        "--resources",
        help="Kubernetes resources to grant access to.",
    ),
    verbs: list[str] = typer.Option(
        [],
        "--verbs",
        help="Kubernetes verbs to grant (comma-separated or repeated).",
    ),
    read_only: bool = typer.Option(
        False,
        "--read-only",
        help="Grant only get/list/watch permissions.",
    ),
    cluster_wide: bool = typer.Option(
        False,
        "--cluster-wide",
        help="Create ClusterRole and ClusterRoleBinding instead of Role.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Only print YAML without applying to cluster.",
    ),
) -> None:
    """Create RBAC resources for MCPServer Kubernetes runtime."""
    # Split comma-separated values for resources and verbs
    expanded_resources = []
    for r in resources:
        expanded_resources.extend(r.split(","))

    expanded_verbs = []
    for v in verbs:
        expanded_verbs.extend(v.split(","))

    create_rbac_command(
        name=name,
        namespace=namespace,
        namespaces=list(namespaces),
        resources=expanded_resources,
        verbs=expanded_verbs,
        read_only=read_only,
        cluster_wide=cluster_wide,
        dry_run=dry_run,
    )


@app.command(name="status")
def status(
    namespace: str = typer.Option(
        "kaos-system",
        "--namespace",
        "-n",
        help="Namespace where KAOS operator is installed.",
    ),
) -> None:
    """Show KAOS system status."""
    status_command(namespace=namespace)


@app.command(name="runtimes")
def runtimes(
    namespace: str = typer.Option(
        "kaos-system",
        "--namespace",
        "-n",
        help="Namespace where KAOS operator is installed.",
    ),
) -> None:
    """List available MCP runtimes."""
    runtimes_command(namespace=namespace)


@app.command(name="working-namespace")
def working_namespace(
    namespace: str = typer.Argument(..., help="Namespace to switch to."),
) -> None:
    """Set the working namespace for kubectl.

    Creates the namespace if it doesn't exist and switches kubectl context.
    """
    # Create namespace if it doesn't exist
    result = subprocess.run(
        ["kubectl", "create", "namespace", namespace],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        typer.echo(f"✅ Created namespace '{namespace}'")
    elif "already exists" in result.stderr:
        typer.echo(f"📦 Namespace '{namespace}' already exists")
    else:
        typer.echo(f"Error: {result.stderr}", err=True)
        sys.exit(result.returncode)

    # Get current context
    result = subprocess.run(
        ["kubectl", "config", "current-context"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        typer.echo(f"Error getting current context: {result.stderr}", err=True)
        sys.exit(result.returncode)
    current_context = result.stdout.strip()

    # Set namespace in current context
    result = subprocess.run(
        [
            "kubectl",
            "config",
            "set-context",
            current_context,
            "--namespace",
            namespace,
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        typer.echo(f"Error setting namespace: {result.stderr}", err=True)
        sys.exit(result.returncode)

    typer.echo(f"✅ Switched to namespace '{namespace}'")
