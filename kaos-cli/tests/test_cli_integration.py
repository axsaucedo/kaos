"""CLI integration tests using --dry-run to validate YAML generation."""

import yaml
import pytest
from typer.testing import CliRunner

from kaos_cli.main import app

runner = CliRunner()


# ─── Agent deploy dry-run ───────────────────────────────────────────────


class TestAgentDeployDryRun:
    def test_basic_agent(self):
        result = runner.invoke(
            app,
            [
                "agent",
                "deploy",
                "test-agent",
                "--modelapi",
                "my-api",
                "--model",
                "gpt-4o",
                "--dry-run",
            ],
        )
        assert result.exit_code == 0
        docs = list(yaml.safe_load_all(result.output))
        agent = docs[0]
        assert agent["kind"] == "Agent"
        assert agent["metadata"]["name"] == "test-agent"
        assert agent["spec"]["modelAPI"] == "my-api"
        assert agent["spec"]["model"] == "gpt-4o"

    def test_agent_with_mcp_and_subagents(self):
        result = runner.invoke(
            app,
            [
                "agent",
                "deploy",
                "coord",
                "--modelapi",
                "api",
                "--model",
                "m1",
                "--mcp",
                "echo-mcp",
                "--sub-agent",
                "worker-1",
                "--expose",
                "--dry-run",
            ],
        )
        assert result.exit_code == 0
        docs = list(yaml.safe_load_all(result.output))
        agent = docs[0]
        assert "echo-mcp" in agent["spec"]["mcpServers"]
        assert agent["spec"]["agentNetwork"]["expose"] is True
        assert "worker-1" in agent["spec"]["agentNetwork"]["access"]

    def test_agent_with_description_and_instructions(self):
        result = runner.invoke(
            app,
            [
                "agent",
                "deploy",
                "desc-agent",
                "--modelapi",
                "api",
                "--model",
                "m1",
                "--description",
                "Test agent",
                "--instructions",
                "Be helpful",
                "--dry-run",
            ],
        )
        assert result.exit_code == 0
        docs = list(yaml.safe_load_all(result.output))
        agent = docs[0]
        assert agent["spec"]["config"]["description"] == "Test agent"
        assert "Be helpful" in agent["spec"]["config"]["instructions"]

    def test_agent_with_mock_responses(self):
        result = runner.invoke(
            app,
            [
                "agent",
                "deploy",
                "mock-agent",
                "--modelapi",
                "api",
                "--model",
                "m1",
                "--mock-response",
                "Hello!",
                "--dry-run",
            ],
        )
        assert result.exit_code == 0
        docs = list(yaml.safe_load_all(result.output))
        agent = docs[0]
        env = agent["spec"]["container"]["env"]
        mock_env = next(e for e in env if e["name"] == "DEBUG_MOCK_RESPONSES")
        assert "Hello!" in mock_env["value"]

    def test_agent_with_otel_endpoint(self):
        result = runner.invoke(
            app,
            [
                "agent",
                "deploy",
                "otel-agent",
                "--modelapi",
                "api",
                "--model",
                "m1",
                "--otel-endpoint",
                "http://otel:4317",
                "--dry-run",
            ],
        )
        assert result.exit_code == 0
        docs = list(yaml.safe_load_all(result.output))
        agent = docs[0]
        assert agent["spec"]["config"]["telemetry"]["enabled"] is True
        assert agent["spec"]["config"]["telemetry"]["endpoint"] == "http://otel:4317"

    def test_agent_with_env_vars(self):
        result = runner.invoke(
            app,
            [
                "agent",
                "deploy",
                "env-agent",
                "--modelapi",
                "api",
                "--model",
                "m1",
                "--env",
                "LOG_LEVEL=DEBUG",
                "--dry-run",
            ],
        )
        assert result.exit_code == 0
        docs = list(yaml.safe_load_all(result.output))
        agent = docs[0]
        env = agent["spec"]["container"]["env"]
        log_env = next(e for e in env if e["name"] == "LOG_LEVEL")
        assert log_env["value"] == "DEBUG"


# ─── ModelAPI deploy dry-run ────────────────────────────────────────────


