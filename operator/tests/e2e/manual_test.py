#!/usr/bin/env python3
"""
Manual testing script for E2E deployment.

This script can be run independently to manually deploy resources and test
the operator without using pytest. Useful for debugging and verification.

Usage:
    python3 manual_test.py create       # Create test resources
    python3 manual_test.py test         # Test the deployed resources
    python3 manual_test.py cleanup      # Delete test resources
    python3 manual_test.py port-forward # Start port-forward
"""

import sys
import time
import logging
import subprocess
import httpx
import asyncio
from pathlib import Path

# Add conftest to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from sh import kubectl

try:
    from .conftest import (
        create_custom_resource,
        wait_for_deployment,
        port_forward,
        create_modelapi_resource,
        create_mcpserver_resource,
        create_agent_resource,
    )
except ImportError:
    from conftest import (
        create_custom_resource,
        wait_for_deployment,
        port_forward,
        create_modelapi_resource,
        create_mcpserver_resource,
        create_agent_resource,
    )

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

TEST_NAMESPACE = "test-e2e-manual"


def create_resources():
    """Create test resources."""
    logger.info("=" * 60)
    logger.info("Creating test resources")
    logger.info("=" * 60)

    # Create namespace
    try:
        logger.info(f"Creating namespace: {TEST_NAMESPACE}")
        kubectl("create", "namespace", TEST_NAMESPACE)
    except Exception as e:
        logger.warning(f"Namespace may already exist: {e}")

    # Create ModelAPI
    logger.info("\n1. Creating ModelAPI resource...")
    modelapi_spec = create_modelapi_resource(TEST_NAMESPACE, "ollama-proxy")
    create_custom_resource(modelapi_spec, TEST_NAMESPACE)

    # Create MCPServer
    logger.info("\n2. Creating MCPServer resource...")
    mcpserver_spec = create_mcpserver_resource(TEST_NAMESPACE, "echo-server")
    create_custom_resource(mcpserver_spec, TEST_NAMESPACE)

    # Create Agent
    logger.info("\n3. Creating Agent resource...")
    agent_spec = create_agent_resource(
        namespace=TEST_NAMESPACE,
        modelapi_name="ollama-proxy",
        mcpserver_names=["echo-server"],
        agent_name="echo-agent",
    )
    create_custom_resource(agent_spec, TEST_NAMESPACE)

    logger.info("\n" + "=" * 60)
    logger.info("Resources created. Waiting for deployments...")
    logger.info("=" * 60)

    # Wait for deployments
    logger.info("\nWaiting for ModelAPI deployment...")
    wait_for_deployment(TEST_NAMESPACE, "modelapi-ollama-proxy", timeout=120)

    logger.info("\nWaiting for MCPServer deployment...")
    wait_for_deployment(TEST_NAMESPACE, "mcpserver-echo-server", timeout=120)

    logger.info("\nWaiting for Agent deployment...")
    wait_for_deployment(TEST_NAMESPACE, "agent-echo-agent", timeout=120)

    logger.info("\n" + "=" * 60)
    logger.info("✓ All deployments ready!")
    logger.info("=" * 60)

    logger.info(f"\nNext step: Run port-forward with:")
    logger.info(f"  python3 manual_test.py port-forward")
    logger.info(f"\nOr manually:")
    logger.info(f"  kubectl port-forward svc/agent-echo-agent 8000:8000 -n {TEST_NAMESPACE}")


def run_tests():
    """Test the deployed resources."""
    logger.info("=" * 60)
    logger.info("Testing deployed resources")
    logger.info("=" * 60)

    async def test_endpoints():
        agent_url = "http://localhost:8000"

        async with httpx.AsyncClient(timeout=10.0) as client:
            # Test /ready
            logger.info("\nTesting /ready endpoint...")
            try:
                response = await client.get(f"{agent_url}/ready")
                logger.info(f"  Status: {response.status_code}")
                logger.info(f"  Response: {response.json()}")
            except Exception as e:
                logger.error(f"  Error: {e}")

            # Test /health
            logger.info("\nTesting /health endpoint...")
            try:
                response = await client.get(f"{agent_url}/health")
                logger.info(f"  Status: {response.status_code}")
                logger.info(f"  Response: {response.json()}")
            except Exception as e:
                logger.error(f"  Error: {e}")

            # Test /agent/card
            logger.info("\nTesting /agent/card endpoint...")
            try:
                response = await client.get(f"{agent_url}/agent/card")
                logger.info(f"  Status: {response.status_code}")
                card = response.json()
                logger.info(f"  Agent: {card['name']}")
                logger.info(f"  Description: {card['description']}")
                tools = card.get("tools", [])
                logger.info(f"  Tools: {[t.get('name') for t in tools]}")
                logger.info(f"  Capabilities: {card['capabilities']}")
            except Exception as e:
                logger.error(f"  Error: {e}")

    asyncio.run(test_endpoints())

    logger.info("\n" + "=" * 60)
    logger.info("✓ Tests complete!")
    logger.info("=" * 60)


