"""Fixtures for the harness contract suite.

Every test runs against ``tests/mock_modelapi.py`` with a fake credential, so the
suite needs no real model endpoint and no network. What it *does* need is the
harness binary itself; when that is absent the suite skips rather than fails,
matching how ``pydantic-ai-server/tests`` skips when Ollama is missing.
"""

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

HERE = Path(__file__).parent
MOCK = HERE / "mock_modelapi.py"

MOCK_PORT = int(os.environ.get("HARNESS_TEST_MOCK_PORT", "8089"))
DRIVER_PORT = int(os.environ.get("HARNESS_TEST_DRIVER_PORT", "8088"))
BASE_URL = f"http://127.0.0.1:{DRIVER_PORT}"
MOCK_URL = f"http://127.0.0.1:{MOCK_PORT}"


def harness_binary() -> str:
    """Resolve the harness executable, honouring the HARNESS_BIN override.

    ``pi`` is an npm package, so a checkout will not have it; local verification
    points HARNESS_BIN at a node_modules install.
    """
    override = os.environ.get("HARNESS_BIN", "")
    if override:
        return override if os.access(override, os.X_OK) else ""
    resolved = shutil.which(os.environ.get("HARNESS_DRIVER", "pi"))
    return resolved or ""


@pytest.fixture(scope="session")
def mock_modelapi():
    """Scripted OpenAI/Anthropic-compatible endpoint standing in for a ModelAPI."""
    proc = subprocess.Popen(
        [sys.executable, str(MOCK), str(MOCK_PORT)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    for _ in range(60):
        try:
            if httpx.get(f"{MOCK_URL}/v1/models", timeout=1).status_code == 200:
                break
        except Exception:
            time.sleep(0.25)
    else:
        proc.kill()
        pytest.fail("mock ModelAPI did not start")
    yield MOCK_URL
    proc.kill()


@pytest.fixture(scope="session")
def driver(mock_modelapi, tmp_path_factory):
    """The driver, serving the KAOS agent contract in front of a real harness."""
    binary = harness_binary()
    if not binary:
        pytest.skip("harness binary not available (set HARNESS_BIN)")

    state = tmp_path_factory.mktemp("state")
    workspace = tmp_path_factory.mktemp("workspace")
    env = {
        **os.environ,
        "AGENT_NAME": "coder",
        "AGENT_DESCRIPTION": "harness runtime under test",
        "MODEL_API_URL": mock_modelapi,
        "MODEL_NAME": "mock-model",
        "HARNESS_DRIVER": os.environ.get("HARNESS_DRIVER", "pi"),
        "HARNESS_WORKSPACE": str(workspace),
        "HARNESS_STATE_DIR": str(state),
        "HARNESS_BIN": binary,
        "AGENT_PORT": str(DRIVER_PORT),
    }
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "kaos_harness.driver:get_app",
            "--factory",
            "--host",
            "127.0.0.1",
            "--port",
            str(DRIVER_PORT),
            "--log-level",
            "warning",
        ],
        cwd=str(HERE.parent),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    for _ in range(80):
        try:
            if httpx.get(f"{BASE_URL}/health", timeout=1).status_code == 200:
                break
        except Exception:
            time.sleep(0.25)
    else:
        proc.kill()
        pytest.fail("driver did not start")

    yield BASE_URL
    proc.kill()


@pytest.fixture
def script(mock_modelapi):
    """Queue the model turns the harness will consume, in order."""

    def _script(responses):
        httpx.post(f"{mock_modelapi}/_script", json={"responses": responses}, timeout=5)

    return _script
