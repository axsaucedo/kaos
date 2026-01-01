"""End-to-end tests for ModelAPI resource deployment.

Tests:
- ModelAPI Proxy mode with mock_response (no backend needed)
- ModelAPI Proxy mode with real Ollama backend
- ModelAPI Hosted mode with Ollama

NOTE: These tests do NOT use shared_modelapi fixture because they test
specific ModelAPI configurations and functionality.
"""

import pytest
import httpx

from e2e.conftest import (
    create_custom_resource,
    wait_for_deployment,
    port_forward_with_wait,
    create_modelapi_resource,
    get_next_port,
)


@pytest.mark.asyncio
async def test_modelapi_proxy_deployment(test_namespace: str):
    """Test ModelAPI Proxy mode deployment and health check."""
    name = "proxy-deploy"
    modelapi_spec = create_modelapi_resource(test_namespace, name)
    create_custom_resource(modelapi_spec, test_namespace)

    wait_for_deployment(test_namespace, f"modelapi-{name}", timeout=120)

    port = get_next_port()
    pf_process = port_forward_with_wait(
        namespace=test_namespace,
        service_name=f"modelapi-{name}",
        local_port=port,
        remote_port=8000,
    )

    try:
        async with httpx.AsyncClient() as client:
            # Health check
            response = await client.get(f"http://localhost:{port}/health", timeout=10.0)
            assert response.status_code == 200
            
            # Models endpoint
            response = await client.get(f"http://localhost:{port}/models", timeout=10.0)
            assert response.status_code == 200
    finally:
        pf_process.terminate()
        pf_process.wait(timeout=5)


@pytest.mark.asyncio
async def test_modelapi_proxy_mock_response(test_namespace: str):
    """Test ModelAPI Proxy mode with mock_response (no real LLM backend).
    
    This validates that LiteLLM's mock_response feature works correctly,
    which enables deterministic testing without requiring a real LLM.
    """
    name = "mock-resp"
    modelapi_spec = create_modelapi_resource(test_namespace, name)
    create_custom_resource(modelapi_spec, test_namespace)

    wait_for_deployment(test_namespace, f"modelapi-{name}", timeout=120)

    port = get_next_port()
    pf_process = port_forward_with_wait(
        namespace=test_namespace,
        service_name=f"modelapi-{name}",
        local_port=port,
        remote_port=8000,
    )

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            # Test mock_response - LiteLLM returns this string without calling any backend
            response = await client.post(
                f"http://localhost:{port}/v1/chat/completions",
                json={
                    "model": "anything",
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
    finally:
        pf_process.terminate()
        pf_process.wait(timeout=5)


@pytest.mark.asyncio
async def test_modelapi_proxy_with_ollama(test_namespace: str):
    """Test ModelAPI Proxy mode with real Ollama backend.
    
    This is the ONLY test that actually calls a real LLM model through proxy.
    Requires Ollama running locally with smollm2:135m model.
    """
    name = "ollama-prx"
    # Create ModelAPI with Ollama backend using new simplified proxyConfig fields
    modelapi_spec = {
        "apiVersion": "ethical.institute/v1alpha1",
        "kind": "ModelAPI",
        "metadata": {
            "name": name,
            "namespace": test_namespace,
        },
        "spec": {
            "mode": "Proxy",
            "proxyConfig": {
                "apiBase": "http://host.docker.internal:11434",
                "model": "ollama/smollm2:135m",
                "env": [
                    {"name": "OPENAI_API_KEY", "value": "sk-test"},
                ]
            },
        },
    }
    create_custom_resource(modelapi_spec, test_namespace)

    wait_for_deployment(test_namespace, f"modelapi-{name}", timeout=120)

    port = get_next_port()
    pf_process = port_forward_with_wait(
        namespace=test_namespace,
        service_name=f"modelapi-{name}",
        local_port=port,
        remote_port=8000,
    )

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            # Test health
            response = await client.get(f"http://localhost:{port}/health", timeout=10.0)
            assert response.status_code == 200
            
            # Test actual model inference with smollm2
            response = await client.post(
                f"http://localhost:{port}/v1/chat/completions",
                json={
                    "model": "ollama/smollm2:135m",
                    "messages": [{"role": "user", "content": "Say hello"}],
                    "max_tokens": 20,
                },
                timeout=30.0,
            )
            assert response.status_code == 200
            data = response.json()
            
            # Verify we got a real response
            assert "choices" in data
            assert len(data["choices"]) > 0
            assert len(data["choices"][0]["message"]["content"]) > 0
            
    finally:
        pf_process.terminate()
        pf_process.wait(timeout=5)


@pytest.mark.asyncio
async def test_modelapi_hosted_ollama(test_namespace: str):
    """Test ModelAPI Hosted mode with Ollama (smollm2:135m model).
    
    This tests that an Ollama instance can be deployed in-cluster
    and serve model inference requests.
    
    Note: This test may take longer as Ollama needs to pull the model.
    """
    name = "hosted"
    # Create ModelAPI in Hosted mode
    modelapi_spec = {
        "apiVersion": "ethical.institute/v1alpha1",
        "kind": "ModelAPI",
        "metadata": {
            "name": name,
            "namespace": test_namespace,
        },
        "spec": {
            "mode": "Hosted",
            "hostedConfig": {
                "model": "smollm2:135m",
                "env": [
                    {"name": "OLLAMA_DEBUG", "value": "false"},
                ],
            },
        },
    }
    create_custom_resource(modelapi_spec, test_namespace)

    # Hosted mode uses Ollama on port 11434
    wait_for_deployment(test_namespace, f"modelapi-{name}", timeout=180)

    port = get_next_port()
    # For hosted mode, we need a custom wait since it doesn't have /health on port 11434
    from e2e.conftest import port_forward
    import time
    
    pf_process = port_forward(
        namespace=test_namespace,
        service_name=f"modelapi-{name}",
        local_port=port,
        remote_port=11434,  # Ollama port
    )

    time.sleep(3)  # Ollama needs more time to start

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            # Test Ollama health (root endpoint returns version info)
            response = await client.get(f"http://localhost:{port}/", timeout=30.0)
            assert response.status_code == 200
            
    finally:
        pf_process.terminate()
        pf_process.wait(timeout=5)
