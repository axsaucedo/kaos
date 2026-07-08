"""KAOS system commands."""

import subprocess
import sys

import typer
from typer.core import TyperGroup

from kaos_cli.system.install import install_command, uninstall_command
from kaos_cli.system.create_rbac import create_rbac_command
from kaos_cli.system.status import status_command
from kaos_cli.install import (
    DEFAULT_FULL_AUTH_PRESET,
    DEFAULT_RELEASE_NAME,
    FULL_AUTH_KAOS_DEMO,
    FULL_AUTH_KEYCLOAK_AIB,
    FULL_AUTH_PRESETS,
    MONITORING_BACKENDS,
    _expand_full_auth_preset,
)
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
                args = preprocess_optional_value_flag(
                    args, "--full-auth-enabled", DEFAULT_FULL_AUTH_PRESET
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
        help="Set Helm values directly (can be used multiple times). Escape hatch "
        "for any chart value not exposed as a dedicated flag.",
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
        help="Install Gateway API (Envoy Gateway) and configure routing. Implied by "
        "--full-auth-enabled.",
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
    full_auth_enabled: str | None = typer.Option(
        None,
        "--full-auth-enabled",
        help="Enable an end-to-end security posture. Options: "
        f"'{FULL_AUTH_KEYCLOAK_AIB}' (default; full Keycloak user identity + identity "
        "broker with token exchange + verified OPA authorization) or "
        f"'{FULL_AUTH_KAOS_DEMO}' (self-contained demo; KAOS-projected policy "
        "ConfigMap, header-trusted agent JWT, no external IdP/broker). The flag may "
        "be passed without a value to select the default. Implies --gateway-enabled.",
    ),
    gateway_api_strict: bool = typer.Option(
        False,
        "--gateway-api-strict/--no-gateway-api-strict",
        help="Enable gateway-only strict traffic: NetworkPolicy isolation and gateway "
        "routing together, independent of authorization. Makes the Envoy Gateway the "
        "only application path between workloads. Enforcement requires a CNI that "
        "enforces NetworkPolicy (e.g. Calico).",
    ),
    chart_path: str | None = typer.Option(
        None,
        "--chart-path",
        help="Path to local operator Helm chart directory (for development).",
    ),
    auth_namespace: str = typer.Option(
        "aib-system",
        "--auth-namespace",
        hidden=True,
        help="Namespace for the identity broker (advanced).",
    ),
    keycloak_namespace: str = typer.Option(
        "keycloak",
        "--keycloak-namespace",
        hidden=True,
        help="Namespace for the user identity provider (advanced).",
    ),
    aib_chart_path: str | None = typer.Option(
        None,
        "--aib-chart-path",
        hidden=True,
        help="Path to a local identity broker Helm chart to install (unpublished/dev "
        "path). Required to install the broker in-cluster for the "
        f"{FULL_AUTH_KEYCLOAK_AIB} preset.",
    ),
    aib_values_path: str | None = typer.Option(
        None,
        "--aib-values",
        hidden=True,
        help="Values file for the identity broker chart (advanced).",
    ),
    keycloak_chart_path: str | None = typer.Option(
        None,
        "--keycloak-chart-path",
        hidden=True,
        help="Path to a local Keycloak Helm chart to install. When omitted, a "
        "self-contained dev deployment is applied instead (advanced).",
    ),
    auth_enabled: bool = typer.Option(
        False,
        "--auth-enabled/--no-auth-enabled",
        hidden=True,
        help="Advanced: enable agent-auth wiring directly without a preset.",
    ),
    ext_authz_url: str | None = typer.Option(
        None, "--ext-authz-url", hidden=True, help="Advanced: ext_authz backend."
    ),
    auth_issuer: str | None = typer.Option(
        None, "--auth-issuer", hidden=True, help="Advanced: broker issuer URL."
    ),
    token_exchange: bool = typer.Option(
        True,
        "--token-exchange/--no-token-exchange",
        hidden=True,
        help="Advanced: RFC 8693 token-exchange path.",
    ),
    ext_proc_url: str | None = typer.Option(
        None,
        "--ext-proc-url",
        hidden=True,
        help="Advanced: token-exchange ext_proc backend.",
    ),
    user_auth: bool = typer.Option(
        True,
        "--user-auth/--no-user-auth",
        hidden=True,
        help="Advanced: install the user identity provider (Keycloak).",
    ),
    user_auth_issuer: str | None = typer.Option(
        None, "--user-auth-issuer", hidden=True, help="Advanced: user-auth OIDC issuer."
    ),
    user_auth_audience: str = typer.Option(
        "kaos",
        "--user-auth-audience",
        hidden=True,
        help="Advanced: user token audience.",
    ),
    network_policy: bool = typer.Option(
        True,
        "--network-policy/--no-network-policy",
        hidden=True,
        help="Advanced: generate bypass-prevention NetworkPolicies.",
    ),
    network_policy_egress: bool = typer.Option(
        False,
        "--network-policy-egress/--no-network-policy-egress",
        hidden=True,
        help="Advanced: add egress default-deny to NetworkPolicies.",
    ),
    gateway_routing: bool = typer.Option(
        False,
        "--gateway-routing/--no-gateway-routing",
        hidden=True,
        help="Advanced: route internal traffic through the gateway.",
    ),
    gateway_host: str | None = typer.Option(
        None,
        "--gateway-host",
        hidden=True,
        help="Advanced: in-cluster gateway host[:port].",
    ),
    tls_mode: str | None = typer.Option(
        None,
        "--tls-mode",
        hidden=True,
        help="Advanced: gateway HTTPS termination mode.",
    ),
    tls_issuer_name: str | None = typer.Option(
        None,
        "--tls-issuer-name",
        hidden=True,
        help="Advanced: cert-manager issuer name.",
    ),
    tls_issuer_kind: str = typer.Option(
        "ClusterIssuer",
        "--tls-issuer-kind",
        hidden=True,
        help="Advanced: cert-manager issuer kind.",
    ),
    tls_secret_name: str | None = typer.Option(
        None,
        "--tls-secret-name",
        hidden=True,
        help="Advanced: existing TLS Secret name.",
    ),
    authz_provider: str | None = typer.Option(
        None,
        "--authz-provider",
        hidden=True,
        help="Advanced: authorization provider (kaos|aib).",
    ),
    authz_gateway_extension: str | None = typer.Option(
        None,
        "--authz-gateway-extension",
        hidden=True,
        help="Advanced: enforcement extension (ext_proc|ext_authz).",
    ),
    agent_jwt_verification: str | None = typer.Option(
        None,
        "--agent-jwt-verification",
        hidden=True,
        help="Advanced: agent JWT trust (skip|verified).",
    ),
    policy_data_source: str | None = typer.Option(
        None,
        "--policy-data-source",
        hidden=True,
        help="Advanced: policy data author (automated|manual|external).",
    ),
    policy_rego_override: bool = typer.Option(
        False,
        "--policy-rego-override",
        hidden=True,
        help="Advanced: operator owns policy.rego only, admin authors grant data.",
    ),
    admin_url: str | None = typer.Option(
        None,
        "--admin-url",
        hidden=True,
        help="Advanced: identity broker admin API URL.",
    ),
    policy_configmap_name: str | None = typer.Option(
        None,
        "--policy-configmap-name",
        hidden=True,
        help="Advanced: policy ConfigMap name.",
    ),
    policy_configmap_namespace: str | None = typer.Option(
        None,
        "--policy-configmap-namespace",
        hidden=True,
        help="Advanced: policy ConfigMap namespace.",
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

    auth_kwargs: dict = {}
    if full_auth_enabled is not None:
        if full_auth_enabled not in FULL_AUTH_PRESETS:
            typer.echo(
                f"Error: Invalid full-auth preset '{full_auth_enabled}'. Options: "
                f"{', '.join(FULL_AUTH_PRESETS)}",
                err=True,
            )
            raise typer.Exit(1)
        # The gateway is the enforcement point for every auth posture, so ensure
        # it is installed even if --gateway-enabled was not passed explicitly.
        gateway_enabled = True
        auth_kwargs = _expand_full_auth_preset(full_auth_enabled)

    call_kwargs = dict(
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
        auth_namespace=auth_namespace,
        keycloak_namespace=keycloak_namespace,
        keycloak_release="keycloak",
        aib_chart_path=aib_chart_path,
        aib_values_path=aib_values_path,
        keycloak_chart_path=keycloak_chart_path,
        gateway_api_strict=gateway_api_strict,
        auth_enabled=auth_enabled,
        ext_authz_url=ext_authz_url,
        auth_issuer=auth_issuer,
        token_exchange=token_exchange,
        ext_proc_url=ext_proc_url,
        user_auth=user_auth,
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
        authz_provider=authz_provider,
        authz_gateway_extension=authz_gateway_extension,
        agent_jwt_verification=agent_jwt_verification,
        policy_data_source=policy_data_source,
        policy_rego_override=policy_rego_override,
        admin_url=admin_url,
        policy_configmap_name=policy_configmap_name,
        policy_configmap_namespace=policy_configmap_namespace,
    )
    # Preset values take precedence over the advanced flag defaults.
    call_kwargs.update(auth_kwargs)
    install_command(**call_kwargs)


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
