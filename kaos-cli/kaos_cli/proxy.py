"""CORS-enabled Kubernetes API proxy."""

import ssl

import httpx
from kubernetes import client, config
from starlette.applications import Starlette
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Route


def create_proxy_app(k8s_url: str | None = None) -> Starlette:
    """Create a Starlette app that proxies requests to the K8s API with CORS."""
    # Load kubernetes config
    try:
        config.load_incluster_config()
    except config.ConfigException:
        config.load_kube_config()

    configuration = client.Configuration.get_default_copy()

    # Use provided URL or from kubeconfig
    api_url = k8s_url or configuration.host

    # Get auth info from configuration
    auth_headers: dict[str, str] = {}
    if configuration.api_key and "authorization" in configuration.api_key:
        auth_headers["Authorization"] = configuration.api_key["authorization"]
    elif configuration.api_key_prefix and configuration.api_key:
        for key, value in configuration.api_key.items():
            prefix = configuration.api_key_prefix.get(key, "")
            auth_headers["Authorization"] = f"{prefix} {value}".strip()
            break

    # SSL/TLS configuration - handle client certificates
    ssl_context: ssl.SSLContext | bool = False
    if configuration.cert_file and configuration.key_file:
        ssl_context = ssl.create_default_context()
        ssl_context.load_cert_chain(
            certfile=configuration.cert_file,
            keyfile=configuration.key_file,
        )
        if configuration.ssl_ca_cert:
            ssl_context.load_verify_locations(cafile=configuration.ssl_ca_cert)
        else:
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE
    elif configuration.ssl_ca_cert:
        ssl_context = ssl.create_default_context(cafile=configuration.ssl_ca_cert)

    async def proxy_request(request: Request) -> Response:
        """Proxy incoming requests to the Kubernetes API server."""
        path = request.url.path
        query = str(request.url.query) if request.url.query else ""
        target_url = f"{api_url}{path}"
        if query:
            target_url = f"{target_url}?{query}"

        # Start with auth headers
        headers = dict(auth_headers)

        # Copy relevant headers from request
        for key in ["content-type", "accept", "mcp-session-id"]:
            if key in request.headers:
                headers[key] = request.headers[key]

        # Get request body
        body = await request.body()

        async with httpx.AsyncClient(verify=ssl_context, timeout=120.0) as http_client:
            response = await http_client.request(
                method=request.method,
                url=target_url,
                headers=headers,
                content=body if body else None,
            )

            # Build response headers
            response_headers = dict(response.headers)

            return Response(
                content=response.content,
                status_code=response.status_code,
                headers=response_headers,
                media_type=response.headers.get("content-type"),
            )

    routes = [
        Route("/{path:path}", proxy_request, methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"]),
    ]

    app = Starlette(routes=routes)

    # Add CORS middleware with mcp-session-id exposed
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["mcp-session-id"],
    )

    return app
