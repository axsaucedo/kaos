"""CORS-enabled Kubernetes API proxy with SSE streaming support."""

import ssl
from typing import AsyncGenerator

import httpx
from kubernetes import client, config
from starlette.applications import Starlette
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import Response, StreamingResponse
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
        """Proxy incoming requests to the Kubernetes API server.
        
        Supports SSE streaming for text/event-stream responses by using
        httpx streaming and yielding chunks as they arrive.
        """
        path = request.url.path
        query = str(request.url.query) if request.url.query else ""
        target_url = f"{api_url}{path}"
        if query:
            target_url = f"{target_url}?{query}"

        # Start with auth headers
        headers = dict(auth_headers)

        # Copy relevant headers from request
        for key in ["content-type", "accept", "mcp-session-id", "cache-control", "x-session-id"]:
            if key in request.headers:
                headers[key] = request.headers[key]

        # Get request body
        body = await request.body()
        
        # Check if this is likely an SSE streaming request
        accept_header = request.headers.get("accept", "")
        is_sse_request = "text/event-stream" in accept_header

        if is_sse_request:
            # Use streaming for SSE requests to avoid buffering
            return await _stream_proxy_request(
                target_url, request.method, headers, body, ssl_context
            )
        else:
            # Regular non-streaming request
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
    
    async def _stream_proxy_request(
        target_url: str,
        method: str,
        headers: dict[str, str],
        body: bytes | None,
        ssl_ctx: ssl.SSLContext | bool,
    ) -> StreamingResponse:
        """Proxy a streaming request, yielding chunks as they arrive.
        
        This is essential for SSE (Server-Sent Events) to work properly,
        as the client expects to receive events incrementally.
        """
        async def generate() -> AsyncGenerator[bytes, None]:
            async with httpx.AsyncClient(verify=ssl_ctx, timeout=120.0) as http_client:
                async with http_client.stream(
                    method=method,
                    url=target_url,
                    headers=headers,
                    content=body if body else None,
                ) as response:
                    async for chunk in response.aiter_bytes():
                        yield chunk
        
        # Create streaming response with SSE headers
        # Note: We can't easily get the actual status code from the stream before
        # starting to yield, so we assume 200 for streaming. Errors will be in the stream.
        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",  # Disable nginx buffering
            },
        )

    routes = [
        Route(
            "/{path:path}",
            proxy_request,
            methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
        ),
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