def start_port_forward():
    """Start port-forward to agent service."""
    logger.info("=" * 60)
    logger.info("Starting port-forward")
    logger.info("=" * 60)

    logger.info(f"\nPort-forwarding agent-echo-agent service...")
    logger.info(f"Local: http://localhost:8000")
    logger.info(f"Service: svc/agent-echo-agent in {TEST_NAMESPACE}")
    logger.info(f"\nPress Ctrl+C to stop\n")

    try:
        process = subprocess.Popen(
            ["kubectl", "port-forward", f"svc/agent-echo-agent", "8000:8000",
             "-n", TEST_NAMESPACE],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        process.wait()
    except KeyboardInterrupt:
        logger.info("\nPort-forward stopped")
    except Exception as e:
        logger.error(f"Error: {e}")


def cleanup():
    """Delete test resources."""
    logger.info("=" * 60)
    logger.info("Cleaning up test resources")
    logger.info("=" * 60)

    logger.info(f"Deleting namespace: {TEST_NAMESPACE}")
    try:
        kubectl("delete", "namespace", TEST_NAMESPACE)
        logger.info(f"Namespace {TEST_NAMESPACE} deleted")
    except Exception as e:
        logger.error(f"Error deleting namespace {TEST_NAMESPACE}: {e}")

    logger.info("\n" + "=" * 60)
    logger.info("✓ Cleanup complete!")
    logger.info("=" * 60)


def check_prerequisites():
    """Check if all prerequisites are available."""
    logger.info("=" * 60)
    logger.info("Checking prerequisites")
    logger.info("=" * 60)

    checks = []

    # Check kubectl
    logger.info("\n1. Checking kubectl...")
    try:
        result = subprocess.run(["kubectl", "cluster-info"], capture_output=True, text=True)
        if result.returncode == 0:
            logger.info("  ✓ kubectl available")
            checks.append(True)
        else:
            logger.error(f"  ✗ kubectl error: {result.stderr}")
            checks.append(False)
    except Exception as e:
        logger.error(f"  ✗ kubectl not found: {e}")
        checks.append(False)

    # Check context
    logger.info("\n2. Checking Kubernetes context...")
    try:
        result = subprocess.run(["kubectl", "config", "current-context"],
                              capture_output=True, text=True)
        context = result.stdout.strip()
        logger.info(f"  Current context: {context}")
        checks.append(True)
    except Exception as e:
        logger.error(f"  ✗ Error: {e}")
        checks.append(False)

    # Check operator deployment
    logger.info("\n3. Checking operator deployment...")
    try:
        result = subprocess.run(
            ["kubectl", "get", "deployment", "-n", "agentic-system"],
            capture_output=True, text=True
        )
        if "agentic-operator-controller-manager" in result.stdout:
            logger.info("  ✓ Operator deployed")
            checks.append(True)
        else:
            logger.warning("  ⚠ Operator not found in agentic-system")
            checks.append(False)
    except Exception as e:
        logger.warning(f"  ⚠ Could not check operator: {e}")
        checks.append(False)

    # Check Ollama
    logger.info("\n4. Checking Ollama (via host.docker.internal)...")
    try:
        response = httpx.get("http://host.docker.internal:11434/api/tags", timeout=2)
        if response.status_code == 200:
            logger.info("  ✓ Ollama accessible")
            checks.append(True)
        else:
            logger.warning(f"  ⚠ Ollama returned {response.status_code}")
            checks.append(False)
    except Exception as e:
        logger.warning(f"  ⚠ Ollama not accessible: {e}")
        checks.append(False)

    logger.info("\n" + "=" * 60)
    if all(checks):
        logger.info("✓ All prerequisites met!")
    else:
        logger.warning("⚠ Some prerequisites missing. Tests may fail.")
    logger.info("=" * 60)


def main():
    """Main entry point."""
    if len(sys.argv) < 2:
        print("""
Usage: python3 manual_test.py <command>

Commands:
  check         Check prerequisites
  create        Create test resources
  test          Test deployed resources (requires port-forward running)
  port-forward  Start port-forward to agent service
  cleanup       Delete test resources

Examples:
  python3 manual_test.py check           # Check prerequisites
  python3 manual_test.py create          # Create resources
  python3 manual_test.py port-forward    # Start port-forward
  python3 manual_test.py test            # Test endpoints (in another terminal)
  python3 manual_test.py cleanup         # Clean up
        """)
        sys.exit(1)

    command = sys.argv[1]

    if command == "check":
        check_prerequisites()
    elif command == "create":
        create_resources()
    elif command == "test":
        run_tests()
    elif command == "port-forward":
        start_port_forward()
    elif command == "cleanup":
        cleanup()
    else:
        logger.error(f"Unknown command: {command}")
        sys.exit(1)


if __name__ == "__main__":
    main()
