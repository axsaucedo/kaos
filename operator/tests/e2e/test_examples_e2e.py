"""E2E tests for documentation examples.

These tests execute the markdown examples using Jupytext.
The examples in docs/examples/ are designed to be executable
when run through Jupytext's notebook execution.

All test logic lives in the markdown files - NO duplication in Python.
"""

import subprocess
import sys
from pathlib import Path

import pytest


# Path to docs/examples relative to repo root
DOCS_EXAMPLES_PATH = Path(__file__).parent.parent.parent.parent / "docs" / "examples"


def run_jupytext(markdown_file: Path, timeout: int = 300) -> subprocess.CompletedProcess:
    """Execute a markdown file using Jupytext."""
    result = subprocess.run(
        [
            sys.executable, "-m", "jupytext",
            "--set-kernel", "python3",
            "--execute",
            str(markdown_file),
        ],
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=DOCS_EXAMPLES_PATH,
    )
    return result


class TestExamplesViaJupytext:
    """Tests that execute documentation examples using Jupytext.
    
    All example logic lives in the markdown files.
    These tests simply run the markdown through Jupytext and verify success.
    """

    def test_custom_mcp_server_example(self):
        """Execute the custom MCP server example.
        
        Tests: kaos mcp init, kaos mcp build, server customization
        """
        example_file = DOCS_EXAMPLES_PATH / "custom-mcp-server.md"
        assert example_file.exists(), f"Example file not found: {example_file}"
        
        result = run_jupytext(example_file, timeout=300)
        
        if result.returncode != 0:
            print(f"STDOUT:\n{result.stdout}")
            print(f"STDERR:\n{result.stderr}")
        
        assert result.returncode == 0, f"Example execution failed: {result.stderr}"

    def test_kaos_monkey_example(self):
        """Execute the KAOS Monkey example.
        
        Tests: Agent with MCP tools, mock responses, pod deletion
        """
        example_file = DOCS_EXAMPLES_PATH / "kaos-monkey.md"
        assert example_file.exists(), f"Example file not found: {example_file}"
        
        result = run_jupytext(example_file, timeout=300)
        
        if result.returncode != 0:
            print(f"STDOUT:\n{result.stdout}")
            print(f"STDERR:\n{result.stderr}")
        
        assert result.returncode == 0, f"Example execution failed: {result.stderr}"

    def test_multi_agent_telemetry_example(self):
        """Execute the Multi-Agent Telemetry example.
        
        Tests: Multi-agent delegation, coordinator pattern
        """
        example_file = DOCS_EXAMPLES_PATH / "multi-agent-telemetry.md"
        assert example_file.exists(), f"Example file not found: {example_file}"
        
        result = run_jupytext(example_file, timeout=300)
        
        if result.returncode != 0:
            print(f"STDOUT:\n{result.stdout}")
            print(f"STDERR:\n{result.stderr}")
        
        assert result.returncode == 0, f"Example execution failed: {result.stderr}"

    def test_unified_mcp_gateway_example(self):
        """Execute the Unified MCP Gateway (pctx-codemode) example.
        
        Tests: pctx-codemode aggregation, Code Mode, multi-server routing
        Note: Uses longer timeout (420s) due to multiple MCP servers + pctx-codemode gateway
        """
        example_file = DOCS_EXAMPLES_PATH / "unified-mcp-gateway.md"
        assert example_file.exists(), f"Example file not found: {example_file}"
        
        result = run_jupytext(example_file, timeout=420)
        
        if result.returncode != 0:
            print(f"STDOUT:\n{result.stdout}")
            print(f"STDERR:\n{result.stderr}")
        
        assert result.returncode == 0, f"Example execution failed: {result.stderr}"

    def test_fastmcp_codemode_example(self):
        """Execute the FastMCP Code Mode example.
        
        Tests: fastmcp-codemode runtime, CodeMode meta-tools, Python sandbox execution
        """
        example_file = DOCS_EXAMPLES_PATH / "fastmcp-codemode.md"
        assert example_file.exists(), f"Example file not found: {example_file}"
        
        result = run_jupytext(example_file, timeout=300)
        
        if result.returncode != 0:
            print(f"STDOUT:\n{result.stdout}")
            print(f"STDERR:\n{result.stderr}")
        
        assert result.returncode == 0, f"Example execution failed: {result.stderr}"

    def test_memory_example(self):
        """Execute the agent memory example.

        Tests: a memory-enabled Agent bound to a local MemoryStore, automatic
        persist-after-run and recall-before-run, and per-session window isolation
        verified by querying the memory service API directly.
        """
        example_file = DOCS_EXAMPLES_PATH / "memory.md"
        assert example_file.exists(), f"Example file not found: {example_file}"

        result = run_jupytext(example_file, timeout=420)

        if result.returncode != 0:
            print(f"STDOUT:\n{result.stdout}")
            print(f"STDERR:\n{result.stderr}")

        assert result.returncode == 0, f"Example execution failed: {result.stderr}"

    def test_authorization_example(self):
        """The authorization guide is conceptual and not notebook-executable."""
        example_file = DOCS_EXAMPLES_PATH / "authorization.md"
        assert example_file.exists(), f"Example file not found: {example_file}"
        pytest.skip("authorization.md is an architecture walkthrough, not an executable example")

    def test_custom_agent_example(self):
        """Execute the custom agent image example.
        
        Tests: Custom Pydantic AI agent with custom tools, Docker image build,
        container.image CRD override, tool discovery via agent card
        """
        example_file = DOCS_EXAMPLES_PATH / "custom-agent.md"
        assert example_file.exists(), f"Example file not found: {example_file}"
        
        result = run_jupytext(example_file, timeout=300)
        
        if result.returncode != 0:
            print(f"STDOUT:\n{result.stdout}")
            print(f"STDERR:\n{result.stderr}")
        
        assert result.returncode == 0, f"Example execution failed: {result.stderr}"

    def test_autonomous_agent_example(self):
        """Execute the autonomous agent example.
        
        Tests: Startup-activated autonomous execution, A2A sync/autonomous modes,
        kaos agent memory, kaos agent status, kaos agent a2a send/get
        """
        example_file = DOCS_EXAMPLES_PATH / "autonomous-agent.md"
        assert example_file.exists(), f"Example file not found: {example_file}"
        
        result = run_jupytext(example_file, timeout=300)
        
        if result.returncode != 0:
            print(f"STDOUT:\n{result.stdout}")
            print(f"STDERR:\n{result.stderr}")
        
        assert result.returncode == 0, f"Example execution failed: {result.stderr}"
