"""KAOS install and uninstall commands for the Kubernetes operator."""

import shutil
import subprocess
import sys

import typer

import typer

# Helm chart repository URL (hosted on GitHub Pages)
HELM_REPO_URL = "https://axsaucedo.github.io/kaos/charts"
HELM_REPO_NAME = "kaos"
HELM_CHART_NAME = "kaos-operator"
DEFAULT_NAMESPACE = "kaos-system"
DEFAULT_RELEASE_NAME = "kaos"

# Gateway API defaults
ENVOY_GATEWAY_VERSION = "v1.4.6"
GATEWAY_CLASS_NAME = "envoy-gateway"

# MetalLB defaults
METALLB_VERSION = "v0.14.9"

# Development pgvector Postgres (opt-in, dev-only) for external-mode MemoryStores
PGVECTOR_IMAGE = "pgvector/pgvector:pg16"
PGVECTOR_NAME = "kaos-memory-pgvector"
PGVECTOR_SECRET_NAME = "kaos-memory-pgvector"
PGVECTOR_SECRET_KEY = "dsn"
PGVECTOR_DB = "kaos"
PGVECTOR_USER = "kaos"
PGVECTOR_PASSWORD = "kaos"

# Agent-auth (identity broker) defaults
DEFAULT_AUTH_NAMESPACE = "aib-system"
DEFAULT_AUTH_RELEASE = "aib"
DEFAULT_CREDENTIAL_SECRET_PREFIX = "kaos-aib"
AUTH_ENDUSER_PORT = 8000
AUTH_ADMIN_PORT = 14000
AUTH_EXTPROC_PORT = 50051


# Independent agent and user identity modes selected by the install flags.
AGENT_AUTH_MODES = ("service-account", "aib", "keycloak")
USER_AUTH_MODES = ("keycloak", "none")
DEFAULT_AGENT_AUTH_MODE = "service-account"
DEFAULT_USER_AUTH_MODE = "keycloak"
DEFAULT_POLICY_CONFIGMAP_NAME = "kaos-authz-policy"

# User-auth (human identity provider, Keycloak by default) defaults
DEFAULT_KEYCLOAK_NAMESPACE = "keycloak"
DEFAULT_KEYCLOAK_RELEASE = "keycloak"
DEFAULT_KEYCLOAK_IMAGE = "quay.io/keycloak/keycloak:26.0"
KEYCLOAK_HTTP_PORT = 8080
DEFAULT_USER_AUTH_REALM = "kaos"
DEFAULT_USER_AUTH_AUDIENCE = "kaos"
DEFAULT_USER_AUTH_CLIENT_ID = "kaos"
DEFAULT_TOKEN_EXCHANGE_AUDIENCE = "token-exchange-broker"
DEFAULT_OIDC_CREDENTIAL_SECRET_PREFIX = "kaos-oidc"
DEFAULT_OIDC_REGISTRATION_SECRET_NAME = "kaos-oidc-registration"
DEFAULT_OIDC_REGISTRATION_SECRET_KEY = "token"
DEFAULT_AGENT_AUTH_AUDIENCE = "kaos-gateway"
# Dev-only fixtures used to bootstrap a non-interactive test identity. These are
# intended exclusively for local/e2e validation, never for production installs.
DEFAULT_USER_AUTH_CLIENT_SECRET = "kaos-dev-secret"
DEFAULT_USER_AUTH_TEST_USER = "kaos-user"
DEFAULT_USER_AUTH_TEST_PASSWORD = "kaos-password"
DEFAULT_KEYCLOAK_ADMIN_USER = "admin"
DEFAULT_KEYCLOAK_ADMIN_PASSWORD = "admin"
# KAOS CRD names (for explicit install/uninstall)
KAOS_CRDS = [
    "agents.kaos.tools",
    "mcpservers.kaos.tools",
    "modelapis.kaos.tools",
]

MONITORING_BACKENDS = ("signoz", "jaeger")



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

def _run_kubectl(
    args: list[str], check: bool = True, **kwargs
) -> subprocess.CompletedProcess:
    """Run a kubectl command and return the result."""
    cmd = ["kubectl"] + args
    return subprocess.run(cmd, capture_output=True, text=True, check=check, **kwargs)


from .infra import (
    _configure_metallb, _install_gateway_api, _install_metallb,
    _uninstall_gateway_api, _uninstall_metallb, _wait_for_gateway_class,
)
from .observability import (
    _create_jaeger_ui_config, _get_otel_endpoint, _install_jaeger,
    _install_monitoring, _install_pgvector, _install_signoz, _pgvector_dsn,
    _pgvector_manifest, _uninstall_monitoring, _uninstall_pgvector,
)
from .auth import (
    _auth_broker_fullname, _bootstrap_keycloak_realm,
    _build_aib_broker_public_url_args, _build_auth_operator_args,
    _build_token_exchange_aib_args, _default_auth_admin_url,
    _default_auth_issuer, _default_user_auth_issuer, _install_aib,
    _install_keycloak, _keycloak_dev_manifests, _keycloak_realm_configmap_name,
    _keycloak_realm_json,
)


