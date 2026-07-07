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

# Agent-auth (identity broker) defaults
DEFAULT_AUTH_NAMESPACE = "aib-system"
DEFAULT_AUTH_RELEASE = "aib"
DEFAULT_CREDENTIAL_SECRET_PREFIX = "kaos-aib"
# Conventional in-cluster service names exposed by the broker stack.
AUTH_EXT_AUTHZ_PORT = 9191
AUTH_ENDUSER_PORT = 8000
AUTH_ADMIN_PORT = 14000
AUTH_EXT_PROC_PORT = 50051
AUTH_EXT_PROC_CLIENT_ID = "extproc-gateway"
AUTH_EXT_PROC_CLIENT_SECRET = "extproc-gateway-secret"
DEFAULT_THIRD_PARTY_SERVICE_ID = "dummy-third-party"

# User-auth (human identity provider, Keycloak by default) defaults
DEFAULT_KEYCLOAK_NAMESPACE = "keycloak"
DEFAULT_KEYCLOAK_RELEASE = "keycloak"
DEFAULT_KEYCLOAK_IMAGE = "quay.io/keycloak/keycloak:26.0"
KEYCLOAK_HTTP_PORT = 8080
DEFAULT_USER_AUTH_REALM = "kaos"
DEFAULT_USER_AUTH_AUDIENCE = "kaos"
DEFAULT_USER_AUTH_CLIENT_ID = "kaos"
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


def _install_redis(namespace: str) -> bool:
    """Install Redis for distributed agent memory."""
    typer.echo("Installing Redis...")

    result = run_helm_command(
        [
            "repo",
            "add",
            "bitnami",
            "https://charts.bitnami.com/bitnami",
            "--force-update",
        ],
        check=False,
    )
    if result.returncode != 0 and "already exists" not in result.stderr:
        typer.echo(f"Warning adding Bitnami repo: {result.stderr}", err=True)

    run_helm_command(["repo", "update"], check=False)

    result = run_helm_command(
        [
            "upgrade",
            "--install",
            "redis",
            "bitnami/redis",
            "--namespace",
            namespace,
            "--create-namespace",
            "--set",
            "architecture=standalone",
            "--set",
            "auth.enabled=false",
        ],
        check=False,
    )
    if result.returncode != 0:
        typer.echo(f"Error installing Redis: {result.stderr}", err=True)
        return False

    typer.echo(f"✅ Redis installed in '{namespace}' namespace")
    return True


def _uninstall_redis(namespace: str) -> bool:
    """Uninstall Redis."""
    typer.echo("Uninstalling Redis...")

    result = run_helm_command(
        ["uninstall", "redis", "--namespace", namespace],
        check=False,
    )

    if result.returncode == 0:
        typer.echo(f"✅ Redis uninstalled from '{namespace}'")
        return True
    elif "not found" in result.stderr.lower():
        typer.echo(f"Redis release not found in namespace '{namespace}'.")
        return True
    else:
        typer.echo(f"Error uninstalling Redis: {result.stderr}", err=True)
        return False


def _auth_broker_fullname(auth_release: str) -> str:
    """Return the broker Service/Deployment name produced by the broker chart."""
    return f"{auth_release}-agentic-identity-broker"


def _default_ext_authz_url(auth_namespace: str) -> str:
    """Default host:port of the broker access-check gRPC backend."""
    return f"aib-access-check-grpc.{auth_namespace}.svc.cluster.local:{AUTH_EXT_AUTHZ_PORT}"