class TestModelAPIDeployDryRun:
    def test_proxy_mode_default(self):
        result = runner.invoke(
            app,
            ["modelapi", "deploy", "my-api", "--dry-run"],
        )
        assert result.exit_code == 0
        docs = list(yaml.safe_load_all(result.output))
        api = docs[0]
        assert api["kind"] == "ModelAPI"
        assert api["metadata"]["name"] == "my-api"
        assert api["spec"]["mode"] == "Proxy"
        assert "*" in api["spec"]["proxyConfig"]["models"]

    def test_proxy_mode_with_models(self):
        result = runner.invoke(
            app,
            [
                "modelapi",
                "deploy",
                "my-api",
                "--model",
                "gpt-4o",
                "--model",
                "gpt-3.5",
                "--dry-run",
            ],
        )
        assert result.exit_code == 0
        docs = list(yaml.safe_load_all(result.output))
        api = docs[0]
        assert "gpt-4o" in api["spec"]["proxyConfig"]["models"]
        assert "gpt-3.5" in api["spec"]["proxyConfig"]["models"]

    def test_hosted_mode(self):
        result = runner.invoke(
            app,
            [
                "modelapi",
                "deploy",
                "my-api",
                "--mode",
                "Hosted",
                "--model",
                "smollm2:135m",
                "--dry-run",
            ],
        )
        assert result.exit_code == 0
        docs = list(yaml.safe_load_all(result.output))
        api = docs[0]
        assert api["spec"]["mode"] == "Hosted"
        assert api["spec"]["hostedConfig"]["model"] == "smollm2:135m"

    def test_proxy_with_provider(self):
        result = runner.invoke(
            app,
            [
                "modelapi",
                "deploy",
                "my-api",
                "--provider",
                "nebius",
                "--base-url",
                "https://api.nebius.ai/v1",
                "--dry-run",
            ],
        )
        assert result.exit_code == 0
        docs = list(yaml.safe_load_all(result.output))
        api = docs[0]
        assert api["spec"]["proxyConfig"]["provider"] == "nebius"
        assert api["spec"]["proxyConfig"]["apiBase"] == "https://api.nebius.ai/v1"

    def test_proxy_with_api_secret(self):
        result = runner.invoke(
            app,
            [
                "modelapi",
                "deploy",
                "my-api",
                "--api-secret",
                "my-secret:api-key",
                "--dry-run",
            ],
        )
        assert result.exit_code == 0
        docs = list(yaml.safe_load_all(result.output))
        api = docs[0]
        secret_ref = api["spec"]["proxyConfig"]["apiKey"]["secretKeyRef"]
        assert secret_ref["name"] == "my-secret"
        assert secret_ref["key"] == "api-key"

    def test_hosted_mode_requires_model(self):
        result = runner.invoke(
            app,
            [
                "modelapi",
                "deploy",
                "my-api",
                "--mode",
                "Hosted",
                "--dry-run",
            ],
        )
        assert result.exit_code != 0


# ─── MCP deploy dry-run ─────────────────────────────────────────────────


class TestMCPDeployDryRun:
    def test_runtime_deploy(self):
        result = runner.invoke(
            app,
            [
                "mcp",
                "deploy",
                "echo-mcp",
                "--runtime",
                "python-string",
                "--params",
                'def echo(msg: str) -> str:\n    return msg',
                "--dry-run",
            ],
        )
        assert result.exit_code == 0
        docs = list(yaml.safe_load_all(result.output))
        mcp = docs[0]
        assert mcp["kind"] == "MCPServer"
        assert mcp["metadata"]["name"] == "echo-mcp"
        assert mcp["spec"]["runtime"] == "python-string"
        assert "def echo" in mcp["spec"]["params"]

    def test_custom_image_deploy(self):
        result = runner.invoke(
            app,
            [
                "mcp",
                "deploy",
                "my-mcp",
                "--image",
                "my-image:v1",
                "--dry-run",
            ],
        )
        assert result.exit_code == 0
        docs = list(yaml.safe_load_all(result.output))
        mcp = docs[0]
        assert mcp["kind"] == "MCPServer"
        assert mcp["spec"]["runtime"] == "custom"
        assert mcp["spec"]["container"]["image"] == "my-image:v1"

    def test_runtime_with_env_vars(self):
        result = runner.invoke(
            app,
            [
                "mcp",
                "deploy",
                "slack-mcp",
                "--runtime",
                "slack",
                "--env",
                "SLACK_TOKEN=xoxb-123",
                "--dry-run",
            ],
        )
        assert result.exit_code == 0
        docs = list(yaml.safe_load_all(result.output))
        mcp = docs[0]
        env = mcp["spec"]["container"]["env"]
        slack_env = next(e for e in env if e["name"] == "SLACK_TOKEN")
        assert slack_env["value"] == "xoxb-123"


