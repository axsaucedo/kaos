"""End-to-end tests for ModelAPI resource deployment.

Tests via Gateway API:
- ModelAPI Proxy mode with mock_response (no backend needed)
- ModelAPI Proxy mode with real Ollama backend
- ModelAPI Hosted mode with Ollama

NOTE: These tests do NOT use shared_modelapi fixture because they test
specific ModelAPI configurations and functionality.
"""

import time
import pytest
import httpx

from e2e.conftest import (
    create_custom_resource,
    wait_for_deployment,
    wait_for_resource_ready,
    gateway_url,
    create_modelapi_resource,
    port_forward,
    get_next_port,
)


@pytest.mark.asyncio
async def test_modelapi_proxy_deployment(test_namespace: str):
    """Test ModelAPI Proxy mode deployment and health check."""
    name = "proxy-deploy"
    modelapi_spec = create_modelapi_resource(test_namespace, name)
    create_custom_resource(modelapi_spec, test_namespace)

    wait_for_deployment(test_namespace, f"modelapi-{name}", timeout=120)

    modelapi_url = gateway_url(test_namespace, "modelapi", name)
    wait_for_resource_ready(modelapi_url, health_path="/health/liveliness")

    async with httpx.AsyncClient() as client:
        # Health check
        response = await client.get(f"{modelapi_url}/health/liveliness", timeout=10.0)
        assert response.status_code == 200
        
        # Models endpoint
        response = await client.get(f"{modelapi_url}/models", timeout=10.0)
        assert response.status_code == 200


@pytest.mark.asyncio
async def test_modelapi_proxy_mock_response(test_namespace: str):
    """Test ModelAPI Proxy mode with mock_response (no real LLM backend)."""
    name = "mock-resp"
    modelapi_spec = create_modelapi_resource(test_namespace, name)
    create_custom_resource(modelapi_spec, test_namespace)

    wait_for_deployment(test_namespace, f"modelapi-{name}", timeout=120)

    modelapi_url = gateway_url(test_namespace, "modelapi", name)
    wait_for_resource_ready(modelapi_url, health_path="/health/liveliness")

    async with httpx.AsyncClient(timeout=30.0) as client:
        # Test mock_response
        response = await client.post(
            f"{modelapi_url}/v1/chat/completions",
            json={
                "model": "gpt-3.5-turbo",
                "messages": [{"role": "user", "content": "test"}],
                "mock_response": "This is a deterministic mock response",
            },
        )
        assert response.status_code == 200
        data = response.json()
        
        # Verify the mock response is returned
        assert "choices" in data
        assert len(data["choices"]) > 0
        assert "This is a deterministic mock response" in data["choices"][0]["message"]["content"]


@pytest.mark.asyncio
async def test_modelapi_proxy_with_hosted_backend(test_namespace: str):
    """Test ModelAPI Proxy mode pointing to a Hosted ModelAPI backend.
    
    This test creates two ModelAPIs:
    1. A Hosted ModelAPI running Ollama with smollm2:135m
    2. A Proxy ModelAPI (LiteLLM) that routes to the Hosted backend
    
    This validates the full proxy chain without requiring external services.
    Uses Gateway API with custom timeout to allow for LLM inference time.
    """
    # Step 1: Create the Hosted backend (Ollama in-cluster)
    backend_name = "proxy-backend"
    backend_spec = {
        "apiVersion": "ethical.institute/v1alpha1",
        "kind": "ModelAPI",
        "metadata": {"name": backend_name, "namespace": test_namespace},
        "spec": {
            "mode": "Hosted",
            "hostedConfig": {
                "model": "smollm2:135m",
                "env": [{"name": "OLLAMA_DEBUG", "value": "false"}],
            },
        },
    }
    create_custom_resource(backend_spec, test_namespace)
    
    # Wait for Hosted backend to be ready (longer timeout for model pull)
    wait_for_deployment(test_namespace, f"modelapi-{backend_name}", timeout=180)
    
    # Give Ollama time to fully initialize after deployment is ready
    time.sleep(5)
    
    # Step 2: Create the Proxy that points to the Hosted backend
    # The Hosted ModelAPI service is at: modelapi-{backend_name}.{namespace}:11434
    # Configure gatewayRoute.timeout to 120s to allow for LLM inference
    proxy_name = "proxy-chain"
    proxy_spec = {
        "apiVersion": "ethical.institute/v1alpha1",
        "kind": "ModelAPI",
        "metadata": {"name": proxy_name, "namespace": test_namespace},
        "spec": {
            "mode": "Proxy",
            "proxyConfig": {
                "apiBase": f"http://modelapi-{backend_name}.{test_namespace}:11434",
                "model": "ollama/smollm2:135m",
                "env": [{"name": "OPENAI_API_KEY", "value": "sk-test"}]
            },
            "gatewayRoute": {
                "timeout": "120s",
            },
        },
    }
    create_custom_resource(proxy_spec, test_namespace)
    
    wait_for_deployment(test_namespace, f"modelapi-{proxy_name}", timeout=120)
    
    # Use Gateway API URL with the extended timeout configured in the CRD
    proxy_url = gateway_url(test_namespace, "modelapi", proxy_name)
    wait_for_resource_ready(proxy_url, health_path="/health/liveliness")
    
    async with httpx.AsyncClient(timeout=120.0) as client:
        # Test proxy health
        response = await client.get(f"{proxy_url}/health/liveliness", timeout=10.0)
        assert response.status_code == 200
        
        # Test actual model inference through the proxy chain via Gateway
        response = await client.post(
            f"{proxy_url}/v1/chat/completions",
            json={
                "model": "ollama/smollm2:135m",
                "messages": [{"role": "user", "content": "Say hello"}],
                "max_tokens": 20,
            },
            timeout=90.0,
        )
        assert response.status_code == 200
        data = response.json()
        
        # Verify we got a real response from Ollama through the proxy
        assert "choices" in data
        assert len(data["choices"]) > 0
        assert len(data["choices"][0]["message"]["content"]) > 0


@pytest.mark.asyncio
async def test_modelapi_hosted_ollama(test_namespace: str):
    """Test ModelAPI Hosted mode with Ollama (smollm2:135m model).
    
    Note: Hosted mode runs Ollama on port 11434, not 8000.
    Gateway API HTTPRoute is for port 8000, so we use port-forward for this test.
    """
    name = "hosted"
    modelapi_spec = {
        "apiVersion": "ethical.institute/v1alpha1",
        "kind": "ModelAPI",
        "metadata": {"name": name, "namespace": test_namespace},
        "spec": {
            "mode": "Hosted",
            "hostedConfig": {
                "model": "smollm2:135m",
                "env": [{"name": "OLLAMA_DEBUG", "value": "false"}],
            },
        },
    }
    create_custom_resource(modelapi_spec, test_namespace)

    # Hosted mode uses longer timeout for model pull
    wait_for_deployment(test_namespace, f"modelapi-{name}", timeout=180)

    # For hosted mode, use port-forward since it's on port 11434
    port = get_next_port()
    pf = port_forward(test_namespace, f"modelapi-{name}", port, 11434)
    time.sleep(3)

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            # Test Ollama health (root endpoint)
            response = await client.get(f"http://localhost:{port}/", timeout=30.0)
            assert response.status_code == 200
    finally:
        pf.terminate()
        pf.wait(timeout=5)