def _default_ext_proc_url(auth_namespace: str, auth_release: str) -> str:
    """Default host:port of the broker ExtProc token-exchange gRPC backend.

    Matches the Service rendered by the broker chart's optional ExtProc
    component (``<release>-agentic-identity-broker-extproc``).
    """
    host = f"{_auth_broker_fullname(auth_release)}-extproc.{auth_namespace}.svc.cluster.local"
    return f"{host}:{AUTH_EXT_PROC_PORT}"


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
    admin_url: str = "",
    user_issuer: str = "",
    user_audience: str = "",
    user_jwks_uri: str = "",
    ext_proc_url: str = "",
    network_policy: bool = True,
    network_policy_egress: bool = False,
    gateway_routing: bool = False,
    gateway_host: str = "",
    tls_mode: str = "",
    tls_issuer_name: str = "",
    tls_issuer_kind: str = "ClusterIssuer",
    tls_secret_name: str = "",
    authz_provider: str = "",
    authz_gateway_extension: str = "",
    agent_jwt_verification: str = "",
    policy_data_source: str = "",
    policy_rego_override: bool = False,
    policy_configmap_name: str = "",
    policy_configmap_namespace: str = "",
) -> list[str]:
    """Build the operator Helm --set arguments that enable agent-auth wiring.

    Returns the flat ``--set key=value`` argument list so it can be unit-tested
    independently of running Helm. User-auth (``security.userAuth.*``) arguments
    are appended only when a user issuer is supplied, keeping agent-only and
    autonomous-only installs unchanged. The token-exchange ext_proc backend
    (``security.agentAuth.extProcUrl``) is appended only when supplied. When an
    admin URL is supplied, the operator's identity projection controller is
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
    args.extend(["--set", f"security.agentAuth.extAuthzUrl={ext_authz_url}"])
    args.extend(["--set", f"security.agentAuth.issuer={issuer}"])
    args.extend(
        [
            "--set",
            f"security.agentAuth.credentialSecretPrefix={credential_secret_prefix}",
        ]
    )
    if ext_proc_url:
        args.extend(["--set", f"security.agentAuth.extProcUrl={ext_proc_url}"])
    if admin_url:
        args.extend(["--set", f"security.agentAuth.adminUrl={admin_url}"])
    if authz_provider:
        args.extend(
            ["--set", f"security.agentAuth.authorization.provider={authz_provider}"]
        )
    if authz_gateway_extension:
        args.extend(
            [
                "--set",
                f"security.agentAuth.authorization.gatewayExtension={authz_gateway_extension}",
            ]
        )
    if agent_jwt_verification:
        args.extend(
            [
                "--set",
                f"security.agentAuth.authorization.agentJwtVerification={agent_jwt_verification}",
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


def _build_aib_extproc_args(
    ext_proc_client_id: str,
    ext_proc_client_secret: str,
    client_assertion_type: str = "access_token",
) -> list[str]:
    """Build the broker-chart Helm --set args enabling the ExtProc component.

    Returns the flat ``--set key=value`` list so it can be unit-tested without
    running Helm. The OAuth2 token endpoint and issuer are left to the chart
    defaults (the in-cluster broker enduser service).
    """
    return [
        "--set",
        "extProc.enabled=true",
        "--set",
        f"extProc.oauth2.clientId={ext_proc_client_id}",
        "--set",
        f"extProc.oauth2.clientSecret={ext_proc_client_secret}",
        "--set",
        f"extProc.oauth2.clientAssertionType={client_assertion_type}",
    ]


def _provision_token_exchange(
    admin_url: str,
    ext_proc_client_id: str,
    third_party_service_id: str,
    third_party_issuer: str,
) -> bool:
    """Register the ExtProc OAuth client and a dummy third-party service.

    Best-effort, dev/validation-only provisioning against the broker admin API so
    that the token-exchange path has an OAuth client to assert as and a
    third-party service to exchange for. Failures are non-fatal: the install
    continues and the validation surface can register the grant interactively.
    """
    import json
    import urllib.error
    import urllib.request

    def _post(path: str, payload: dict) -> bool:
        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            f"{admin_url.rstrip('/')}{path}",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            urllib.request.urlopen(req, timeout=10)  # noqa: S310 (in-cluster URL)
            return True
        except urllib.error.HTTPError as exc:
            # 409/422 (already exists) is acceptable for idempotent provisioning.
            if exc.code in (409, 422):
                return True
            typer.echo(
                f"Warning: token-exchange provisioning {path} -> HTTP {exc.code}",
                err=True,
            )
            return False
        except urllib.error.URLError as exc:
            typer.echo(
                f"Warning: token-exchange provisioning {path} unreachable: {exc}",
                err=True,
            )
            return False

    ok = _post(
        "/agents",
        {
            "client_id": ext_proc_client_id,
            "display_name": "ExtProc Gateway",
            "description": "Gateway token-exchange client (auto-provisioned)",
        },
    )
    ok = (
        _post(
            "/services",
            {
                "display_name": "Dummy Third Party",
                "client_id": "dummy-third-party",
                "client_secret": "dummy-third-party-secret",
                "issuer_uri": third_party_issuer,
                "service_id": third_party_service_id,
            },
        )
        and ok
    )
    return ok


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
    audience mapper so the issued token carries the audience the gateway verifies.
    """
    return {
        "realm": realm,
        "enabled": True,
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
                    }
                ],
            }
        ],
        "users": [
            {
                "username": username,
                "enabled": True,
                "emailVerified": True,
                "email": f"{username}@example.com",
                "firstName": "KAOS",
                "lastName": "User",
                "requiredActions": [],
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


def install_command(
    namespace: str,
    release_name: str,
    version: str | None,
    set_values: list[str],
    wait: bool,
    monitoring_enabled: str | None = None,
    gateway_enabled: bool = False,
    metallb_enabled: bool = False,
    redis_enabled: bool = False,
    chart_path: str | None = None,
    auth_enabled: bool = False,
    auth_namespace: str = DEFAULT_AUTH_NAMESPACE,
    auth_release: str = DEFAULT_AUTH_RELEASE,
    ext_authz_url: str | None = None,
    auth_issuer: str | None = None,
    credential_secret_prefix: str = DEFAULT_CREDENTIAL_SECRET_PREFIX,
    token_exchange: bool = True,
    ext_proc_url: str | None = None,
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
    gateway_host: str | None = None,
    tls_mode: str | None = None,
    tls_issuer_name: str | None = None,
    tls_issuer_kind: str = "ClusterIssuer",
    tls_secret_name: str | None = None,
    authz_provider: str | None = None,
    authz_gateway_extension: str | None = None,
    agent_jwt_verification: str | None = None,
    policy_data_source: str | None = None,
    policy_rego_override: bool = False,
    admin_url: str | None = None,
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

    if redis_enabled:
        if not _install_redis(namespace):
            typer.echo("Warning: Redis installation failed, continuing...", err=True)

    # Resolve agent-auth endpoints (used for both component installs and operator wiring)
    if auth_enabled:
        ext_authz_url = ext_authz_url or _default_ext_authz_url(auth_namespace)
        auth_issuer = auth_issuer or _default_auth_issuer(auth_namespace, auth_release)
        auth_admin_url = _default_auth_admin_url(auth_namespace, auth_release)
        if token_exchange:
            ext_proc_url = ext_proc_url or _default_ext_proc_url(
                auth_namespace, auth_release
            )
        if user_auth:
            user_auth_issuer = user_auth_issuer or _default_user_auth_issuer(
                keycloak_namespace, keycloak_release
            )

        # Install the identity broker from a local chart when provided (it is
        # unpublished, so a chart path is required to install it here). The
        # ExtProc token-exchange component is enabled when token exchange is on.
        if aib_chart_path:
            aib_extra_set = (
                _build_aib_extproc_args(
                    AUTH_EXT_PROC_CLIENT_ID, AUTH_EXT_PROC_CLIENT_SECRET
                )
                if token_exchange
                else None
            )
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
            elif token_exchange:
                _provision_token_exchange(
                    auth_admin_url,
                    AUTH_EXT_PROC_CLIENT_ID,
                    DEFAULT_THIRD_PARTY_SERVICE_ID,
                    auth_issuer,
                )
        else:
            typer.echo(
                "Note: --aib-chart-path not provided; assuming the identity broker "
                f"is already installed in namespace '{auth_namespace}'.",
            )

        # The operator's identity projection controller (enabled via
        # security.agentAuth.adminUrl on the operator chart) registers agents and
        # mints their per-agent credential Secrets directly; no separate
        # deployable is required.

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

    if redis_enabled:
        helm_args.extend(["--set", "agentDefaults.memory.type=redis"])
        redis_url = f"redis://redis-master.{namespace}:6379"
        helm_args.extend(["--set", f"agentDefaults.memory.redisUrl={redis_url}"])

    if auth_enabled:
        resolved_user_issuer = (
            user_auth_issuer
            or _default_user_auth_issuer(keycloak_namespace, keycloak_release)
            if user_auth
            else ""
        )
        helm_args.extend(
            _build_auth_operator_args(
                ext_authz_url or _default_ext_authz_url(auth_namespace),
                auth_issuer or _default_auth_issuer(auth_namespace, auth_release),
                credential_secret_prefix,
                admin_url=admin_url
                or _default_auth_admin_url(auth_namespace, auth_release),
                user_issuer=resolved_user_issuer,
                user_audience=user_auth_audience if user_auth else "",
                ext_proc_url=(
                    ext_proc_url or _default_ext_proc_url(auth_namespace, auth_release)
                    if token_exchange
                    else ""
                ),
                network_policy=network_policy,
                network_policy_egress=network_policy_egress,
                gateway_routing=gateway_routing,
                gateway_host=gateway_host or "",
                tls_mode=tls_mode or "",
                tls_issuer_name=tls_issuer_name or "",
                tls_issuer_kind=tls_issuer_kind,
                tls_secret_name=tls_secret_name or "",
                authz_provider=authz_provider or "",
                authz_gateway_extension=authz_gateway_extension or "",
                agent_jwt_verification=agent_jwt_verification or "",
                policy_data_source=policy_data_source or "",
                policy_rego_override=policy_rego_override,
                policy_configmap_name=policy_configmap_name or "",
                policy_configmap_namespace=policy_configmap_namespace or "",
            )
        )

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
    redis_enabled: bool = False,
) -> None:
    """Uninstall the KAOS operator using Helm."""
    if not check_helm_installed():
        typer.echo("Error: helm is not installed.", err=True)
        sys.exit(1)

    # Uninstall monitoring if requested
    if monitoring_enabled:
        _uninstall_monitoring(monitoring_enabled, namespace)

    # Uninstall Redis if requested
    if redis_enabled:
        _uninstall_redis(namespace)

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