def _expand_auth_flags(agent_mode: str, user_mode: str, namespace: str) -> dict:
    """Expand agent and user auth modes into install_command auth kwargs."""
    base = {
        "auth_enabled": True,
        "gateway_enabled": True,
        "pdp_enabled": True,
        "network_policy": True,
        "gateway_routing": True,
        "policy_data_source": "automated",
        "policy_configmap_name": DEFAULT_POLICY_CONFIGMAP_NAME,
        "policy_configmap_namespace": namespace,
    }
    identity_provider = {
        "service-account": "serviceaccount",
        "aib": "aib",
        "keycloak": "oidc",
    }[agent_mode]
    result = {
        **base,
        "identity_provider": identity_provider,
        "user_auth": user_mode == "keycloak",
        "gateway_api_strict": user_mode == "keycloak",
    }
    if agent_mode == "keycloak":
        result.update(
            credential_secret_prefix=DEFAULT_OIDC_CREDENTIAL_SECRET_PREFIX,
            oidc_registration_secret_name=DEFAULT_OIDC_REGISTRATION_SECRET_NAME,
            oidc_registration_secret_key=DEFAULT_OIDC_REGISTRATION_SECRET_KEY,
        )
    return result

def install_command(
    namespace: str,
    release_name: str,
    version: str | None,
    set_values: list[str],
    wait: bool,
    monitoring_enabled: str | None = None,
    gateway_enabled: bool = False,
    metallb_enabled: bool = False,
    pgvector_memory_enabled: bool = False,
    token_exchange_enabled: bool = False,
    chart_path: str | None = None,
    auth_enabled: bool = False,
    auth_namespace: str = DEFAULT_AUTH_NAMESPACE,
    auth_release: str = DEFAULT_AUTH_RELEASE,
    identity_provider: str = "aib",
    pdp_enabled: bool = False,
    ext_authz_url: str | None = None,
    auth_issuer: str | None = None,
    credential_secret_prefix: str = DEFAULT_CREDENTIAL_SECRET_PREFIX,
    aib_chart_path: str | None = None,
    aib_values_path: str | None = None,
    user_auth: bool = True,
    keycloak_namespace: str = DEFAULT_KEYCLOAK_NAMESPACE,
    keycloak_release: str = DEFAULT_KEYCLOAK_RELEASE,
    keycloak_chart_path: str | None = None,
    user_auth_issuer: str | None = None,
    user_auth_audience: str = DEFAULT_USER_AUTH_AUDIENCE,
    network_policy: bool = True,
    network_policy_egress: bool = False,
    gateway_routing: bool = False,
    gateway_api_strict: bool = False,
    gateway_host: str | None = None,
    tls_mode: str | None = None,
    tls_issuer_name: str | None = None,
    tls_issuer_kind: str = "ClusterIssuer",
    tls_secret_name: str | None = None,
    policy_data_source: str | None = None,
    policy_rego_override: bool = False,
    admin_url: str | None = None,
    oidc_registration_secret_name: str = "",
    oidc_registration_secret_key: str = "",
    policy_configmap_name: str | None = None,
    policy_configmap_namespace: str | None = None,
) -> None:
    """Install the KAOS operator using Helm."""
    if not check_helm_installed():
        typer.echo("Error: helm is not installed. Please install helm first.", err=True)
        typer.echo("See: https://helm.sh/docs/intro/install/", err=True)
        sys.exit(1)

    # Phase 1: Kick off all infra installs (no waiting)
    if metallb_enabled:
        if not _install_metallb():
            typer.echo("Warning: MetalLB installation failed, continuing...", err=True)

    if gateway_enabled:
        if not _install_gateway_api(enable_backend=token_exchange_enabled):
            typer.echo(
                "Warning: Gateway API installation failed, continuing...", err=True
            )

    if monitoring_enabled:
        if not _install_monitoring(monitoring_enabled, namespace):
            typer.echo(
                "Warning: Monitoring installation failed, continuing...", err=True
            )

    if pgvector_memory_enabled:
        if not _install_pgvector(namespace):
            typer.echo(
                "Warning: pgvector Postgres installation failed, continuing...",
                err=True,
            )

    # Resolve the AIB issuer once for both token minting and every verifier.
    resolved_auth_issuer = ""
    if auth_enabled:
        if identity_provider == "aib":
            resolved_auth_issuer = auth_issuer or _default_auth_issuer(
                auth_namespace, auth_release
            )
        elif identity_provider == "oidc":
            resolved_auth_issuer = auth_issuer or _default_user_auth_issuer(
                keycloak_namespace, keycloak_release
            )
        if user_auth:
            user_auth_issuer = user_auth_issuer or _default_user_auth_issuer(
                keycloak_namespace, keycloak_release
            )

        # Install the identity broker from a local chart when provided (it is
        # unpublished, so a chart path is required to install it here).
        if (identity_provider == "aib" or token_exchange_enabled) and aib_chart_path:
            if token_exchange_enabled:
                keycloak_issuer = user_auth_issuer or _default_user_auth_issuer(
                    keycloak_namespace, keycloak_release
                )
                aib_extra_set = _build_token_exchange_aib_args(
                    auth_namespace,
                    auth_release,
                    keycloak_issuer,
                )
            else:
                aib_extra_set = _build_aib_broker_public_url_args(resolved_auth_issuer)
            if not _install_aib(
                auth_namespace,
                auth_release,
                aib_chart_path,
                aib_values_path,
                wait,
                extra_set=aib_extra_set,
            ):
                typer.echo(
                    "Warning: identity broker installation failed, continuing...",
                    err=True,
                )
        elif identity_provider == "aib":
            typer.echo(
                "Note: --aib-chart-path not provided; assuming the identity broker "
                f"is already installed in namespace '{auth_namespace}'.",
            )

        # In AIB mode the operator registers agents and provisions credentials;
        # ServiceAccount mode needs no external identity component.

        # Keycloak backs the user plane and the OIDC DCR agent mode. Install it
        # when either plane selects it.
        if user_auth or identity_provider == "oidc":
            if not _install_keycloak(
                keycloak_namespace,
                keycloak_release,
                DEFAULT_USER_AUTH_REALM,
                user_auth_audience,
                keycloak_chart_path,
                wait,
                token_exchange_enabled,
            ):
                typer.echo(
                    "Warning: Keycloak installation failed, continuing...", err=True
                )

    # Phase 2: Wait for infra that the operator depends on
    if gateway_enabled:
        _wait_for_gateway_class()

    if metallb_enabled:
        _configure_metallb()

    # Phase 3: Install operator chart
    typer.echo(f"Installing KAOS operator to namespace '{namespace}'...")

    # Determine chart reference: local path or published repo
    if chart_path:
        chart_ref = chart_path
        typer.echo(f"Using local chart: {chart_path}")
    else:
        typer.echo(f"Adding Helm repository '{HELM_REPO_NAME}'...")
        result = run_helm_command(
            ["repo", "add", HELM_REPO_NAME, HELM_REPO_URL, "--force-update"],
            check=False,
        )
        if result.returncode != 0 and "already exists" not in result.stderr:
            typer.echo(f"Warning: {result.stderr}", err=True)

        typer.echo("Updating Helm repositories...")
        run_helm_command(["repo", "update"], check=False)
        chart_ref = f"{HELM_REPO_NAME}/{HELM_CHART_NAME}"

    # Pre-apply CRDs via kubectl to handle field manager conflicts on re-installs
    typer.echo("Applying CRDs...")
    if chart_path:
        import pathlib

        crds_dir = pathlib.Path(chart_path) / "crds"
        if crds_dir.exists():
            result = _run_kubectl(
                ["apply", "--server-side", "--force-conflicts", "-f", str(crds_dir)],
                check=False,
            )
            if result.returncode != 0:
                typer.echo(f"Warning: CRD apply failed: {result.stderr}", err=True)
            elif result.stdout.strip():
                typer.echo(f"  {result.stdout.strip()}")
        else:
            typer.echo(f"Warning: CRDs directory not found: {crds_dir}", err=True)
    else:
        show_args = ["show", "crds", chart_ref]
        if version:
            show_args.extend(["--version", version])
        crds_result = run_helm_command(show_args, check=False)
        if crds_result.returncode == 0 and crds_result.stdout.strip():
            result = _run_kubectl(
                ["apply", "--server-side", "--force-conflicts", "-f", "-"],
                check=False,
                input=crds_result.stdout,
            )
            if result.returncode != 0:
                typer.echo(f"Warning: CRD apply failed: {result.stderr}", err=True)
            elif result.stdout.strip():
                typer.echo(f"  {result.stdout.strip()}")
        else:
            typer.echo(
                f"Warning: Could not extract CRDs (rc={crds_result.returncode}): "
                f"{crds_result.stderr}",
                err=True,
            )

    # Build helm install command
    helm_args = [
        "upgrade",
        "--install",
        release_name,
        chart_ref,
        "--namespace",
        namespace,
        "--create-namespace",
        "--skip-crds",
    ]

    if version:
        helm_args.extend(["--version", version])

    if wait:
        helm_args.append("--wait")

    for value in set_values:
        helm_args.extend(["--set", value])

    if monitoring_enabled:
        otel_endpoint = _get_otel_endpoint(monitoring_enabled, namespace)
        helm_args.extend(["--set", "telemetry.enabled=true"])
        helm_args.extend(["--set", f"telemetry.endpoint={otel_endpoint}"])

    if gateway_enabled:
        helm_args.extend(["--set", "gatewayAPI.enabled=true"])
        helm_args.extend(["--set", "gatewayAPI.createGateway=true"])
        helm_args.extend(["--set", f"gatewayAPI.gatewayClassName={GATEWAY_CLASS_NAME}"])

    if auth_enabled:
        resolved_user_issuer = (
            user_auth_issuer
            or _default_user_auth_issuer(keycloak_namespace, keycloak_release)
            if user_auth
            else ""
        )
        helm_args.extend(
            _build_auth_operator_args(
                ext_authz_url or "",
                resolved_auth_issuer,
                credential_secret_prefix,
                identity_provider=identity_provider,
                pdp_enabled=pdp_enabled,
                admin_url=(
                    (admin_url or _default_auth_admin_url(auth_namespace, auth_release))
                    if identity_provider == "aib"
                    else ""
                ),
                user_issuer=resolved_user_issuer,
                user_audience=user_auth_audience if user_auth else "",
                oidc_registration_secret_name=oidc_registration_secret_name,
                oidc_registration_secret_key=oidc_registration_secret_key,
                network_policy=network_policy,
                network_policy_egress=network_policy_egress,
                gateway_routing=gateway_routing,
                gateway_api_strict=gateway_api_strict,
                gateway_host=gateway_host or "",
                tls_mode=tls_mode or "",
                tls_issuer_name=tls_issuer_name or "",
                tls_issuer_kind=tls_issuer_kind,
                tls_secret_name=tls_secret_name or "",
                policy_data_source=policy_data_source or "",
                policy_rego_override=policy_rego_override,
                policy_configmap_name=policy_configmap_name or "",
                policy_configmap_namespace=policy_configmap_namespace or "",
            )
        )
        if token_exchange_enabled:
            helm_args.extend(
                [
                    "--set",
                    "security.tokenExchange.enabled=true",
                    "--set",
                    "security.tokenExchange.aib.adminUrl="
                    f"{_default_auth_admin_url(auth_namespace, auth_release)}",
                    "--set",
                    "security.tokenExchange.extProc.serviceName="
                    f"{auth_release}-agentic-identity-broker-extproc",
                    "--set",
                    f"security.tokenExchange.extProc.namespace={auth_namespace}",
                    "--set",
                    f"security.tokenExchange.extProc.port={AUTH_EXTPROC_PORT}",
                ]
            )
    elif gateway_api_strict:
        # Strict gateway-only traffic is a standalone posture: it applies even
        # without an authorization enforcement hook, so emit it directly when
        # auth is not enabled.
        helm_args.extend(["--set", "security.strictGatewayApi.enabled=true"])

    typer.echo(f"Installing chart {HELM_CHART_NAME}...")
    if identity_provider == "oidc" and oidc_registration_secret_name:
        typer.echo(
            "Note: create a Keycloak initial access token and provision it with:"
        )
        typer.echo(
            f"  kubectl create secret generic {oidc_registration_secret_name} "
            f"-n {namespace} --from-literal={oidc_registration_secret_key}=<token>"
        )
        typer.echo("  The operator pod remains pending until this Secret exists.")
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
    pgvector_memory_enabled: bool = False,
) -> None:
    """Uninstall the KAOS operator using Helm."""
    if not check_helm_installed():
        typer.echo("Error: helm is not installed.", err=True)
        sys.exit(1)

    # Uninstall monitoring if requested
    if monitoring_enabled:
        _uninstall_monitoring(monitoring_enabled, namespace)

    if pgvector_memory_enabled:
        _uninstall_pgvector(namespace)

    # Delete all KAOS custom resources so operator can process finalizers
    typer.echo("Deleting KAOS custom resources...")
    for resource_type in ["agents", "mcpservers", "modelapis"]:
        _run_kubectl(
            ["delete", resource_type, "--all-namespaces", "--all", "--timeout=60s"],
            check=False,
        )

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

    # Delete KAOS CRDs (helm doesn't delete CRDs on uninstall)
    typer.echo("Deleting KAOS CRDs...")
    _run_kubectl(
        ["delete", "crd", "--ignore-not-found"] + KAOS_CRDS,
        check=False,
    )

    # Uninstall Gateway API if requested
    if gateway_enabled:
        _uninstall_gateway_api()

    # Uninstall MetalLB if requested
    if metallb_enabled:
        _uninstall_metallb()
