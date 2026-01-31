"""
Consolidated Agent Server E2E tests.

Tests the actual Agent server running with HTTP client communication.
Includes single agent, multi-agent, and delegation scenarios.
Requires Ollama running locally with smollm2:135m model.
"""

import pytest
import httpx
import time
import logging
import json
from multiprocessing import Process

from agent.server import AgentServerSettings, create_agent_server
from agent.client import RemoteAgent

logger = logging.getLogger(__name__)


def run_agent_server(
    port: int,
    model_url: str,
    model_name: str,
    agent_name: str,
    instructions: str = "You are a helpful assistant. Be brief.",
    sub_agents_config: str = "",
):
    """Run agent server in subprocess (memory endpoints always enabled)."""
    settings = AgentServerSettings(
        agent_name=agent_name,
        agent_description=f"Agent: {agent_name}",
        agent_instructions=instructions,
        agent_port=port,
        model_api_url=model_url,
        model_name=model_name,
        agent_log_level="WARNING",
        agent_sub_agents=sub_agents_config,
    )
    server = create_agent_server(settings)
    server.run()


def wait_for_server(url: str, timeout: int = 30) -> bool:
    """Wait for server to be ready."""
    for _ in range(timeout * 2):
        try:
            response = httpx.get(f"{url}/ready", timeout=2.0)
            if response.status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


@pytest.fixture(scope="module")
def ollama_available():
    """Check if Ollama is available."""
    try:
        response = httpx.get("http://localhost:11434/api/tags", timeout=5.0)
        return response.status_code == 200
    except Exception:
        return False


@pytest.fixture(scope="module")
def single_agent_server(ollama_available):
    """Fixture that starts a single agent server."""
    if not ollama_available:
        pytest.skip("Ollama not available")

    port = 8060
    process = Process(
        target=run_agent_server,
        args=(port, "http://localhost:11434", "smollm2:135m", "test-agent"),
    )
    process.start()

    if not wait_for_server(f"http://localhost:{port}"):
        process.terminate()
        process.join(timeout=5)
        pytest.fail("Agent server did not start")

    yield {"url": f"http://localhost:{port}", "name": "test-agent"}

    process.terminate()
    process.join(timeout=5)


@pytest.fixture(scope="module")
def multi_agent_cluster(ollama_available):
    """Fixture that starts coordinator + 2 worker agents."""
    if not ollama_available:
        pytest.skip("Ollama not available")

    model_url = "http://localhost:11434"
    model_name = "smollm2:135m"

    processes = []
    agents = []

    # Start workers first
    for i, (name, port) in enumerate([("worker-1", 8070), ("worker-2", 8071)]):
        p = Process(
            target=run_agent_server,
            args=(
                port,
                model_url,
                model_name,
                name,
                f"You are {name}. Always mention your name in responses. Be brief.",
            ),
        )
        p.start()
        processes.append(p)
        agents.append({"name": name, "port": port, "url": f"http://localhost:{port}"})

    # Wait for workers
    for agent in agents:
        if not wait_for_server(agent["url"]):
            for p in processes:
                p.terminate()
                p.join(timeout=5)
            pytest.fail(f"Worker {agent['name']} did not start")

    # Start coordinator with sub-agents
    coord_port = 8072
    sub_agents_config = "worker-1:http://localhost:8070,worker-2:http://localhost:8071"
    coord_process = Process(
        target=run_agent_server,
        args=(
            coord_port,
            model_url,
            model_name,
            "coordinator",
            "You are the coordinator.",
            sub_agents_config,
        ),
    )
    coord_process.start()
    processes.append(coord_process)

    coord_url = f"http://localhost:{coord_port}"
    if not wait_for_server(coord_url):
        for p in processes:
            p.terminate()
            p.join(timeout=5)
        pytest.fail("Coordinator did not start")

    agents.append({"name": "coordinator", "port": coord_port, "url": coord_url})

    yield {"agents": agents, "urls": {a["name"]: a["url"] for a in agents}}

    for p in processes:
        p.terminate()
        p.join(timeout=5)


