"""Authentication provider installation and Helm argument helpers."""

import json

import typer

from . import (
    AUTH_ADMIN_PORT, AUTH_ENDUSER_PORT, DEFAULT_AGENT_AUTH_AUDIENCE,
    DEFAULT_KEYCLOAK_ADMIN_PASSWORD, DEFAULT_KEYCLOAK_ADMIN_USER,
    DEFAULT_KEYCLOAK_IMAGE, DEFAULT_OIDC_REGISTRATION_SECRET_KEY,
    DEFAULT_OIDC_REGISTRATION_SECRET_NAME, DEFAULT_TOKEN_EXCHANGE_AUDIENCE,
    DEFAULT_USER_AUTH_CLIENT_ID, DEFAULT_USER_AUTH_CLIENT_SECRET,
    DEFAULT_USER_AUTH_REALM, DEFAULT_USER_AUTH_TEST_PASSWORD,
    DEFAULT_USER_AUTH_TEST_USER, KEYCLOAK_HTTP_PORT,
)


def _root():
    """Resolve shared helpers through the public package for compatibility."""
    import kaos_cli.install as root

    return root
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

    result = _root().run_helm_command(helm_args, check=False)
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

def _build_token_exchange_aib_args(
    auth_namespace: str,
    auth_release: str,
    keycloak_issuer: str,
) -> list[str]:
    """Configure the self-managed AIB release for Keycloak-backed exchange."""
    aib_issuer = _default_auth_issuer(auth_namespace, auth_release)
    keycloak_token_endpoint = f"{keycloak_issuer}/protocol/openid-connect/token"
    keycloak_authorize_endpoint = f"{keycloak_issuer}/protocol/openid-connect/auth"
    extra_env = [
        {"name": "EXTPROC_OAUTH2_ISSUER", "value": keycloak_issuer},
        {"name": "EXTPROC_OAUTH2_CLIENT_ID", "value": DEFAULT_USER_AUTH_CLIENT_ID},
        {
            "name": "EXTPROC_OAUTH2_CLIENT_SECRET",
            "value": DEFAULT_USER_AUTH_CLIENT_SECRET,
        },
        {"name": "EXTPROC_OAUTH2_CLIENT_ASSERTION_TYPE", "value": "access_token"},
    ]
    return [
        "--set",
        f"broker.server.enduser.publicUrl={aib_issuer}",
        "--set",
        "broker.oauth2AuthorizationServer.mode=proxy",
        "--set",
        f"broker.oauth2AuthorizationServer.proxy.upstreamIssuerUri={keycloak_issuer}",
        "--set",
        "broker.oauth2AuthorizationServer.proxy.upstreamAuthorizeEndpoint="
        f"{keycloak_authorize_endpoint}",
        "--set",
        f"broker.oauth2AuthorizationServer.proxy.upstreamTokenEndpoint={keycloak_token_endpoint}",
        "--set",
        f"broker.tokenExchange.expectedAudience={DEFAULT_TOKEN_EXCHANGE_AUDIENCE}",
        "--set",
        "broker.tokenExchange.claimExtraction.principalExpression=subject_token.sub",
        "--set",
        "broker.tokenExchange.claimExtraction.agentIdExpression="
        "resolveAgentIdByClientId(subject_token.azp)",
        "--set",
        "broker.tokenExchange.authorization.type=cel",
        "--set",
        "broker.tokenExchange.authorization.cel.expression="
        f'client_assertion.azp == "{DEFAULT_USER_AUTH_CLIENT_ID}"',
        "--set",
        "extProc.enabled=true",
        "--set",
        f"extProc.oauth2.clientCredentialsEndpoint={keycloak_token_endpoint}",
        "--set-json",
        f"extProc.extraEnv={json.dumps(extra_env, separators=(',', ':'))}",
    ]

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
                        "name": "token-exchange-audience",
                        "protocol": "openid-connect",
                        "protocolMapper": "oidc-audience-mapper",
                        "config": {
                            "included.custom.audience": DEFAULT_TOKEN_EXCHANGE_AUDIENCE,
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

    apply_ns = _root()._run_kubectl(
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

    result = _root()._run_kubectl(
        ["apply", "-f", "-"], check=False, input=json.dumps(configmap)
    )
    if result.returncode != 0:
        typer.echo(f"Error bootstrapping Keycloak realm: {result.stderr}", err=True)
        return False
    typer.echo(f"✅ Keycloak realm '{realm}' bootstrap manifest applied")
    return True

def _keycloak_dev_manifests(
    namespace: str, release: str, token_exchange_enabled: bool = False
) -> list[dict]:
    """Self-contained Keycloak dev deployment (start-dev, H2 in-memory, no DB).

    Mounts the realm-import ConfigMap and runs with --import-realm so the
    bootstrapped realm/client/user are available on startup. Intended for local
    and e2e validation only.
    """
    labels = {"app": release}
    configmap_name = _keycloak_realm_configmap_name(release)
    args = ["start-dev", "--import-realm"]
    if token_exchange_enabled:
        args.append("--features=token-exchange,admin-fine-grained-authz")

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
                            "args": args,
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
    token_exchange_enabled: bool = False,
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
        result = _root().run_helm_command(helm_args, check=False)
        if result.returncode != 0:
            typer.echo(f"Error installing Keycloak: {result.stderr}", err=True)
            return False
    else:
        for manifest in _keycloak_dev_manifests(
            namespace, release, token_exchange_enabled
        ):
            result = _root()._run_kubectl(
                ["apply", "-f", "-"], check=False, input=json.dumps(manifest)
            )
            if result.returncode != 0:
                typer.echo(f"Error installing Keycloak: {result.stderr}", err=True)
                return False

    typer.echo(f"✅ Keycloak installed in '{namespace}' namespace")
    return True
