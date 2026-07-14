"""KAOS system commands."""

import subprocess
import sys

import typer
from typer.core import TyperGroup

from kaos_cli.system.install import install_command, uninstall_command
from kaos_cli.system.create_rbac import create_rbac_command
from kaos_cli.system.status import status_command
from kaos_cli.install import (
    AGENT_AUTH_MODES,
    USER_AUTH_MODES,
    DEFAULT_AGENT_AUTH_MODE,
    DEFAULT_USER_AUTH_MODE,
    DEFAULT_RELEASE_NAME,
    MONITORING_BACKENDS,
    _expand_auth_flags,
    _default_auth_admin_url,
    _default_auth_issuer,
    _default_user_auth_issuer,
    DEFAULT_USER_AUTH_CLIENT_ID,
    DEFAULT_USER_AUTH_REALM,
)
from kaos_cli.config import load_config, save_config
from kaos_cli.system.runtimes import runtimes_command
from kaos_cli.utils import DEFAULT_MONITORING_BACKEND, preprocess_optional_value_flag


class _SystemGroup(TyperGroup):
    """Custom Group that allows --monitoring-enabled without a value (defaults to signoz)."""

    def get_command(self, ctx, cmd_name):
        cmd = super().get_command(ctx, cmd_name)
        if cmd and cmd_name in ("install", "uninstall"):
            original_parse = cmd.parse_args

            def patched_parse(ctx, args):
                for flag in ("--agent-auth-enabled", "--user-auth-enabled"):
                    if args.count(flag) > 1:
                        raise typer.BadParameter(f"{flag} may only be specified once")
                args = preprocess_optional_value_flag(
                    args, "--monitoring-enabled", DEFAULT_MONITORING_BACKEND
                )
                args = preprocess_optional_value_flag(
                    args, "--agent-auth-enabled", DEFAULT_AGENT_AUTH_MODE
                )
                args = preprocess_optional_value_flag(
                    args, "--user-auth-enabled", DEFAULT_USER_AUTH_MODE
                )
                return original_parse(ctx, args)

            cmd.parse_args = patched_parse
        return cmd


app = typer.Typer(
    cls=_SystemGroup,
    help="System management commands for KAOS operator.",
    no_args_is_help=True,
)