class TestSingleAgentServer:
    """Tests for single agent server functionality."""

    def test_server_health_discovery_and_invocation(self, single_agent_server):
        """Test complete single agent workflow: health, discovery, invocation, memory."""
        url = single_agent_server["url"]

        # 1. Health and Ready endpoints
        health = httpx.get(f"{url}/health").json()
        assert health["status"] == "healthy"
        assert health["name"] == "test-agent"

        ready = httpx.get(f"{url}/ready").json()
        assert ready["status"] == "ready"

        # 2. Agent card discovery
        card = httpx.get(f"{url}/.well-known/agent").json()
        assert card["name"] == "test-agent"
        assert "message_processing" in card["capabilities"]
        assert "skills" in card

        # 3. Chat completions (OpenAI-compatible)
        invoke_resp = httpx.post(
            f"{url}/v1/chat/completions",
            json={
                "model": "test-agent",
                "messages": [{"role": "user", "content": "Say hello briefly"}],
                "stream": False,
            },
            timeout=60.0,
        )
        assert invoke_resp.status_code == 200
        invoke_data = invoke_resp.json()
        assert invoke_data["object"] == "chat.completion"
        assert len(invoke_data["choices"]) > 0
        assert len(invoke_data["choices"][0]["message"]["content"]) > 0

        # 4. Verify memory events
        memory = httpx.get(f"{url}/memory/events").json()
        assert memory["agent"] == "test-agent"
        assert memory["total"] >= 2  # user_message + agent_response

        event_types = [e["event_type"] for e in memory["events"]]
        assert "user_message" in event_types
        assert "agent_response" in event_types

        logger.info("✓ Single agent workflow complete")

    def test_chat_completions_non_streaming(self, single_agent_server):
        """Test OpenAI-compatible chat completions (non-streaming) with single and multi-turn."""
        url = single_agent_server["url"]

        # Test 1: Single message
        response = httpx.post(
            f"{url}/v1/chat/completions",
            json={
                "model": "test-agent",
                "messages": [{"role": "user", "content": "Say OK"}],
                "stream": False,
            },
            timeout=60.0,
        )

        assert response.status_code == 200
        data = response.json()

        # Verify OpenAI format
        assert data["object"] == "chat.completion"
        assert data["id"].startswith("chatcmpl-")
        assert "choices" in data
        assert len(data["choices"]) > 0
        assert data["choices"][0]["message"]["role"] == "assistant"
        assert len(data["choices"][0]["message"]["content"]) > 0
        assert data["choices"][0]["finish_reason"] == "stop"

        logger.info("✓ Non-streaming chat completions work (single message)")

        # Test 2: Multi-turn conversation (full message array)
        response = httpx.post(
            f"{url}/v1/chat/completions",
            json={
                "model": "test-agent",
                "messages": [
                    {"role": "user", "content": "My name is Alice"},
                    {"role": "assistant", "content": "Hello Alice!"},
                    {"role": "user", "content": "What is my name?"},
                ],
                "stream": False,
            },
            timeout=60.0,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["object"] == "chat.completion"
        assert len(data["choices"][0]["message"]["content"]) > 0

        logger.info("✓ Non-streaming chat completions work (multi-turn)")

    def test_chat_completions_streaming(self, single_agent_server):
        """Test OpenAI-compatible chat completions (streaming)."""
        url = single_agent_server["url"]

        with httpx.stream(
            "POST",
            f"{url}/v1/chat/completions",
            json={
                "model": "test-agent",
                "messages": [{"role": "user", "content": "Count 1 2 3"}],
                "stream": True,
            },
            timeout=60.0,
        ) as response:
            assert response.status_code == 200
            assert "text/event-stream" in response.headers.get("content-type", "")

            chunks = []
            found_done = False

            for line in response.iter_lines():
                if line.startswith("data: "):
                    data_str = line[6:]
                    if data_str == "[DONE]":
                        found_done = True
                    else:
                        chunks.append(data_str)

            assert len(chunks) > 0
            assert found_done

        logger.info("✓ Streaming chat completions work")


class TestMultiAgentCluster:
    """Tests for multi-agent cluster functionality."""

    def test_all_agents_discovery(self, multi_agent_cluster):
        """Test all agents in cluster are discoverable."""
        for name, url in multi_agent_cluster["urls"].items():
            # Health
            health = httpx.get(f"{url}/health").json()
            assert health["status"] == "healthy"
            assert health["name"] == name

            # Agent card
            card = httpx.get(f"{url}/.well-known/agent").json()
            assert card["name"] == name
            assert "message_processing" in card["capabilities"]

        # Coordinator should have delegation capability
        coord_card = httpx.get(
            f"{multi_agent_cluster['urls']['coordinator']}/.well-known/agent"
        ).json()
        assert "task_delegation" in coord_card["capabilities"]

        logger.info("✓ All agents discoverable")

    def test_agents_process_independently_with_memory(self, multi_agent_cluster):
        """Test each agent processes tasks and records in memory."""
        for name, url in multi_agent_cluster["urls"].items():
            # Send unique task
            task_id = f"TASK_{name}_{int(time.time())}"

            resp = httpx.post(
                f"{url}/v1/chat/completions",
                json={
                    "model": name,
                    "messages": [{"role": "user", "content": f"Process task {task_id}. Be brief."}],
                    "stream": False,
                },
                timeout=60.0,
            )
            assert resp.status_code == 200
            assert resp.json()["object"] == "chat.completion"

            # Verify memory
            memory = httpx.get(f"{url}/memory/events").json()
            user_msgs = [e for e in memory["events"] if e["event_type"] == "user_message"]

            # Task should be in memory
            found = any(task_id in str(e["content"]) for e in user_msgs)
            assert found, f"Task not found in {name}'s memory"

        logger.info("✓ All agents process independently with memory")

    def test_delegation_via_agent_decision(self, multi_agent_cluster):
        """Test delegation happens when model decides to delegate.

        With the new design, delegation occurs when the model's response
        contains a ```delegate block, not via special roles.
        This test verifies basic invocation works - delegation testing
        is better done via DEBUG_MOCK_RESPONSES in E2E tests.
        """
        coord_url = multi_agent_cluster["urls"]["coordinator"]

        # Send a user message - the model may or may not delegate
        # We're testing the infrastructure works, not forcing delegation
        task_id = f"TASK_{int(time.time())}"
        response = httpx.post(
            f"{coord_url}/v1/chat/completions",
            json={
                "model": "coordinator",
                "messages": [
                    {
                        "role": "user",
                        "content": f"Please respond with task ID {task_id}. Be brief.",
                    }
                ],
            },
            timeout=60.0,
        )

        assert response.status_code == 200
        data = response.json()
        assert "choices" in data
        assert len(data["choices"][0]["message"]["content"]) > 0

        # Verify coordinator's memory has the interaction
        coord_memory = httpx.get(f"{coord_url}/memory/events").json()
        user_msgs = [e for e in coord_memory["events"] if e["event_type"] == "user_message"]
        assert any(task_id in str(e["content"]) for e in user_msgs)

        logger.info("✓ Agent processes messages correctly")

    def test_agents_independent_processing(self, multi_agent_cluster):
        """Test workers process independently with memory isolation."""
        w1_url = multi_agent_cluster["urls"]["worker-1"]
        w2_url = multi_agent_cluster["urls"]["worker-2"]

        task1_id = f"W1_{int(time.time())}"
        task2_id = f"W2_{int(time.time())}"

        # Chat completions to worker-1
        resp1 = httpx.post(
            f"{w1_url}/v1/chat/completions",
            json={
                "model": "worker-1",
                "messages": [{"role": "user", "content": f"Process task {task1_id}. Be brief."}],
                "stream": False,
            },
            timeout=60.0,
        )
        assert resp1.status_code == 200

        # Chat completions to worker-2
        resp2 = httpx.post(
            f"{w2_url}/v1/chat/completions",
            json={
                "model": "worker-2",
                "messages": [{"role": "user", "content": f"Process task {task2_id}. Be brief."}],
                "stream": False,
            },
            timeout=60.0,
        )
        assert resp2.status_code == 200

        # Verify each worker only has its task
        w1_memory = httpx.get(f"{w1_url}/memory/events").json()
        w2_memory = httpx.get(f"{w2_url}/memory/events").json()

        w1_content = " ".join(str(e["content"]) for e in w1_memory["events"])
        w2_content = " ".join(str(e["content"]) for e in w2_memory["events"])

        assert task1_id in w1_content
        assert task2_id not in w1_content  # Memory isolation
        assert task2_id in w2_content
        assert task1_id not in w2_content  # Memory isolation

        logger.info("✓ Workers process independently with memory isolation")

    @pytest.mark.asyncio
    async def test_remote_agent_discovery_and_invocation(self, multi_agent_cluster):
        """Test RemoteAgent can discover and invoke workers."""
        worker_url = multi_agent_cluster["urls"]["worker-1"]

        remote = RemoteAgent(name="worker-1", card_url=worker_url)

        # Init (discover)
        success = await remote._init()
        assert success
        assert remote.agent_card is not None
        assert remote.agent_card.name == "worker-1"
        assert "message_processing" in remote.agent_card.capabilities

        # process_message - now takes messages list with task-delegation role
        response = await remote.process_message(
            [{"role": "task-delegation", "content": "Say hello from remote. Be brief."}]
        )
        assert len(response) > 0

        await remote.close()

        logger.info("✓ RemoteAgent discovery and invocation work")


class TestErrorHandling:
    """Tests for error handling scenarios."""

    def test_missing_messages(self, single_agent_server):
        """Test missing messages returns error."""
        url = single_agent_server["url"]

        response = httpx.post(
            f"{url}/v1/chat/completions",
            json={"model": "test-agent", "stream": False},
            timeout=30.0,
        )

        assert response.status_code in [400, 422]
        logger.info("✓ Missing messages returns error")

    def test_empty_messages_returns_error(self, single_agent_server):
        """Test empty messages array returns error."""
        url = single_agent_server["url"]

        response = httpx.post(
            f"{url}/v1/chat/completions",
            json={"model": "test-agent", "messages": [], "stream": False},
            timeout=30.0,
        )

        assert response.status_code == 400
        logger.info("✓ Empty messages returns error")
