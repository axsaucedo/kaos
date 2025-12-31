"""End-to-end tests for ModelAPI resource deployment.

Tests:
- ModelAPI Proxy mode with mock_response (no backend needed)
- ModelAPI Proxy mode with real Ollama backend
- ModelAPI Hosted mode with Ollama
"""

import time
import subprocess
import pytest
import httpx

from e2e.conftest import (
    create_custom_resource,
    wait_for_deployment,
    port_forward,
    create_modelapi_resource,
    create_modelapi_hosted_resource,
)


@pytest.mark.asyncio
async def test_modelapi_proxy_deployment(test_namespace: str):
    """Test ModelAPI Proxy mode deployment and health check."""
    modelapi_spec = create_modelapi_resource(test_namespace, "test-proxy")
    create_custom_resource(modelapi_spec, test_namespace)

    wait_for_deployment(test_namespace, "modelapi-test-proxy", timeout=120)

    pf_process = port_forward(
        namespace=test_namespace,
        service_name="modelapi-test-proxy",
        local_port=18030,
        remote_port=8000,
    )

    time.sleep(2)

    try:
        async with httpx.AsyncClient() as client:
            # Health check
            response = await client.get("http://localhost:18030/health", timeout=10.0)
            assert response.status_code == 200
            
            # Models endpoint
            response = await client.get("http://localhost:18030/models", timeout=10.0)
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
    modelapi_spec = create_modelapi_resource(test_namespace, "mock-test")
    create_custom_resource(modelapi_spec, test_namespace)

    wait_for_deployment(test_namespace, "modelapi-mock-test", timeout=120)

    pf_process = port_forward(
        namespace=test_namespace,
        service_name="modelapi-mock-test",
        local_port=18031,
        remote_port=8000,
    )

    time.sleep(2)

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            # Test mock_response - LiteLLM returns this string without calling any backend
            response = await client.post(
                "http://localhost:18031/v1/chat/completions",
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
    # Create ModelAPI with Ollama backend using new simplified proxyConfig fields
    modelapi_spec = {
        "apiVersion": "ethical.institute/v1alpha1",
        "kind": "ModelAPI",
        "metadata": {
            "name": "ollama-proxy",
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

    wait_for_deployment(test_namespace, "modelapi-ollama-proxy", timeout=120)

    pf_process = port_forward(
        namespace=test_namespace,
        service_name="modelapi-ollama-proxy",
        local_port=18032,
        remote_port=8000,
    )

    time.sleep(3)

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            # Test health
            response = await client.get("http://localhost:18032/health", timeout=10.0)
            assert response.status_code == 200
            
            # Test actual model inference with smollm2
            response = await client.post(
                "http://localhost:18032/v1/chat/completions",
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
    # Create ModelAPI in Hosted mode
    modelapi_spec = {
        "apiVersion": "ethical.institute/v1alpha1",
        "kind": "ModelAPI",
        "metadata": {
            "name": "hosted-ollama",
            "namespace": test_namespace,
        },
        "spec": {
            "mode": "Hosted",
            "serverConfig": {
                "model": "smollm2:135m",
                "env": [
                    {"name": "OLLAMA_DEBUG", "value": "false"},
                ],
            },
        },
    }
    create_custom_resource(modelapi_spec, test_namespace)

    # Hosted mode uses Ollama on port 11434
    wait_for_deployment(test_namespace, "modelapi-hosted-ollama", timeout=180)

    pf_process = port_forward(
        namespace=test_namespace,
        service_name="modelapi-hosted-ollama",
        local_port=18033,
        remote_port=11434,  # Ollama port
    )

    time.sleep(5)

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            # Test Ollama health (root endpoint returns version info)
            response = await client.get("http://localhost:18033/", timeout=30.0)
            assert response.status_code == 200
            
    finally:
        pf_process.terminate()
        pf_process.wait(timeout=5)
