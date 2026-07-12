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


# Curated identity and gateway-policy postures selected with --auth-enabled.
AUTH_PRESET_AIB_KEYCLOAK = "aib-keycloak"
AUTH_PRESET_OIDC_KEYCLOAK = "oidc-keycloak"
AUTH_PRESET_KAOS_INTERNAL = "kaos-internal"
AUTH_PRESET_AIB_ONLY = "aib-only"
AUTH_PRESETS = (
    AUTH_PRESET_AIB_KEYCLOAK,
    AUTH_PRESET_OIDC_KEYCLOAK,
    AUTH_PRESET_KAOS_INTERNAL,
    AUTH_PRESET_AIB_ONLY,
)
DEFAULT_AUTH_PRESET = AUTH_PRESET_AIB_KEYCLOAK
DEFAULT_POLICY_CONFIGMAP_NAME = "kaos-authz-policy"

# User-auth (human identity provider, Keycloak by default) defaults
DEFAULT_KEYCLOAK_NAMESPACE = "keycloak"
DEFAULT_KEYCLOAK_RELEASE = "keycloak"
DEFAULT_KEYCLOAK_IMAGE = "quay.io/keycloak/keycloak:26.0"
KEYCLOAK_HTTP_PORT = 8080
DEFAULT_USER_AUTH_REALM = "kaos"
DEFAULT_USER_AUTH_AUDIENCE = "kaos"
DEFAULT_USER_AUTH_CLIENT_ID = "kaos"
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


def _run_kubectl(
    args: list[str], check: bool = True, **kwargs
) -> subprocess.CompletedProcess:
    """Run a kubectl command and return the result."""
    cmd = ["kubectl"] + args
    return subprocess.run(cmd, capture_output=True, text=True, check=check, **kwargs)