@app.command(name="access-control")
def access_control(
    turn_on: bool = typer.Option(False, "--on", help="Start access control."),
    turn_off: bool = typer.Option(False, "--off", help="Stop access control."),
    namespace: str = typer.Option("kaos-system", "--namespace", "-n"),
) -> None:
    """Start or stop the access-control service."""
    if turn_on == turn_off:
        typer.echo("Error: specify exactly one of --on or --off", err=True)
        raise typer.Exit(1)
    state = "on" if turn_on else "off"
    replicas = "2" if turn_on else "0"
    result = subprocess.run(
        [
            "kubectl",
            "scale",
            "deployment/kaos-pdp",
            "-n",
            namespace,
            f"--replicas={replicas}",
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        typer.echo(result.stderr.strip() or "Error: unable to scale access control", err=True)
        raise typer.Exit(result.returncode)
    rollout = subprocess.run(
        [
            "kubectl",
            "rollout",
            "status",
            "deployment/kaos-pdp",
            "-n",
            namespace,
            "--timeout=60s",
        ],
        capture_output=True,
        text=True,
    )
    if rollout.returncode != 0:
        typer.echo(rollout.stderr.strip() or "Error: access-control rollout timed out", err=True)
        raise typer.Exit(rollout.returncode)
    typer.echo(f"✓ access-control {state}")


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
        help="Set Helm values directly (repeatable). Escape hatch for any chart "
        "value not exposed as a dedicated flag, e.g. advanced security overrides "
        "under security.agentAuth.*",
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
        "an authentication flag.",
    ),
    gateway_strict: bool = typer.Option(
        False,
        "--gateway-strict",
        help="Allow application traffic only through the gateway.",
    ),
    authz_enabled: bool = typer.Option(
        False,
        "--authz-enabled",
        help="Enable fail-closed gateway access-control enforcement.",
    ),
    agent_auth: str | None = typer.Option(
        None,
        "--agent-auth",
        help="Agent identity mode: serviceaccount|oidc|keycloak.",
    ),
    user_auth: str | None = typer.Option(
        None,
        "--user-auth",
        help="User identity mode: keycloak or none.",
    ),
    create_cli_config: bool = typer.Option(
        False,
        "--create-cli-config",
        help="Write a KAOS CLI config after a successful install.",
    ),
    config_path_override: str | None = typer.Option(
        None,
        "--config-path",
        help="Path written by --create-cli-config (default: ./.kaos-config.yaml).",
    ),
    metallb_enabled: bool = typer.Option(
        False,
        "--metallb-enabled",
        help="Install MetalLB for LoadBalancer support (KIND/bare-metal clusters).",
    ),
    pgvector_memory_enabled: bool = typer.Option(
        False,
        "--pgvector-memory-enabled",
        help="Provision a development pgvector Postgres for external-mode MemoryStores (dev-only).",
    ),
    token_exchange_enabled: bool = typer.Option(
        False,
        "--token-exchange-enabled",
        help="Enable delegated third-party token exchange. Requires Keycloak agent "
        "identity, the Keycloak user plane, and a self-managed AIB release.",
    ),
    agent_auth_enabled: str | None = typer.Option(
        None,
        "--agent-auth-enabled",
        help=f"Enable agent authentication. Options: {', '.join(AGENT_AUTH_MODES)}. "
        f"Defaults to {DEFAULT_AGENT_AUTH_MODE} when passed without a value.",
    ),
    user_auth_enabled: str | None = typer.Option(
        None,
        "--user-auth-enabled",
        help=f"Enable user authentication. Options: {', '.join(USER_AUTH_MODES)}. "
        f"Defaults to {DEFAULT_USER_AUTH_MODE} when passed without a value.",
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
        help="Namespace for the identity broker (advanced/dev).",
    ),
    keycloak_namespace: str = typer.Option(
        "keycloak",
        "--keycloak-namespace",
        hidden=True,
        help="Namespace for the user identity provider (advanced/dev).",
    ),
    aib_chart_path: str | None = typer.Option(
        None,
        "--aib-chart-path",
        hidden=True,
        help="Path to a local identity broker Helm chart to install (unpublished/dev "
        "path). Used with --agent-auth-enabled aib.",
    ),
    aib_values_path: str | None = typer.Option(
        None,
        "--aib-values",
        hidden=True,
        help="Values file for the identity broker chart (advanced/dev).",
    ),
    keycloak_chart_path: str | None = typer.Option(
        None,
        "--keycloak-chart-path",
        hidden=True,
        help="Path to a local Keycloak Helm chart to install. When omitted, a "
        "self-contained dev deployment is applied instead (advanced/dev).",
    ),
) -> None:
    """Install the KAOS operator using Helm."""
    if monitoring_enabled is not None and monitoring_enabled not in MONITORING_BACKENDS:
        typer.echo(
            f"Error: Invalid monitoring backend '{monitoring_enabled}'. Options: {', '.join(MONITORING_BACKENDS)}",
            err=True,
        )
        raise typer.Exit(1)

    if agent_auth_enabled is not None and agent_auth is not None:
        typer.echo("Error: use only one of --agent-auth and --agent-auth-enabled", err=True)
        raise typer.Exit(1)
    if user_auth_enabled is not None and user_auth is not None:
        typer.echo("Error: use only one of --user-auth and --user-auth-enabled", err=True)
        raise typer.Exit(1)
    if agent_auth not in (None, "serviceaccount", "oidc", "keycloak"):
        typer.echo(
            "Error: --agent-auth must be serviceaccount, oidc, or keycloak", err=True
        )
        raise typer.Exit(1)
    if user_auth not in (None, "keycloak", "none"):
        typer.echo("Error: --user-auth must be keycloak or none", err=True)
        raise typer.Exit(1)

    selected_agent_auth = (
        {
            "serviceaccount": "service-account",
            "oidc": "keycloak",
            "keycloak": "keycloak",
        }.get(agent_auth)
        if agent_auth is not None
        else agent_auth_enabled
    )
    selected_user_auth = user_auth if user_auth is not None else user_auth_enabled

    auth_kwargs: dict = {}
    if token_exchange_enabled:
        if selected_agent_auth not in (None, "keycloak"):
            typer.echo(
                "Error: --token-exchange-enabled requires "
                "--agent-auth-enabled keycloak; service-account-only and AIB "
                "identity postures cannot re-mint user tokens.",
                err=True,
            )
            raise typer.Exit(1)
        if selected_user_auth not in (None, "keycloak"):
            typer.echo(
                "Error: --token-exchange-enabled requires "
                "--user-auth-enabled keycloak.",
                err=True,
            )
            raise typer.Exit(1)
        if not aib_chart_path:
            typer.echo(
                "Error: --token-exchange-enabled requires --aib-chart-path so "
                "the self-managed AIB release can be installed with ext_proc.",
                err=True,
            )
            raise typer.Exit(1)

    if (
        selected_agent_auth is not None
        or selected_user_auth is not None
        or token_exchange_enabled
        or authz_enabled
    ):
        agent_mode = selected_agent_auth or (
            "keycloak" if token_exchange_enabled else DEFAULT_AGENT_AUTH_MODE
        )
        user_mode = selected_user_auth or (
            "none" if authz_enabled else DEFAULT_USER_AUTH_MODE
        )
        if agent_mode not in AGENT_AUTH_MODES:
            typer.echo(
                f"Error: Invalid agent auth mode '{agent_mode}'. Options: "
                f"{', '.join(AGENT_AUTH_MODES)}",
                err=True,
            )
            raise typer.Exit(1)
        if user_mode not in USER_AUTH_MODES:
            typer.echo(
                f"Error: Invalid user auth mode '{user_mode}'. Options: "
                f"{', '.join(USER_AUTH_MODES)}",
                err=True,
            )
            raise typer.Exit(1)
        auth_kwargs = _expand_auth_flags(agent_mode, user_mode, namespace)

    call_kwargs = dict(
        namespace=namespace,
        release_name=release_name,
        version=version,
        set_values=list(set_values),
        wait=wait,
        monitoring_enabled=monitoring_enabled,
        gateway_enabled=gateway_enabled,
        metallb_enabled=metallb_enabled,
        pgvector_memory_enabled=pgvector_memory_enabled,
        token_exchange_enabled=token_exchange_enabled,
        chart_path=chart_path,
        auth_namespace=auth_namespace,
        keycloak_namespace=keycloak_namespace,
        keycloak_release="keycloak",
        aib_chart_path=aib_chart_path,
        aib_values_path=aib_values_path,
        keycloak_chart_path=keycloak_chart_path,
        gateway_api_strict=gateway_api_strict or gateway_strict,
    )
    call_kwargs.update(auth_kwargs)
    install_command(**call_kwargs)

    if create_cli_config:
        output_path = config_path_override or ".kaos-config.yaml"
        cli_config = load_config(output_path)
        cli_config["namespace"] = namespace
        if gateway_enabled or auth_kwargs.get("gateway_enabled"):
            cli_config["gateway"] = {
                "address": f"http://kaos-gateway.{namespace}.svc.cluster.local",
                "through_gateway": True,
            }
        if selected_user_auth == "keycloak" or auth_kwargs.get("user_auth"):
            cli_config["auth"] = {
                "issuer": _default_user_auth_issuer(keycloak_namespace, "keycloak"),
                "client_id": DEFAULT_USER_AUTH_CLIENT_ID,
                "realm": DEFAULT_USER_AUTH_REALM,
                "broker_url": _default_auth_issuer(auth_namespace, "aib"),
                "broker_admin_url": _default_auth_admin_url(auth_namespace, "aib"),
            }
        path = save_config(cli_config, output_path)
        typer.echo(f"✓ wrote CLI config {path}")


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
    pgvector_memory_enabled: bool = typer.Option(
        False,
        "--pgvector-memory-enabled",
        help="Also uninstall the development pgvector Postgres.",
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
        pgvector_memory_enabled=pgvector_memory_enabled,
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
