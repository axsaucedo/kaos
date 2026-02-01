"""E2E tests for documentation examples.

These tests execute the markdown examples using Jupytext.
The examples in docs/examples/ are designed to be executable
when run through Jupytext's notebook execution.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest


# Path to docs/examples relative to repo root
DOCS_EXAMPLES_PATH = Path(__file__).parent.parent.parent.parent / "docs" / "examples"


def run_jupytext(markdown_file: Path, timeout: int = 300) -> subprocess.CompletedProcess:
    """Execute a markdown file using Jupytext.
    
    Args:
        markdown_file: Path to the markdown file to execute
        timeout: Timeout in seconds for execution
        
    Returns:
        CompletedProcess with returncode, stdout, stderr
    """
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
    """Tests that execute documentation examples using Jupytext."""

    def test_custom_mcp_server_example(self):
        """Execute the custom MCP server example.
        
        This example tests:
        - kaos mcp init
        - kaos mcp build
        - Server customization with %%writefile
        """
        example_file = DOCS_EXAMPLES_PATH / "custom-mcp-server.md"
        assert example_file.exists(), f"Example file not found: {example_file}"
        
        result = run_jupytext(example_file, timeout=300)
        
        # Print output for debugging
        if result.returncode != 0:
            print(f"STDOUT:\n{result.stdout}")
            print(f"STDERR:\n{result.stderr}")
        
        assert result.returncode == 0, f"Example execution failed: {result.stderr}"

    @pytest.mark.skip(reason="Requires KIND cluster with KAOS installed for full execution")
    def test_kaos_monkey_example(self):
        """Execute the KAOS Monkey example.
        
        This example tests:
        - Agent with mock responses
        - Agent with Kubernetes MCP server
        
        Note: Full execution requires a running cluster, so this is skipped
        in CI. The example is structured so that documentation-only sections
        use 'console' blocks which are not executed.
        """
        example_file = DOCS_EXAMPLES_PATH / "kaos-monkey.md"
        assert example_file.exists(), f"Example file not found: {example_file}"
        
        result = run_jupytext(example_file, timeout=300)
        
        if result.returncode != 0:
            print(f"STDOUT:\n{result.stdout}")
            print(f"STDERR:\n{result.stderr}")
        
        assert result.returncode == 0, f"Example execution failed: {result.stderr}"

    @pytest.mark.skip(reason="Requires KIND cluster with KAOS installed for full execution")
    def test_multi_agent_telemetry_example(self):
        """Execute the multi-agent telemetry example.
        
        This example tests:
        - Multi-agent setup
        - Telemetry configuration
        - Mock responses for deterministic testing
        
        Note: Full execution requires a running cluster, so this is skipped
        in CI. The example is structured so that documentation-only sections
        use 'console' blocks which are not executed.
        """
        example_file = DOCS_EXAMPLES_PATH / "multi-agent-telemetry.md"
        assert example_file.exists(), f"Example file not found: {example_file}"
        
        result = run_jupytext(example_file, timeout=300)
        
        if result.returncode != 0:
            print(f"STDOUT:\n{result.stdout}")
            print(f"STDERR:\n{result.stderr}")
        
        assert result.returncode == 0, f"Example execution failed: {result.stderr}"