def _install_gateway_api() -> bool:
    """Install Envoy Gateway (includes Gateway API CRDs) and create GatewayClass."""
    typer.echo(f"Installing Envoy Gateway ({ENVOY_GATEWAY_VERSION})...")

    # Pre-apply CRDs from the chart to handle field manager conflicts on re-installs
    crds_result = run_helm_command(
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
        result = _run_kubectl(
            ["apply", "--server-side", "--force-conflicts", "-f", "-"],
            check=False,
            input=crds_result.stdout,
        )
        if result.returncode == 0:
            crd_pre_applied = True
        else:
            # Stale CRDs with incompatible storedVersions — delete and let helm recreate
            typer.echo("  Cleaning up stale Gateway API CRDs...")
            _run_kubectl(
                [
                    "delete",
                    "crd",
                    "--ignore-not-found",
                    "-l",
                    "gateway.networking.k8s.io/policy",
                ],
                check=False,
            )
            _run_kubectl(
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

    result = run_helm_command(
        [
            "upgrade",
            "--install",
            "envoy-gateway",
            "oci://docker.io/envoyproxy/gateway-helm",
            "--version",
            ENVOY_GATEWAY_VERSION,
            "--namespace",
            "envoy-gateway-system",
            "--create-namespace",
        ]
        + (["--skip-crds"] if crd_pre_applied else []),
        check=False,
    )
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
    result = _run_kubectl(["apply", "-f", "-"], check=False, input=gc_yaml)
    if result.returncode != 0:
        typer.echo(f"Error creating GatewayClass: {result.stderr}", err=True)
        return False

    typer.echo("Waiting for GatewayClass to be accepted...")
    for i in range(30):
        result = _run_kubectl(
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
    result = run_helm_command(
        ["uninstall", "envoy-gateway", "--namespace", "envoy-gateway-system"],
        check=False,
    )
    if result.returncode != 0 and "not found" not in result.stderr.lower():
        typer.echo(f"Warning: {result.stderr}", err=True)

    _run_kubectl(
        ["delete", "gatewayclass", GATEWAY_CLASS_NAME, "--ignore-not-found"],
        check=False,
    )
    _run_kubectl(
        ["delete", "namespace", "envoy-gateway-system", "--ignore-not-found"],
        check=False,
    )
    typer.echo("✅ Gateway API uninstalled")
    return True


def _install_metallb() -> bool:
    """Install MetalLB for LoadBalancer support (KIND/bare-metal clusters)."""
    typer.echo(f"Installing MetalLB ({METALLB_VERSION})...")
    result = _run_kubectl(
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
    result = _run_kubectl(
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
        result = _run_kubectl(["apply", "-f", "-"], check=False, input=pool_yaml)
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
    _run_kubectl(
        [
            "delete",
            "-f",
            f"https://raw.githubusercontent.com/metallb/metallb/{METALLB_VERSION}/config/manifests/metallb-native.yaml",
            "--ignore-not-found",
        ],
        check=False,
    )
    _run_kubectl(
        ["delete", "namespace", "metallb-system", "--ignore-not-found"], check=False
    )
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
        typer.echo(
            f"Warning: Could not create Jaeger UI config: {result.stderr}", err=True
        )


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


def _pgvector_dsn(namespace: str) -> str:
    """DSN for the in-cluster development pgvector Postgres."""
    host = f"{PGVECTOR_NAME}.{namespace}.svc.cluster.local"
    return f"postgresql://{PGVECTOR_USER}:{PGVECTOR_PASSWORD}@{host}:5432/{PGVECTOR_DB}"


def _pgvector_manifest(namespace: str) -> str:
    """Render the Secret, Deployment, and Service for the dev pgvector Postgres."""
    dsn = _pgvector_dsn(namespace)
    return f"""apiVersion: v1
kind: Secret
metadata:
  name: {PGVECTOR_SECRET_NAME}
  namespace: {namespace}
stringData:
  {PGVECTOR_SECRET_KEY}: {dsn}
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {PGVECTOR_NAME}
  namespace: {namespace}
spec:
  replicas: 1
  selector:
    matchLabels:
      app: {PGVECTOR_NAME}
  template:
    metadata:
      labels:
        app: {PGVECTOR_NAME}
    spec:
      containers:
      - name: postgres
        image: {PGVECTOR_IMAGE}
        env:
        - name: POSTGRES_USER
          value: {PGVECTOR_USER}
        - name: POSTGRES_PASSWORD
          value: {PGVECTOR_PASSWORD}
        - name: POSTGRES_DB
          value: {PGVECTOR_DB}
        ports:
        - containerPort: 5432
        readinessProbe:
          exec:
            command: ["pg_isready", "-U", "{PGVECTOR_USER}", "-d", "{PGVECTOR_DB}"]
          initialDelaySeconds: 5
          periodSeconds: 5
---
apiVersion: v1
kind: Service
metadata:
  name: {PGVECTOR_NAME}
  namespace: {namespace}
spec:
  selector:
    app: {PGVECTOR_NAME}
  ports:
  - port: 5432
    targetPort: 5432
"""


def _install_pgvector(namespace: str) -> bool:
    """Provision a development pgvector Postgres for external-mode MemoryStores.

    This is an opt-in, dev-only datastore (single replica, no persistence,
    default credentials). It writes a Secret holding the connection DSN that an
    ``external`` MemoryStore references via connectionSecretRef.
    """
    typer.echo("Installing development pgvector Postgres...")

    ns_result = _run_kubectl(["create", "namespace", namespace], check=False)
    if ns_result.returncode != 0 and "already exists" not in ns_result.stderr:
        typer.echo(f"Warning creating namespace: {ns_result.stderr}", err=True)

    result = _run_kubectl(
        ["apply", "-f", "-"], check=False, input=_pgvector_manifest(namespace)
    )
    if result.returncode != 0:
        typer.echo(f"Error installing pgvector Postgres: {result.stderr}", err=True)
        return False

    _run_kubectl(
        [
            "rollout",
            "status",
            f"deployment/{PGVECTOR_NAME}",
            "--namespace",
            namespace,
            "--timeout=120s",
        ],
        check=False,
    )

    typer.echo(
        f"✅ pgvector Postgres installed in '{namespace}' "
        f"(dev-only; DSN in secret '{PGVECTOR_SECRET_NAME}' key '{PGVECTOR_SECRET_KEY}')"
    )
    return True


def _uninstall_pgvector(namespace: str) -> bool:
    """Remove the development pgvector Postgres and its connection secret."""
    typer.echo("Uninstalling development pgvector Postgres...")
    for kind, name in (
        ("deployment", PGVECTOR_NAME),
        ("service", PGVECTOR_NAME),
        ("secret", PGVECTOR_SECRET_NAME),
    ):
        _run_kubectl(
            ["delete", kind, name, "--namespace", namespace, "--ignore-not-found"],
            check=False,
        )
    typer.echo(f"✅ pgvector Postgres uninstalled from '{namespace}'")
    return True


def _auth_broker_fullname(auth_release: str) -> str:
    """Return the broker Service/Deployment name produced by the broker chart."""
    return f"{auth_release}-agentic-identity-broker"


def _default_auth_issuer(auth_namespace: str, auth_release: str) -> str:
    """Default issuer (broker enduser endpoint) propagated to agent pods."""
    host = f"{_auth_broker_fullname(auth_release)}.{auth_namespace}.svc.cluster.local"
    return f"http://{host}:{AUTH_ENDUSER_PORT}"


def _default_auth_admin_url(auth_namespace: str, auth_release: str) -> str:
    """Default broker admin API base URL used by the operator identity projection."""
    host = f"{_auth_broker_fullname(auth_release)}.{auth_namespace}.svc.cluster.local"
    return f"http://{host}:{AUTH_ADMIN_PORT}/api"


def _default_user_auth_issuer(keycloak_namespace: str, keycloak_release: str) -> str:
    """Default user-auth OIDC issuer (Keycloak realm URL) for the gateway provider."""
    host = f"{keycloak_release}.{keycloak_namespace}.svc.cluster.local"
    return f"http://{host}:{KEYCLOAK_HTTP_PORT}/realms/{DEFAULT_USER_AUTH_REALM}"


def _build_auth_operator_args(
    ext_authz_url: str,
    issuer: str,
    credential_secret_prefix: str,
    identity_provider: str = "aib",
    pdp_enabled: bool = False,
    admin_url: str = "",
    user_issuer: str = "",
    user_audience: str = "",
    user_jwks_uri: str = "",
    oidc_registration_secret_name: str = "",
    oidc_registration_secret_key: str = "",
    network_policy: bool = True,
    network_policy_egress: bool = False,
    gateway_routing: bool = False,
    gateway_api_strict: bool = False,
    gateway_host: str = "",
    tls_mode: str = "",
    tls_issuer_name: str = "",
    tls_issuer_kind: str = "ClusterIssuer",
    tls_secret_name: str = "",
    policy_data_source: str = "",
    policy_rego_override: bool = False,
    policy_configmap_name: str = "",
    policy_configmap_namespace: str = "",
) -> list[str]:
    """Build the operator Helm --set arguments that enable agent-auth wiring.

    Returns the flat ``--set key=value`` argument list so it can be unit-tested
    independently of running Helm. User-auth (``security.userAuth.*``) arguments
    are appended only when a user issuer is supplied, keeping agent-only and
    autonomous-only installs unchanged. When an admin URL is supplied, the
    operator's identity projection controller is
    enabled via ``security.agentAuth.adminUrl`` so it registers agents and mints
    their per-agent credential Secrets directly.

    Bypass-prevention and transport-security arguments are appended too:
    NetworkPolicy is on unless explicitly disabled, egress isolation is opt-in,
    gateway routing and host are set when requested, and ``security.tls.*`` is
    configured when a TLS mode is supplied.

    Authorization knobs (``security.agentAuth.authorization.*``) and the policy
    ConfigMap projection target are appended only when set, so the default
    install leaves authorization projection off.
    """
    args: list[str] = []
    if ext_authz_url:
        args.extend(["--set", f"security.agentAuth.extAuthzUrl={ext_authz_url}"])
    args.extend(["--set", f"security.agentAuth.identity.provider={identity_provider}"])
    if pdp_enabled:
        args.extend(["--set", "security.pdp.enabled=true"])
    if identity_provider != "serviceaccount" and issuer:
        args.extend(["--set", f"security.agentAuth.issuer={issuer}"])
    if identity_provider == "aib":
        args.extend(
            [
                "--set",
                f"security.agentAuth.credentialSecretPrefix={credential_secret_prefix}",
            ]
        )
    if identity_provider == "aib" and admin_url:
        args.extend(["--set", f"security.agentAuth.adminUrl={admin_url}"])
    if identity_provider == "oidc" and oidc_registration_secret_name:
        args.extend(
            [
                "--set",
                "security.agentAuth.identity.oidc.registration."
                f"initialAccessTokenSecretRef.name={oidc_registration_secret_name}",
            ]
        )
    if identity_provider == "oidc" and oidc_registration_secret_key:
        args.extend(
            [
                "--set",
                "security.agentAuth.identity.oidc.registration."
                f"initialAccessTokenSecretRef.key={oidc_registration_secret_key}",
            ]
        )
    if policy_data_source:
        args.extend(
            [
                "--set",
                f"security.agentAuth.authorization.policyDataSource={policy_data_source}",
            ]
        )
    if policy_rego_override:
        args.extend(
            ["--set", "security.agentAuth.authorization.policyRegoOverride=true"]
        )
    if policy_configmap_name:
        args.extend(
            [
                "--set",
                f"security.agentAuth.projection.policyConfigMap.name={policy_configmap_name}",
            ]
        )
    if policy_configmap_namespace:
        args.extend(
            [
                "--set",
                f"security.agentAuth.projection.policyConfigMap.namespace={policy_configmap_namespace}",
            ]
        )
    if user_issuer:
        args.extend(["--set", f"security.userAuth.issuer={user_issuer}"])
    if user_audience:
        args.extend(["--set", f"security.userAuth.audience={user_audience}"])
    if user_jwks_uri:
        args.extend(["--set", f"security.userAuth.jwksUri={user_jwks_uri}"])
    if not network_policy:
        args.extend(["--set", "security.networkPolicy.enabled=false"])
    if network_policy_egress:
        args.extend(["--set", "security.networkPolicy.egress.enabled=true"])
    if gateway_routing:
        args.extend(["--set", "security.gatewayRouting.enabled=true"])
    if gateway_api_strict:
        args.extend(["--set", "security.strictGatewayApi.enabled=true"])
    if gateway_host:
        args.extend(["--set", f"security.gatewayHost={gateway_host}"])
    if tls_mode:
        args.extend(["--set", f"security.tls.mode={tls_mode}"])
        if tls_issuer_name:
            args.extend(
                ["--set", f"security.tls.certManager.issuerRef.name={tls_issuer_name}"]
            )
        if tls_issuer_kind:
            args.extend(
                ["--set", f"security.tls.certManager.issuerRef.kind={tls_issuer_kind}"]
            )
        if tls_secret_name:
            args.extend(["--set", f"security.tls.secretName={tls_secret_name}"])
    return args


def _install_aib(
    namespace: str,
    release: str,
    chart_path: str,
    values_path: str | None,
    wait: bool,
    extra_set: list[str] | None = None,
) -> bool:
    """Install the identity broker from a local chart (unpublished/dev path)."""
    typer.echo("Installing identity broker...")
    helm_args = [
        "upgrade",
        "--install",
        release,
        chart_path,
        "--namespace",
        namespace,
        "--create-namespace",
    ]
    if values_path:
        helm_args.extend(["--values", values_path])
    if extra_set:
        helm_args.extend(extra_set)
    if wait:
        helm_args.append("--wait")

    result = run_helm_command(helm_args, check=False)
    if result.returncode != 0:
        typer.echo(f"Error installing identity broker: {result.stderr}", err=True)
        return False

    typer.echo(f"✅ Identity broker installed in '{namespace}' namespace")
    return True


def _build_aib_broker_public_url_args(public_url: str) -> list[str]:
    """Set the broker enduser ``public_url`` to its in-cluster service URL.

    The broker defaults ``server.enduser.public_url`` to ``http://localhost:8000``
    and stamps that value as the ``iss`` claim on the ``client_credentials``
    agent tokens it mints. The gateway ``agent`` JWT provider validates those
    tokens against the broker's in-cluster issuer, so without this override the
    ``iss`` never matches and every agent-identity request is rejected with
    ``Jwt_issuer_is_not_configured``. ``public_url`` is the broker enduser
    endpoint (same value propagated to agents as their auth issuer).
    """
    return ["--set", f"broker.server.enduser.publicUrl={public_url}"]


def _keycloak_realm_json(
    realm: str,
    client_id: str,
    client_secret: str,
    audience: str,
    username: str,
    password: str,
) -> dict:
    """Build a minimal Keycloak realm definition for non-interactive validation.

    The realm exposes a confidential client with the direct-access-grant flow so a
    user access token can be minted programmatically (password grant), and an
    audience and group mappers so issued access tokens carry the claims the gateway
    and group-based AccessGrants require.
    """

    return {
        "realm": realm,
        "enabled": True,
        "clientScopes": [
            {
                "name": "kaos-agent-audience",
                "protocol": "openid-connect",
                "attributes": {"include.in.token.scope": "false"},
                "protocolMappers": [
                    {
                        "name": "kaos-agent-audience",
                        "protocol": "openid-connect",
                        "protocolMapper": "oidc-audience-mapper",
                        "config": {
                            "included.custom.audience": DEFAULT_AGENT_AUTH_AUDIENCE,
                            "id.token.claim": "false",
                            "access.token.claim": "true",
                        },
                    }
                ],
            }
        ],
        "defaultDefaultClientScopes": ["kaos-agent-audience"],
        "clients": [
            {
                "clientId": client_id,
                "enabled": True,
                "publicClient": False,
                "secret": client_secret,
                "directAccessGrantsEnabled": True,
                "standardFlowEnabled": True,
                "serviceAccountsEnabled": True,
                "redirectUris": ["*"],
                "protocolMappers": [
                    {
                        "name": "kaos-audience",
                        "protocol": "openid-connect",
                        "protocolMapper": "oidc-audience-mapper",
                        "config": {
                            "included.client.audience": audience,
                            "id.token.claim": "false",
                            "access.token.claim": "true",
                        },
                    },
                    {
                        "name": "kaos-groups",
                        "protocol": "openid-connect",
                        "protocolMapper": "oidc-group-membership-mapper",
                        "config": {
                            "claim.name": "groups",
                            "full.path": "false",
                            "id.token.claim": "false",
                            "access.token.claim": "true",
                            "userinfo.token.claim": "false",
                        },
                    },
                    {
                        "name": "kaos-subject",
                        "protocol": "openid-connect",
                        "protocolMapper": "oidc-usermodel-property-mapper",
                        "config": {
                            "user.attribute": "id",
                            "claim.name": "sub",
                            "jsonType.label": "String",
                            "id.token.claim": "false",
                            "access.token.claim": "true",
                            "userinfo.token.claim": "false",
                        },
                    },
                ],
            },
        ],
        "groups": [{"name": "researchers"}],
        "users": [
            {
                "username": username,
                "enabled": True,
                "emailVerified": True,
                "email": f"{username}@example.com",
                "firstName": "KAOS",
                "lastName": "User",
                "requiredActions": [],
                "groups": ["researchers"],
                "credentials": [
                    {"type": "password", "value": password, "temporary": False}
                ],
            }
        ],
    }


def _keycloak_realm_configmap_name(release: str) -> str:
    """Name of the ConfigMap holding the imported realm definition."""
    return f"{release}-realm-import"


def _bootstrap_keycloak_realm(
    namespace: str,
    release: str,
    realm: str,
    audience: str,
) -> bool:
    """Create the realm-import ConfigMap consumed by Keycloak's --import-realm.

    This is the non-interactive realm bootstrap: it provisions the realm, a
    confidential client and a test user so a user token can be obtained without a
    browser login. Applied via kubectl so it is independent of the Keycloak chart.
    """
    realm_json = json.dumps(
        _keycloak_realm_json(
            realm,
            DEFAULT_USER_AUTH_CLIENT_ID,
            DEFAULT_USER_AUTH_CLIENT_SECRET,
            audience,
            DEFAULT_USER_AUTH_TEST_USER,
            DEFAULT_USER_AUTH_TEST_PASSWORD,
        ),
        indent=2,
    )
    configmap = {
        "apiVersion": "v1",
        "kind": "ConfigMap",
        "metadata": {
            "name": _keycloak_realm_configmap_name(release),
            "namespace": namespace,
        },
        "data": {f"{realm}-realm.json": realm_json},
    }

    apply_ns = _run_kubectl(
        ["create", "namespace", namespace],
        check=False,
    )
    if (
        apply_ns.returncode != 0
        and "already exists" not in (apply_ns.stderr or "").lower()
    ):
        typer.echo(
            f"Warning: could not create namespace '{namespace}': {apply_ns.stderr}",
            err=True,
        )

    result = _run_kubectl(
        ["apply", "-f", "-"], check=False, input=json.dumps(configmap)
    )
    if result.returncode != 0:
        typer.echo(f"Error bootstrapping Keycloak realm: {result.stderr}", err=True)
        return False
    typer.echo(f"✅ Keycloak realm '{realm}' bootstrap manifest applied")
    return True


def _keycloak_dev_manifests(namespace: str, release: str) -> list[dict]:
    """Self-contained Keycloak dev deployment (start-dev, H2 in-memory, no DB).

    Mounts the realm-import ConfigMap and runs with --import-realm so the
    bootstrapped realm/client/user are available on startup. Intended for local
    and e2e validation only.
    """
    labels = {"app": release}
    configmap_name = _keycloak_realm_configmap_name(release)
    deployment = {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {"name": release, "namespace": namespace, "labels": labels},
        "spec": {
            "replicas": 1,
            "selector": {"matchLabels": labels},
            "template": {
                "metadata": {"labels": labels},
                "spec": {
                    "containers": [
                        {
                            "name": "keycloak",
                            "image": DEFAULT_KEYCLOAK_IMAGE,
                            "args": ["start-dev", "--import-realm"],
                            "env": [
                                {
                                    "name": "KEYCLOAK_ADMIN",
                                    "value": DEFAULT_KEYCLOAK_ADMIN_USER,
                                },
                                {
                                    "name": "KEYCLOAK_ADMIN_PASSWORD",
                                    "value": DEFAULT_KEYCLOAK_ADMIN_PASSWORD,
                                },
                            ],
                            "ports": [{"containerPort": KEYCLOAK_HTTP_PORT}],
                            "volumeMounts": [
                                {
                                    "name": "realm-import",
                                    "mountPath": "/opt/keycloak/data/import",
                                    "readOnly": True,
                                }
                            ],
                        }
                    ],
                    "volumes": [
                        {
                            "name": "realm-import",
                            "configMap": {"name": configmap_name},
                        }
                    ],
                },
            },
        },
    }
    service = {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": {"name": release, "namespace": namespace, "labels": labels},
        "spec": {
            "selector": labels,
            "ports": [
                {
                    "port": KEYCLOAK_HTTP_PORT,
                    "targetPort": KEYCLOAK_HTTP_PORT,
                    "name": "http",
                }
            ],
        },
    }
    return [deployment, service]


def _install_keycloak(
    namespace: str,
    release: str,
    realm: str,
    audience: str,
    chart_path: str | None,
    wait: bool,
) -> bool:
    """Install Keycloak as the human user identity provider.

    The realm/client/test-user are bootstrapped first (non-interactive). When a
    chart path is supplied Keycloak is installed via Helm (mirrors the broker
    dev path); otherwise a self-contained dev deployment is applied via kubectl.
    """
    typer.echo("Installing user identity provider (Keycloak)...")
    if not _bootstrap_keycloak_realm(namespace, release, realm, audience):
        return False

    if chart_path:
        helm_args = [
            "upgrade",
            "--install",
            release,
            chart_path,
            "--namespace",
            namespace,
            "--create-namespace",
            "--set",
            f"realmImport.configMapName={_keycloak_realm_configmap_name(release)}",
        ]
        if wait:
            helm_args.append("--wait")
        result = run_helm_command(helm_args, check=False)
        if result.returncode != 0:
            typer.echo(f"Error installing Keycloak: {result.stderr}", err=True)
            return False
    else:
        for manifest in _keycloak_dev_manifests(namespace, release):
            result = _run_kubectl(
                ["apply", "-f", "-"], check=False, input=json.dumps(manifest)
            )
            if result.returncode != 0:
                typer.echo(f"Error installing Keycloak: {result.stderr}", err=True)
                return False

    typer.echo(f"✅ Keycloak installed in '{namespace}' namespace")
    return True


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
                [
                    "kubectl",
                    "delete",
                    "configmap",
                    "jaeger-ui-config",
                    "-n",
                    namespace,
                    "--ignore-not-found",
                ],
                capture_output=True,
                text=True,
            )
        typer.echo(f"✅ {backend.capitalize()} uninstalled from '{namespace}'")
        return True
    elif "not found" in result.stderr.lower():
        typer.echo(
            f"{backend.capitalize()} release not found in namespace '{namespace}'."
        )
        return True
    else:
        typer.echo(f"Error uninstalling {backend}: {result.stderr}", err=True)
        return False


def _get_otel_endpoint(backend: str, namespace: str) -> str:
    """Return the OTLP collector endpoint for the given backend."""
    if backend == "jaeger":
        return f"http://jaeger.{namespace}:4317"
    return f"http://signoz-otel-collector.{namespace}:4317"


def _expand_auth_preset(preset: str, namespace: str) -> dict:
    """Expand an --auth-enabled preset into install_command auth kwargs.

    Every preset enables the in-chart PDP and automated policy projection.
    """
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
    if preset == AUTH_PRESET_AIB_KEYCLOAK:
        return {**base, "identity_provider": "aib", "user_auth": True}
    if preset == AUTH_PRESET_OIDC_KEYCLOAK:
        return {
            **base,
            "identity_provider": "oidc",
            "credential_secret_prefix": DEFAULT_OIDC_CREDENTIAL_SECRET_PREFIX,
            "oidc_registration_secret_name": DEFAULT_OIDC_REGISTRATION_SECRET_NAME,
            "oidc_registration_secret_key": DEFAULT_OIDC_REGISTRATION_SECRET_KEY,
            "user_auth": True,
        }
    if preset == AUTH_PRESET_KAOS_INTERNAL:
        return {**base, "identity_provider": "serviceaccount", "user_auth": False}
    if preset == AUTH_PRESET_AIB_ONLY:
        return {**base, "identity_provider": "aib", "user_auth": False}
    raise ValueError(f"unknown auth preset: {preset!r}")


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
        if not _install_gateway_api():
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
        if identity_provider == "aib" and aib_chart_path:
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

        # Install Keycloak as the human user identity provider and bootstrap its
        # realm so the gateway can verify user subject tokens alongside agent
        # actor tokens. Skipped when user-auth is disabled.
        if user_auth:
            if not _install_keycloak(
                keycloak_namespace,
                keycloak_release,
                DEFAULT_USER_AUTH_REALM,
                user_auth_audience,
                keycloak_chart_path,
                wait,
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