# ─── Samples commands ───────────────────────────────────────────────────


class TestSamples:
    def test_list_samples(self):
        result = runner.invoke(app, ["samples", "list"])
        assert result.exit_code == 0
        assert "1-simple-echo-agent" in result.output
        assert "2-multi-agent-mcp" in result.output
        assert "3-hierarchical-agents" in result.output
        assert "4-dev-ollama-proxy-agent" in result.output
        assert "5-proxy-external-api" in result.output

    def test_deploy_sample_dry_run(self):
        result = runner.invoke(
            app, ["samples", "deploy", "1-simple-echo-agent", "--dry-run"]
        )
        assert result.exit_code == 0
        docs = list(yaml.safe_load_all(result.output))
        kinds = {d["kind"] for d in docs if d}
        assert "Namespace" in kinds
        assert "ModelAPI" in kinds
        assert "MCPServer" in kinds
        assert "Agent" in kinds

    def test_deploy_sample_with_namespace_override(self):
        result = runner.invoke(
            app,
            [
                "samples",
                "deploy",
                "1-simple-echo-agent",
                "--namespace",
                "custom-ns",
                "--dry-run",
            ],
        )
        assert result.exit_code == 0
        docs = list(yaml.safe_load_all(result.output))
        ns_doc = next(d for d in docs if d and d["kind"] == "Namespace")
        assert ns_doc["metadata"]["name"] == "custom-ns"
        agent = next(d for d in docs if d and d["kind"] == "Agent")
        assert agent["metadata"]["namespace"] == "custom-ns"

    def test_deploy_sample_with_model_override(self):
        result = runner.invoke(
            app,
            [
                "samples",
                "deploy",
                "1-simple-echo-agent",
                "--model",
                "llama3:8b",
                "--dry-run",
            ],
        )
        assert result.exit_code == 0
        docs = list(yaml.safe_load_all(result.output))
        modelapi = next(d for d in docs if d and d["kind"] == "ModelAPI")
        assert modelapi["spec"]["hostedConfig"]["model"] == "llama3:8b"

    def test_deploy_sample_with_api_secret_override(self):
        result = runner.invoke(
            app,
            [
                "samples",
                "deploy",
                "5-proxy-external-api",
                "--api-secret",
                "my-secret:my-key",
                "--dry-run",
            ],
        )
        assert result.exit_code == 0
        docs = list(yaml.safe_load_all(result.output))
        modelapi = next(d for d in docs if d and d["kind"] == "ModelAPI")
        secret_ref = modelapi["spec"]["proxyConfig"]["apiKey"]["valueFrom"][
            "secretKeyRef"
        ]
        assert secret_ref["name"] == "my-secret"
        assert secret_ref["key"] == "my-key"

    def test_deploy_nonexistent_sample(self):
        result = runner.invoke(
            app, ["samples", "deploy", "nonexistent", "--dry-run"]
        )
        assert result.exit_code != 0

    def test_deploy_hierarchical_dry_run(self):
        result = runner.invoke(
            app, ["samples", "deploy", "3-hierarchical-agents", "--dry-run"]
        )
        assert result.exit_code == 0
        docs = list(yaml.safe_load_all(result.output))
        agents = [d for d in docs if d and d["kind"] == "Agent"]
        assert len(agents) >= 4  # supervisor + 2 leads + workers

    def test_deploy_multi_agent_dry_run(self):
        result = runner.invoke(
            app, ["samples", "deploy", "2-multi-agent-mcp", "--dry-run"]
        )
        assert result.exit_code == 0
        docs = list(yaml.safe_load_all(result.output))
        agents = [d for d in docs if d and d["kind"] == "Agent"]
        assert len(agents) == 3  # coordinator + 2 workers


# ─── Monitoring validation ──────────────────────────────────────────────


class TestMonitoringValidation:
    def test_ui_invalid_monitoring_backend(self):
        result = runner.invoke(
            app, ["ui", "--monitoring-enabled", "invalid-backend", "--no-browser"]
        )
        assert result.exit_code != 0
        assert "Invalid monitoring backend" in result.output


# ─── Version command ────────────────────────────────────────────────────


class TestVersion:
    def test_version_output(self):
        result = runner.invoke(app, ["version"])
        assert result.exit_code == 0
        assert "kaos-cli" in result.output
