"""CLI integration tests using --dry-run to validate YAML generation."""

import re
import yaml
import pytest
from typer.testing import CliRunner

from kaos_cli.main import app


def strip_ansi(text: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


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

    def test_agent_with_image(self):
        result = runner.invoke(
            app,
            [
                "agent",
                "deploy",
                "custom-agent",
                "--modelapi",
                "api",
                "--model",
                "gpt-4o",
                "--image",
                "my-agent:latest",
                "--dry-run",
            ],
        )
        assert result.exit_code == 0
        docs = list(yaml.safe_load_all(result.output))
        agent = docs[0]
        assert agent["spec"]["container"]["image"] == "my-agent:latest"

    def test_agent_with_image_and_env(self):
        result = runner.invoke(
            app,
            [
                "agent",
                "deploy",
                "custom-agent",
                "--modelapi",
                "api",
                "--model",
                "gpt-4o",
                "--image",
                "my-agent:v2",
                "--env",
                "LOG_LEVEL=DEBUG",
                "--dry-run",
            ],
        )
        assert result.exit_code == 0
        docs = list(yaml.safe_load_all(result.output))
        agent = docs[0]
        assert agent["spec"]["container"]["image"] == "my-agent:v2"
        env = agent["spec"]["container"]["env"]
        log_env = next(e for e in env if e["name"] == "LOG_LEVEL")
        assert log_env["value"] == "DEBUG"

    def test_agent_with_image_and_subagents(self):
        result = runner.invoke(
            app,
            [
                "agent",
                "deploy",
                "coord",
                "--modelapi",
                "api",
                "--model",
                "gpt-4o",
                "--image",
                "coord:latest",
                "--sub-agent",
                "worker",
                "--expose",
                "--dry-run",
            ],
        )
        assert result.exit_code == 0
        docs = list(yaml.safe_load_all(result.output))
        agent = docs[0]
        assert agent["spec"]["container"]["image"] == "coord:latest"
        assert agent["spec"]["agentNetwork"]["expose"] is True
        assert "worker" in agent["spec"]["agentNetwork"]["access"]

    def test_build_requires_image(self):
        result = runner.invoke(
            app,
            [
                "agent",
                "deploy",
                "test",
                "--modelapi",
                "api",
                "--model",
                "m1",
                "--build",
                "--dry-run",
            ],
        )
        assert result.exit_code != 0


# ─── Agent deploy autonomous flags ─────────────────────────────────────


class TestAgentDeployAutonomous:
    def test_autonomous_basic(self):
        result = runner.invoke(
            app,
            [
                "agent",
                "deploy",
                "auto-agent",
                "--modelapi",
                "api",
                "--model",
                "m1",
                "--autonomous",
                "Monitor system health",
                "--dry-run",
            ],
        )
        assert result.exit_code == 0
        docs = list(yaml.safe_load_all(result.output))
        agent = docs[0]
        auto = agent["spec"]["config"]["autonomous"]
        assert "enabled" not in auto
        assert auto["goal"] == "Monitor system health"

    def test_autonomous_with_budgets(self):
        result = runner.invoke(
            app,
            [
                "agent",
                "deploy",
                "auto-agent",
                "--modelapi",
                "api",
                "--model",
                "m1",
                "--autonomous",
                "Check health",
                "--auto-max-iter-runtime",
                "120",
                "--auto-interval",
                "5.0",
                "--task-max-iterations",
                "20",
                "--task-max-runtime",
                "600",
                "--task-max-tool-calls",
                "100",
                "--dry-run",
            ],
        )
        assert result.exit_code == 0
        docs = list(yaml.safe_load_all(result.output))
        agent = docs[0]
        auto = agent["spec"]["config"]["autonomous"]
        assert "enabled" not in auto
        assert auto["goal"] == "Check health"
        assert auto["maxIterRuntimeSeconds"] == 120
        assert auto["intervalSeconds"] == 5.0
        tc = agent["spec"]["config"]["taskConfig"]
        assert tc["maxIterations"] == 20
        assert tc["maxRuntimeSeconds"] == 600
        assert tc["maxToolCalls"] == 100

    def test_autonomous_with_task_budgets_only(self):
        result = runner.invoke(
            app,
            [
                "agent",
                "deploy",
                "auto-agent",
                "--modelapi",
                "api",
                "--model",
                "m1",
                "--task-max-iterations",
                "0",
                "--dry-run",
            ],
        )
        assert result.exit_code == 0
        docs = list(yaml.safe_load_all(result.output))
        agent = docs[0]
        tc = agent["spec"]["config"]["taskConfig"]
        assert tc["maxIterations"] == 0

    def test_autonomous_with_other_config(self):
        result = runner.invoke(
            app,
            [
                "agent",
                "deploy",
                "auto-agent",
                "--modelapi",
                "api",
                "--model",
                "m1",
                "--description",
                "Auto agent",
                "--autonomous",
                "Do work",
                "--mcp",
                "echo-mcp",
                "--dry-run",
            ],
        )
        assert result.exit_code == 0
        docs = list(yaml.safe_load_all(result.output))
        agent = docs[0]
        assert agent["spec"]["config"]["description"] == "Auto agent"
        assert agent["spec"]["config"]["autonomous"]["goal"] == "Do work"
        assert "echo-mcp" in agent["spec"]["mcpServers"]

    def test_no_autonomous_no_config_section(self):
        result = runner.invoke(
            app,
            [
                "agent",
                "deploy",
                "basic-agent",
                "--modelapi",
                "api",
                "--model",
                "m1",
                "--dry-run",
            ],
        )
        assert result.exit_code == 0
        docs = list(yaml.safe_load_all(result.output))
        agent = docs[0]
        assert "config" not in agent["spec"]


# ─── Agent A2A commands ────────────────────────────────────────────────


class TestAgentA2ACommands:
    def test_a2a_help(self):
        result = runner.invoke(app, ["agent", "a2a", "--help"])
        assert result.exit_code == 0
        assert "send" in result.output
        assert "get" in result.output
        assert "cancel" in result.output

    def test_a2a_send_help(self):
        result = runner.invoke(app, ["agent", "a2a", "send", "--help"])
        assert result.exit_code == 0
        output = strip_ansi(result.output)
        assert "--message" in output
        assert "--async" in output
        assert "--session-id" in output
        assert "--json" in output

    def test_a2a_get_help(self):
        result = runner.invoke(app, ["agent", "a2a", "get", "--help"])
        assert result.exit_code == 0
        output = strip_ansi(result.output)
        assert "--task-id" in output
        assert "--json" in output

    def test_a2a_cancel_help(self):
        result = runner.invoke(app, ["agent", "a2a", "cancel", "--help"])
        assert result.exit_code == 0
        output = strip_ansi(result.output)
        assert "--task-id" in output
        assert "--json" in output


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
        secret_ref = api["spec"]["proxyConfig"]["apiKey"]["valueFrom"]["secretKeyRef"]
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
                "def echo(msg: str) -> str:\n    return msg",
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

    def test_deploy_memory_sample_dry_run(self):
        result = runner.invoke(
            app, ["samples", "deploy", "7-memory-agent", "--dry-run"]
        )
        assert result.exit_code == 0
        docs = [d for d in yaml.safe_load_all(result.output) if d]
        kinds = {d["kind"] for d in docs}
        assert "ModelAPI" in kinds
        assert "MemoryStore" in kinds
        assert "Agent" in kinds
        store = next(d for d in docs if d["kind"] == "MemoryStore")
        assert store["spec"]["storage"]["type"] == "local"
        agent = next(d for d in docs if d["kind"] == "Agent")
        assert agent["spec"]["config"]["memory"]["memoryStore"] == "shared-memory"
        assert agent["spec"]["config"]["memory"]["scope"] == "user"
        result = runner.invoke(
            app, ["samples", "deploy", "1-simple-echo-agent", "--dry-run"]
        )
        assert result.exit_code == 0
        docs = list(yaml.safe_load_all(result.output))
        kinds = {d["kind"] for d in docs if d}
        assert "Namespace" not in kinds
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
        # No Namespace doc should be present
        ns_docs = [d for d in docs if d and d["kind"] == "Namespace"]
        assert len(ns_docs) == 0
        # All resources get the namespace override
        for doc in docs:
            if doc:
                assert doc["metadata"]["namespace"] == "custom-ns"

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

    def test_deploy_sample_with_provider_override(self):
        result = runner.invoke(
            app,
            [
                "samples",
                "deploy",
                "5-proxy-external-api",
                "--provider",
                "openai",
                "--dry-run",
            ],
        )
        assert result.exit_code == 0
        docs = list(yaml.safe_load_all(result.output))
        modelapi = next(d for d in docs if d and d["kind"] == "ModelAPI")
        assert modelapi["spec"]["proxyConfig"]["provider"] == "openai"

    def test_deploy_sample_api_secret_without_value_dry_run(self):
        """--api-secret without value shows prompt note and uses placeholder in dry-run."""
        result = runner.invoke(
            app,
            [
                "samples",
                "deploy",
                "5-proxy-external-api",
                "--api-secret",
                "--dry-run",
            ],
        )
        assert result.exit_code == 0
        docs = list(yaml.safe_load_all(result.output))
        modelapi = next(d for d in docs if d and d["kind"] == "ModelAPI")
        secret_ref = modelapi["spec"]["proxyConfig"]["apiKey"]["valueFrom"][
            "secretKeyRef"
        ]
        assert secret_ref["name"] == "kaos-5-proxy-external-api-api-key"
        assert secret_ref["key"] == "api-key"

    def test_deploy_sample_api_secret_bare_name_dry_run(self):
        """--api-secret with bare name (no colon) should fail with format error."""
        result = runner.invoke(
            app,
            [
                "samples",
                "deploy",
                "5-proxy-external-api",
                "--api-secret",
                "my-custom-secret",
                "--dry-run",
            ],
        )
        assert result.exit_code != 0
        assert "Invalid --api-secret format" in result.output

    def test_deploy_nonexistent_sample(self):
        result = runner.invoke(app, ["samples", "deploy", "nonexistent", "--dry-run"])
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

    def test_namespace_override_applies_to_all_resources(self):
        """Verify namespace override applies to all resources (no Namespace doc)."""
        result = runner.invoke(
            app,
            [
                "samples",
                "deploy",
                "1-simple-echo-agent",
                "--namespace",
                "test-ns",
                "--dry-run",
            ],
        )
        assert result.exit_code == 0
        docs = list(yaml.safe_load_all(result.output))
        for doc in docs:
            if doc:
                assert (
                    doc["kind"] != "Namespace"
                ), "Namespace doc should be filtered out"
                assert (
                    doc["metadata"].get("namespace") == "test-ns"
                ), f"{doc['kind']} {doc['metadata']['name']} missing namespace override"

    def test_modelapi_override_skips_modelapi_resource(self):
        """When --modelapi is used, ModelAPI resources are filtered out."""
        result = runner.invoke(
            app,
            [
                "samples",
                "deploy",
                "1-simple-echo-agent",
                "--modelapi",
                "my-existing-api",
                "--dry-run",
            ],
        )
        assert result.exit_code == 0
        docs = list(yaml.safe_load_all(result.output))
        kinds = {d["kind"] for d in docs if d}
        assert "ModelAPI" not in kinds
        # Agent should reference the overridden modelapi
        agent = next(d for d in docs if d and d["kind"] == "Agent")
        assert agent["spec"]["modelAPI"] == "my-existing-api"

    def test_no_namespace_resource_in_output(self):
        """Namespace resources are always filtered out from samples."""
        result = runner.invoke(
            app, ["samples", "deploy", "1-simple-echo-agent", "--dry-run"]
        )
        assert result.exit_code == 0
        docs = list(yaml.safe_load_all(result.output))
        for doc in docs:
            if doc:
                assert doc["kind"] != "Namespace"


# ─── Package data bundling ──────────────────────────────────────────────


class TestPackageData:
    def test_samples_dir_resolves(self):
        from kaos_cli.samples import SAMPLES_DIR

        assert SAMPLES_DIR.exists(), f"SAMPLES_DIR not found: {SAMPLES_DIR}"

    def test_samples_dir_contains_files(self):
        from kaos_cli.samples import _get_sample_files

        files = _get_sample_files()
        assert len(files) == 8
        names = [f.stem for f in files]
        assert "1-simple-echo-agent" in names
        assert "5-proxy-external-api" in names
        assert "7-memory-agent" in names
        assert "8-access-grant" in names


# ─── Monitoring validation ──────────────────────────────────────────────


class TestMonitoringValidation:
    def test_ui_invalid_monitoring_backend(self):
        result = runner.invoke(
            app, ["ui", "--monitoring-enabled", "invalid-backend", "--no-browser"]
        )
        assert result.exit_code != 0
        assert "Invalid monitoring backend" in result.output

    def test_ui_monitoring_enabled_without_value_defaults_signoz(self):
        """--monitoring-enabled without value defaults to signoz (no invalid backend error)."""
        from unittest.mock import patch

        with patch("kaos_cli.ui.check_monitoring_service", return_value=False):
            result = runner.invoke(app, ["ui", "--monitoring-enabled", "--no-browser"])
        # Should not error on invalid backend; fails on service not found instead
        assert "Invalid monitoring backend" not in result.output
        assert "signoz" in result.output.lower()


# ─── System install flags ───────────────────────────────────────────────


class TestSystemInstallFlags:
    def test_install_help_shows_gateway_flag(self):
        result = runner.invoke(
            app, ["system", "install", "--help"], env={"COLUMNS": "200"}
        )
        assert result.exit_code == 0
        output = strip_ansi(result.output)
        assert "--gateway-enabled" in output
        assert "--metallb-enabled" in output
        assert "--pgvector-memory-enabled" in output

    def test_uninstall_help_shows_gateway_flag(self):
        result = runner.invoke(
            app, ["system", "uninstall", "--help"], env={"COLUMNS": "200"}
        )
        assert result.exit_code == 0
        output = strip_ansi(result.output)
        assert "--gateway-enabled" in output
        assert "--metallb-enabled" in output
        assert "--pgvector-memory-enabled" in output

    def test_install_help_shows_auth_flag(self):
        result = runner.invoke(app, ["system", "install", "--help"])
        assert result.exit_code == 0
        output = strip_ansi(result.output)
        assert "--agent-auth-enabled" in output
        assert "--user-auth-enabled" in output
        assert "--auth-enabled" not in output
        # The fine-grained auth knobs are collapsed into the preset and no longer
        # exposed on the command surface.
        assert "--authz-provider" not in output
        # Advanced dev chart paths remain available but hidden from help.
        assert "--aib-chart-path" not in output


class TestPgvectorMemoryInstall:
    def test_dsn_format(self):
        from kaos_cli.install import _pgvector_dsn

        dsn = _pgvector_dsn("kaos-system")
        assert dsn.startswith("postgresql://")
        assert "kaos-memory-pgvector.kaos-system.svc.cluster.local:5432" in dsn
        assert dsn.endswith("/kaos")

    def test_manifest_contract(self):
        from kaos_cli.install import (
            _pgvector_manifest,
            PGVECTOR_IMAGE,
            PGVECTOR_SECRET_NAME,
            PGVECTOR_SECRET_KEY,
        )

        manifest = _pgvector_manifest("kaos-system")
        assert f"name: {PGVECTOR_SECRET_NAME}" in manifest
        assert f"{PGVECTOR_SECRET_KEY}: postgresql://" in manifest
        assert f"image: {PGVECTOR_IMAGE}" in manifest
        assert "kind: Deployment" in manifest
        assert "kind: Service" in manifest

    def test_install_applies_manifest(self):
        from unittest.mock import patch, MagicMock
        from kaos_cli import install as install_mod

        applied = {}

        def fake_kubectl(args, check=False, input=None):
            result = MagicMock()
            result.returncode = 0
            result.stderr = ""
            if args[:2] == ["apply", "-f"]:
                applied["input"] = input
            return result

        with patch.object(install_mod, "_run_kubectl", side_effect=fake_kubectl):
            assert install_mod._install_pgvector("kaos-system") is True
        assert "kind: Secret" in applied["input"]
        assert "image: pgvector/pgvector" in applied["input"]


def test_token_exchange_gateway_install_enables_backend_api():
    from types import SimpleNamespace
    from unittest.mock import patch

    from kaos_cli.install import _install_gateway_api

    calls = []

    def fake_helm(args, check=False):
        calls.append(args)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    with patch("kaos_cli.install.run_helm_command", side_effect=fake_helm):
        assert _install_gateway_api(enable_backend=True)

    install_args = calls[-1]
    assert "config.envoyGateway.extensionApis.enableBackend=true" in install_args


class TestAuthWiring:
    @pytest.fixture(autouse=True)
    def _stub_gateway_install(self):
        """Stub the gateway install/wait helpers so preset-driven installs.

        Tests here assert on operator wiring, not gateway bootstrap, so
        short-circuit it when a case enables the gateway explicitly.
        """
        from unittest.mock import patch

        with patch("kaos_cli.install._install_gateway_api", return_value=True), patch(
            "kaos_cli.install._wait_for_gateway_class", return_value=True
        ):
            yield

    def test_build_auth_operator_args(self):
        from kaos_cli.install import _build_auth_operator_args

        args = _build_auth_operator_args(
            "aib-access-check-grpc.aib-system:9191",
            "http://aib.aib-system:8000",
            "kaos-aib",
        )
        joined = " ".join(args)
        assert (
            "security.agentAuth.extAuthzUrl=aib-access-check-grpc.aib-system:9191"
            in joined
        )
        assert "security.agentAuth.identity.provider=aib" in joined
        assert "security.agentAuth.issuer=http://aib.aib-system:8000" in joined
        assert "security.agentAuth.credentialSecretPrefix=kaos-aib" in joined
        # Each value is preceded by a --set flag.
        assert args.count("--set") == 4

    def test_install_uses_one_aib_issuer_for_broker_and_operator(self):
        from types import SimpleNamespace
        from unittest.mock import patch

        from kaos_cli.install import install_command

        issuer = "https://agents.example.test"
        captured = {}

        def fake_install_aib(*args, **kwargs):
            captured["broker"] = kwargs["extra_set"]
            return True

        def fake_helm(args, check=True, **kwargs):
            captured["operator"] = args
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        with patch("kaos_cli.install.check_helm_installed", return_value=True), patch(
            "kaos_cli.install._install_aib", side_effect=fake_install_aib
        ), patch("kaos_cli.install.run_helm_command", side_effect=fake_helm):
            install_command(
                namespace="kaos-system",
                release_name="kaos",
                version=None,
                set_values=[],
                wait=False,
                chart_path="operator/chart",
                auth_enabled=True,
                auth_issuer=issuer,
                aib_chart_path="aib/chart",
                user_auth=False,
            )

        assert captured["broker"] == [
            "--set",
            f"broker.server.enduser.publicUrl={issuer}",
        ]
        operator = " ".join(captured["operator"])
        assert f"security.agentAuth.issuer={issuer}" in operator
        assert "security.agentAuth.identity.provider=aib" in operator

    def test_default_endpoints_use_auth_namespace(self):
        from kaos_cli.install import (
            _default_auth_issuer,
            _default_auth_admin_url,
        )

        assert "custom-ns" in _default_auth_issuer("custom-ns", "aib")
        assert _default_auth_admin_url("custom-ns", "aib").endswith("/api")
        assert "aib-agentic-identity-broker.custom-ns" in _default_auth_admin_url(
            "custom-ns", "aib"
        )

    def test_auth_enabled_wires_operator_security_values(self):
        """--auth-enabled adds the security.agentAuth.* helm --set args."""
        from unittest.mock import patch

        captured = {}

        def fake_helm(args, check=True, **kwargs):
            from types import SimpleNamespace

            # Capture the operator upgrade invocation.
            if "upgrade" in args and any(
                "kaos-operator" in a or a.endswith("/chart") for a in args
            ):
                captured["args"] = args
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        with patch("kaos_cli.install.check_helm_installed", return_value=True), patch(
            "kaos_cli.install.run_helm_command", side_effect=fake_helm
        ), patch("kaos_cli.install._run_kubectl") as mock_kubectl:
            from types import SimpleNamespace

            mock_kubectl.return_value = SimpleNamespace(
                returncode=0, stdout="", stderr=""
            )
            result = runner.invoke(
                app,
                [
                    "system",
                    "install",
                    "--agent-auth-enabled",
                    "aib",
                    "--user-auth-enabled",
                    "keycloak",
                    "--chart-path",
                    "operator/chart",
                ],
            )

        assert result.exit_code == 0, result.output
        joined = " ".join(captured.get("args", []))
        assert "security.agentAuth.extAuthzUrl=" not in joined
        assert "security.agentAuth.credentialSecretPrefix=kaos-aib" in joined
        assert "security.agentAuth.adminUrl=" in joined

    def test_build_auth_operator_args_includes_admin_url(self):
        from kaos_cli.install import _build_auth_operator_args

        args = _build_auth_operator_args(
            "aib-access-check-grpc.aib-system:9191",
            "http://aib.aib-system:8000",
            "kaos-aib",
            admin_url="http://aib.aib-system:8000/api",
        )
        joined = " ".join(args)
        assert "security.agentAuth.adminUrl=http://aib.aib-system:8000/api" in joined

    def test_build_auth_operator_args_omits_admin_url_when_unset(self):
        from kaos_cli.install import _build_auth_operator_args

        args = _build_auth_operator_args(
            "aib-access-check-grpc.aib-system:9191",
            "http://aib.aib-system:8000",
            "kaos-aib",
        )
        assert "security.agentAuth.adminUrl" not in " ".join(args)

    def test_build_auth_operator_args_includes_user_auth(self):
        from kaos_cli.install import _build_auth_operator_args

        args = _build_auth_operator_args(
            "aib-access-check-grpc.aib-system:9191",
            "http://aib.aib-system:8000",
            "kaos-aib",
            user_issuer="http://keycloak.keycloak:8080/realms/kaos",
            user_audience="kaos",
            user_jwks_uri="http://keycloak.keycloak:8080/custom/certs",
        )
        joined = " ".join(args)
        assert (
            "security.userAuth.issuer=http://keycloak.keycloak:8080/realms/kaos"
            in joined
        )
        assert "security.userAuth.audience=kaos" in joined
        assert (
            "security.userAuth.jwksUri=http://keycloak.keycloak:8080/custom/certs"
            in joined
        )

    def test_build_auth_operator_args_omits_user_auth_when_unset(self):
        from kaos_cli.install import _build_auth_operator_args

        args = _build_auth_operator_args(
            "aib-access-check-grpc.aib-system:9191",
            "http://aib.aib-system:8000",
            "kaos-aib",
        )
        joined = " ".join(args)
        assert "security.userAuth" not in joined

    def test_build_auth_operator_args_kaos_authorization(self):
        from kaos_cli.install import _build_auth_operator_args

        args = _build_auth_operator_args(
            "aib-access-check-grpc.aib-system:9191",
            "http://aib.aib-system:8000",
            "kaos-aib",
            policy_data_source="automated",
            policy_configmap_name="kaos-authz-policy",
            policy_configmap_namespace="aib-system",
        )
        joined = " ".join(args)
        assert "security.agentAuth.authorization.policyDataSource=automated" in joined
        assert (
            "security.agentAuth.projection.policyConfigMap.name=kaos-authz-policy"
            in joined
        )
        assert (
            "security.agentAuth.projection.policyConfigMap.namespace=aib-system"
            in joined
        )

    def test_build_auth_operator_args_rego_override(self):
        from kaos_cli.install import _build_auth_operator_args

        args = _build_auth_operator_args(
            "aib-access-check-grpc.aib-system:9191",
            "http://aib.aib-system:8000",
            "kaos-aib",
            policy_data_source="manual",
            policy_rego_override=True,
        )
        joined = " ".join(args)
        assert "security.agentAuth.authorization.policyRegoOverride=true" in joined
        assert "security.agentAuth.authorization.policyDataSource=manual" in joined

    def test_build_auth_operator_args_broker_identity(self):
        from kaos_cli.install import _build_auth_operator_args

        args = _build_auth_operator_args(
            "aib-access-check-grpc.aib-system:9191",
            "http://aib.aib-system:8000",
            "kaos-aib",
            admin_url="http://aib.aib-system:8000/api",
        )
        joined = " ".join(args)
        assert "security.agentAuth.adminUrl=http://aib.aib-system:8000/api" in joined

    def test_build_auth_operator_args_omits_authorization_when_unset(self):
        from kaos_cli.install import _build_auth_operator_args

        args = _build_auth_operator_args(
            "aib-access-check-grpc.aib-system:9191",
            "http://aib.aib-system:8000",
            "kaos-aib",
        )
        joined = " ".join(args)
        assert "security.agentAuth.authorization" not in joined
        assert "security.agentAuth.projection.policyConfigMap" not in joined

    def test_build_auth_operator_args_network_policy_default_on(self):
        from kaos_cli.install import _build_auth_operator_args

        args = _build_auth_operator_args(
            "aib-access-check-grpc.aib-system:9191",
            "http://aib.aib-system:8000",
            "kaos-aib",
        )
        # NetworkPolicy is enabled by default in the chart, so no override is emitted.
        assert "security.networkPolicy.enabled=false" not in " ".join(args)

    def test_build_auth_operator_args_disable_network_policy(self):
        from kaos_cli.install import _build_auth_operator_args

        args = _build_auth_operator_args(
            "aib-access-check-grpc.aib-system:9191",
            "http://aib.aib-system:8000",
            "kaos-aib",
            network_policy=False,
        )
        assert "security.networkPolicy.enabled=false" in " ".join(args)

    def test_build_auth_operator_args_enable_network_policy_egress(self):
        from kaos_cli.install import _build_auth_operator_args

        args = _build_auth_operator_args(
            "aib-access-check-grpc.aib-system:9191",
            "http://aib.aib-system:8000",
            "kaos-aib",
            network_policy_egress=True,
        )
        assert "security.networkPolicy.egress.enabled=true" in " ".join(args)

    def test_build_auth_operator_args_omits_network_policy_egress_by_default(self):
        from kaos_cli.install import _build_auth_operator_args

        args = _build_auth_operator_args(
            "aib-access-check-grpc.aib-system:9191",
            "http://aib.aib-system:8000",
            "kaos-aib",
        )
        assert "security.networkPolicy.egress.enabled=true" not in " ".join(args)

    def test_build_auth_operator_args_gateway_routing_and_host(self):
        from kaos_cli.install import _build_auth_operator_args

        args = _build_auth_operator_args(
            "aib-access-check-grpc.aib-system:9191",
            "http://aib.aib-system:8000",
            "kaos-aib",
            gateway_routing=True,
            gateway_host="172.18.0.200",
        )
        joined = " ".join(args)
        assert "security.gatewayRouting.enabled=true" in joined
        assert "security.gatewayHost=172.18.0.200" in joined

    def test_build_auth_operator_args_omits_routing_when_default(self):
        from kaos_cli.install import _build_auth_operator_args

        args = _build_auth_operator_args(
            "aib-access-check-grpc.aib-system:9191",
            "http://aib.aib-system:8000",
            "kaos-aib",
        )
        joined = " ".join(args)
        assert "security.gatewayRouting.enabled=true" not in joined
        assert "security.gatewayHost=" not in joined

    def test_build_auth_operator_args_gateway_api_strict(self):
        from kaos_cli.install import _build_auth_operator_args

        args = _build_auth_operator_args(
            "aib-access-check-grpc.aib-system:9191",
            "http://aib.aib-system:8000",
            "kaos-aib",
            gateway_api_strict=True,
        )
        joined = " ".join(args)
        assert "security.strictGatewayApi.enabled=true" in joined

    def test_build_auth_operator_args_omits_strict_when_default(self):
        from kaos_cli.install import _build_auth_operator_args

        args = _build_auth_operator_args(
            "aib-access-check-grpc.aib-system:9191",
            "http://aib.aib-system:8000",
            "kaos-aib",
        )
        assert "security.strictGatewayApi.enabled=true" not in " ".join(args)

    def test_build_auth_operator_args_tls_self_signed(self):
        from kaos_cli.install import _build_auth_operator_args

        args = _build_auth_operator_args(
            "aib-access-check-grpc.aib-system:9191",
            "http://aib.aib-system:8000",
            "kaos-aib",
            tls_mode="selfSigned",
        )
        joined = " ".join(args)
        assert "security.tls.mode=selfSigned" in joined
        assert "security.tls.certManager.issuerRef.name=" not in joined

    def test_build_auth_operator_args_tls_cert_manager(self):
        from kaos_cli.install import _build_auth_operator_args

        args = _build_auth_operator_args(
            "aib-access-check-grpc.aib-system:9191",
            "http://aib.aib-system:8000",
            "kaos-aib",
            tls_mode="certManager",
            tls_issuer_name="letsencrypt-prod",
            tls_issuer_kind="ClusterIssuer",
        )
        joined = " ".join(args)
        assert "security.tls.mode=certManager" in joined
        assert "security.tls.certManager.issuerRef.name=letsencrypt-prod" in joined
        assert "security.tls.certManager.issuerRef.kind=ClusterIssuer" in joined

    def test_build_auth_operator_args_tls_provided(self):
        from kaos_cli.install import _build_auth_operator_args

        args = _build_auth_operator_args(
            "aib-access-check-grpc.aib-system:9191",
            "http://aib.aib-system:8000",
            "kaos-aib",
            tls_mode="provided",
            tls_secret_name="my-gateway-tls",
        )
        joined = " ".join(args)
        assert "security.tls.mode=provided" in joined
        assert "security.tls.secretName=my-gateway-tls" in joined

    def test_build_auth_operator_args_omits_tls_when_unset(self):
        from kaos_cli.install import _build_auth_operator_args

        args = _build_auth_operator_args(
            "aib-access-check-grpc.aib-system:9191",
            "http://aib.aib-system:8000",
            "kaos-aib",
        )
        assert "security.tls.mode=" not in " ".join(args)

    def test_build_aib_broker_public_url_args(self):
        from kaos_cli.install import _build_aib_broker_public_url_args

        public_url = (
            "http://aib-agentic-identity-broker.aib-system.svc.cluster.local:8000"
        )
        args = _build_aib_broker_public_url_args(public_url)
        assert args == [
            "--set",
            f"broker.server.enduser.publicUrl={public_url}",
        ]

    def test_keycloak_realm_json_registers_kaos_client(self):
        from kaos_cli.install import _keycloak_realm_json

        realm = _keycloak_realm_json(
            "kaos", "kaos", "kaos-dev-secret", "kaos", "kaos-user", "kaos-password"
        )
        clients = {c["clientId"]: c for c in realm["clients"]}
        assert set(clients) == {"kaos"}
        assert clients["kaos"]["secret"] == "kaos-dev-secret"
        mappers = {
            mapper["name"]: mapper for mapper in clients["kaos"]["protocolMappers"]
        }
        assert set(mappers) == {
            "kaos-audience",
            "kaos-groups",
            "kaos-subject",
            "token-exchange-audience",
        }
        assert mappers["token-exchange-audience"] == {
            "name": "token-exchange-audience",
            "protocol": "openid-connect",
            "protocolMapper": "oidc-audience-mapper",
            "config": {
                "included.custom.audience": "token-exchange-broker",
                "id.token.claim": "false",
                "access.token.claim": "true",
            },
        }
        assert mappers["kaos-groups"] == {
            "name": "kaos-groups",
            "protocol": "openid-connect",
            "protocolMapper": "oidc-group-membership-mapper",
            "config": {
                "claim.name": "groups",
                "full.path": "false",
                "id.token.claim": "false",
                "access.token.claim": "true",
                "userinfo.token.claim": "false",
            },
        }
        assert mappers["kaos-subject"] == {
            "name": "kaos-subject",
            "protocol": "openid-connect",
            "protocolMapper": "oidc-usermodel-property-mapper",
            "config": {
                "user.attribute": "id",
                "claim.name": "sub",
                "jsonType.label": "String",
                "id.token.claim": "false",
                "access.token.claim": "true",
                "userinfo.token.claim": "false",
            },
        }
        assert realm["groups"] == [{"name": "researchers"}]
        assert realm["users"][0]["groups"] == ["researchers"]
        assert realm["defaultDefaultClientScopes"] == ["kaos-agent-audience"]
        assert realm["clientScopes"] == [
            {
                "name": "kaos-agent-audience",
                "protocol": "openid-connect",
                "attributes": {"include.in.token.scope": "false"},
                "protocolMappers": [
                    {
                        "name": "kaos-agent-audience",
                        "protocol": "openid-connect",
                        "protocolMapper": "oidc-audience-mapper",
                        "config": {
                            "included.custom.audience": "kaos-gateway",
                            "id.token.claim": "false",
                            "access.token.claim": "true",
                        },
                    }
                ],
            }
        ]

    def test_default_user_auth_issuer(self):
        from kaos_cli.install import _default_user_auth_issuer

        issuer = _default_user_auth_issuer("kc-ns", "keycloak")
        assert issuer == "http://keycloak.kc-ns.svc.cluster.local:8080/realms/kaos"

    def test_keycloak_dev_enables_token_exchange_features_when_requested(self):
        from kaos_cli.install import _keycloak_dev_manifests

        deployment = _keycloak_dev_manifests("keycloak", "keycloak", True)[0]
        args = deployment["spec"]["template"]["spec"]["containers"][0]["args"]
        assert args == [
            "start-dev",
            "--import-realm",
            "--features=token-exchange,admin-fine-grained-authz",
        ]

    def test_auth_enabled_wires_user_auth_values(self):
        """aib-keycloak (user-auth on) adds security.userAuth.* args."""
        from unittest.mock import patch
        from types import SimpleNamespace

        captured = {}

        def fake_helm(args, check=True, **kwargs):
            if "upgrade" in args and any(
                "kaos-operator" in a or a.endswith("/chart") for a in args
            ):
                captured["args"] = args
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        with patch("kaos_cli.install.check_helm_installed", return_value=True), patch(
            "kaos_cli.install.run_helm_command", side_effect=fake_helm
        ), patch("kaos_cli.install._run_kubectl") as mock_kubectl:
            mock_kubectl.return_value = SimpleNamespace(
                returncode=0, stdout="", stderr=""
            )
            result = runner.invoke(
                app,
                [
                    "system",
                    "install",
                    "--agent-auth-enabled",
                    "aib",
                    "--user-auth-enabled",
                    "keycloak",
                    "--chart-path",
                    "operator/chart",
                ],
            )

        assert result.exit_code == 0, result.output
        joined = " ".join(captured.get("args", []))
        assert (
            "security.userAuth.issuer="
            "http://keycloak.keycloak.svc.cluster.local:8080/realms/kaos" in joined
        )
        assert "security.userAuth.audience=kaos" in joined

    def test_no_user_auth_omits_user_auth_values(self):
        """kaos-internal installs neither Keycloak nor the userAuth wiring."""
        from unittest.mock import patch
        from types import SimpleNamespace

        captured = {}

        def fake_helm(args, check=True, **kwargs):
            if "upgrade" in args and any(
                "kaos-operator" in a or a.endswith("/chart") for a in args
            ):
                captured["args"] = args
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        with patch("kaos_cli.install.check_helm_installed", return_value=True), patch(
            "kaos_cli.install.run_helm_command", side_effect=fake_helm
        ), patch("kaos_cli.install._install_keycloak") as mock_kc, patch(
            "kaos_cli.install._run_kubectl"
        ) as mock_kubectl:
            mock_kubectl.return_value = SimpleNamespace(
                returncode=0, stdout="", stderr=""
            )
            result = runner.invoke(
                app,
                [
                    "system",
                    "install",
                    "--agent-auth-enabled",
                    "service-account",
                    "--user-auth-enabled",
                    "none",
                    "--chart-path",
                    "operator/chart",
                ],
            )

        assert result.exit_code == 0, result.output
        mock_kc.assert_not_called()
        joined = " ".join(captured.get("args", []))
        assert "security.userAuth" not in joined
        assert "security.agentAuth.extAuthzUrl=" not in joined
        # The cluster-identity preset bakes in the policy ConfigMap target.
        assert (
            "security.agentAuth.projection.policyConfigMap.name=kaos-authz-policy"
            in joined
        )

    def test_keycloak_install_applies_realm_and_deployment(self):
        """aib-keycloak applies the realm ConfigMap and Keycloak deployment."""
        from unittest.mock import patch
        from types import SimpleNamespace

        kubectl_inputs = []

        def fake_kubectl(args, check=True, **kwargs):
            if "input" in kwargs and kwargs["input"]:
                kubectl_inputs.append(kwargs["input"])
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        with patch("kaos_cli.install.check_helm_installed", return_value=True), patch(
            "kaos_cli.install.run_helm_command",
            return_value=SimpleNamespace(returncode=0, stdout="", stderr=""),
        ), patch("kaos_cli.install._run_kubectl", side_effect=fake_kubectl):
            result = runner.invoke(
                app,
                [
                    "system",
                    "install",
                    "--agent-auth-enabled",
                    "aib",
                    "--user-auth-enabled",
                    "keycloak",
                    "--chart-path",
                    "operator/chart",
                ],
            )

        assert result.exit_code == 0, result.output
        blob = "\n".join(kubectl_inputs)
        assert "ConfigMap" in blob
        assert "kaos-realm.json" in blob
        assert "quay.io/keycloak/keycloak" in blob

    def test_keycloak_chart_path_uses_helm(self):
        """--keycloak-chart-path installs Keycloak via Helm with the realm ConfigMap."""
        from unittest.mock import patch
        from types import SimpleNamespace

        helm_calls = []

        def fake_helm(args, check=True, **kwargs):
            helm_calls.append(args)
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        with patch("kaos_cli.install.check_helm_installed", return_value=True), patch(
            "kaos_cli.install.run_helm_command", side_effect=fake_helm
        ), patch("kaos_cli.install._run_kubectl") as mock_kubectl:
            mock_kubectl.return_value = SimpleNamespace(
                returncode=0, stdout="", stderr=""
            )
            result = runner.invoke(
                app,
                [
                    "system",
                    "install",
                    "--agent-auth-enabled",
                    "aib",
                    "--user-auth-enabled",
                    "keycloak",
                    "--keycloak-chart-path",
                    "charts/keycloak",
                    "--chart-path",
                    "operator/chart",
                ],
            )

        assert result.exit_code == 0, result.output
        joined = " ".join(" ".join(c) for c in helm_calls)
        assert "charts/keycloak" in joined
        assert "realmImport.configMapName=keycloak-realm-import" in joined

    def test_expand_auth_flags_keycloak_aib(self):
        from kaos_cli.install import _expand_auth_flags

        kwargs = _expand_auth_flags("aib", "keycloak", "kaos-system")
        assert kwargs == {
            "auth_enabled": True,
            "gateway_enabled": True,
            "pdp_enabled": True,
            "network_policy": True,
            "gateway_routing": True,
            "policy_data_source": "automated",
            "policy_configmap_name": "kaos-authz-policy",
            "policy_configmap_namespace": "kaos-system",
            "identity_provider": "aib",
            "user_auth": True,
        }

    def test_expand_auth_flags_keycloak_oidc(self):
        from kaos_cli.install import _expand_auth_flags

        kwargs = _expand_auth_flags("keycloak", "keycloak", "kaos-system")
        assert kwargs == {
            "auth_enabled": True,
            "gateway_enabled": True,
            "pdp_enabled": True,
            "network_policy": True,
            "gateway_routing": True,
            "policy_data_source": "automated",
            "policy_configmap_name": "kaos-authz-policy",
            "policy_configmap_namespace": "kaos-system",
            "identity_provider": "oidc",
            "credential_secret_prefix": "kaos-oidc",
            "oidc_registration_secret_name": "kaos-oidc-registration",
            "oidc_registration_secret_key": "token",
            "user_auth": True,
        }

    def test_expand_auth_flags_kaos_internal(self):
        from kaos_cli.install import _expand_auth_flags

        kwargs = _expand_auth_flags("service-account", "none", "kaos-system")
        assert kwargs == {
            "auth_enabled": True,
            "gateway_enabled": True,
            "pdp_enabled": True,
            "network_policy": True,
            "gateway_routing": True,
            "policy_data_source": "automated",
            "policy_configmap_name": "kaos-authz-policy",
            "policy_configmap_namespace": "kaos-system",
            "identity_provider": "serviceaccount",
            "user_auth": False,
        }

    def test_expand_auth_flags_aib_only(self):
        from kaos_cli.install import _expand_auth_flags

        kwargs = _expand_auth_flags("aib", "none", "kaos-system")
        assert kwargs == {
            "auth_enabled": True,
            "gateway_enabled": True,
            "pdp_enabled": True,
            "network_policy": True,
            "gateway_routing": True,
            "policy_data_source": "automated",
            "policy_configmap_name": "kaos-authz-policy",
            "policy_configmap_namespace": "kaos-system",
            "identity_provider": "aib",
            "user_auth": False,
        }

    @pytest.mark.parametrize(
        "agent_mode,user_mode,expected,installs_aib,installs_keycloak",
        [
            (
                "service-account",
                "none",
                {
                    "security.agentAuth.identity.provider=serviceaccount",
                    "security.pdp.enabled=true",
                    "gatewayAPI.enabled=true",
                    "gatewayAPI.createGateway=true",
                    "gatewayAPI.gatewayClassName=envoy-gateway",
                    "security.agentAuth.authorization.policyDataSource=automated",
                    "security.agentAuth.projection.policyConfigMap.name=kaos-authz-policy",
                    "security.agentAuth.projection.policyConfigMap.namespace=kaos-system",
                    "security.gatewayRouting.enabled=true",
                },
                False,
                False,
            ),
            (
                "service-account",
                "keycloak",
                {
                    "security.agentAuth.identity.provider=serviceaccount",
                    "security.pdp.enabled=true",
                    "gatewayAPI.enabled=true",
                    "gatewayAPI.createGateway=true",
                    "gatewayAPI.gatewayClassName=envoy-gateway",
                    "security.agentAuth.authorization.policyDataSource=automated",
                    "security.agentAuth.projection.policyConfigMap.name=kaos-authz-policy",
                    "security.agentAuth.projection.policyConfigMap.namespace=kaos-system",
                    "security.userAuth.issuer=http://keycloak.keycloak.svc.cluster.local:8080/realms/kaos",
                    "security.userAuth.audience=kaos",
                    "security.gatewayRouting.enabled=true",
                },
                False,
                True,
            ),
            (
                "aib",
                "none",
                {
                    "security.agentAuth.identity.provider=aib",
                    "security.pdp.enabled=true",
                    "gatewayAPI.enabled=true",
                    "gatewayAPI.createGateway=true",
                    "gatewayAPI.gatewayClassName=envoy-gateway",
                    "security.agentAuth.issuer=http://aib-agentic-identity-broker.aib-system.svc.cluster.local:8000",
                    "security.agentAuth.credentialSecretPrefix=kaos-aib",
                    "security.agentAuth.adminUrl=http://aib-agentic-identity-broker.aib-system.svc.cluster.local:14000/api",
                    "security.agentAuth.authorization.policyDataSource=automated",
                    "security.agentAuth.projection.policyConfigMap.name=kaos-authz-policy",
                    "security.agentAuth.projection.policyConfigMap.namespace=kaos-system",
                    "security.gatewayRouting.enabled=true",
                },
                True,
                False,
            ),
            (
                "aib",
                "keycloak",
                {
                    "security.agentAuth.identity.provider=aib",
                    "security.pdp.enabled=true",
                    "gatewayAPI.enabled=true",
                    "gatewayAPI.createGateway=true",
                    "gatewayAPI.gatewayClassName=envoy-gateway",
                    "security.agentAuth.issuer=http://aib-agentic-identity-broker.aib-system.svc.cluster.local:8000",
                    "security.agentAuth.credentialSecretPrefix=kaos-aib",
                    "security.agentAuth.adminUrl=http://aib-agentic-identity-broker.aib-system.svc.cluster.local:14000/api",
                    "security.agentAuth.authorization.policyDataSource=automated",
                    "security.agentAuth.projection.policyConfigMap.name=kaos-authz-policy",
                    "security.agentAuth.projection.policyConfigMap.namespace=kaos-system",
                    "security.userAuth.issuer=http://keycloak.keycloak.svc.cluster.local:8080/realms/kaos",
                    "security.userAuth.audience=kaos",
                    "security.gatewayRouting.enabled=true",
                },
                True,
                True,
            ),
            (
                "keycloak",
                "keycloak",
                {
                    "security.agentAuth.identity.provider=oidc",
                    "security.pdp.enabled=true",
                    "gatewayAPI.enabled=true",
                    "gatewayAPI.createGateway=true",
                    "gatewayAPI.gatewayClassName=envoy-gateway",
                    "security.agentAuth.issuer=http://keycloak.keycloak.svc.cluster.local:8080/realms/kaos",
                    "security.agentAuth.identity.oidc.registration.initialAccessTokenSecretRef.name=kaos-oidc-registration",
                    "security.agentAuth.identity.oidc.registration.initialAccessTokenSecretRef.key=token",
                    "security.agentAuth.authorization.policyDataSource=automated",
                    "security.agentAuth.projection.policyConfigMap.name=kaos-authz-policy",
                    "security.agentAuth.projection.policyConfigMap.namespace=kaos-system",
                    "security.userAuth.issuer=http://keycloak.keycloak.svc.cluster.local:8080/realms/kaos",
                    "security.userAuth.audience=kaos",
                    "security.gatewayRouting.enabled=true",
                },
                False,
                True,
            ),
            (
                "keycloak",
                "none",
                {
                    "security.agentAuth.identity.provider=oidc",
                    "security.pdp.enabled=true",
                    "gatewayAPI.enabled=true",
                    "gatewayAPI.createGateway=true",
                    "gatewayAPI.gatewayClassName=envoy-gateway",
                    "security.agentAuth.issuer=http://keycloak.keycloak.svc.cluster.local:8080/realms/kaos",
                    "security.agentAuth.identity.oidc.registration.initialAccessTokenSecretRef.name=kaos-oidc-registration",
                    "security.agentAuth.identity.oidc.registration.initialAccessTokenSecretRef.key=token",
                    "security.agentAuth.authorization.policyDataSource=automated",
                    "security.agentAuth.projection.policyConfigMap.name=kaos-authz-policy",
                    "security.agentAuth.projection.policyConfigMap.namespace=kaos-system",
                    "security.gatewayRouting.enabled=true",
                },
                False,
                True,
            ),
        ],
    )
    def test_auth_flag_combinations_exact_helm_values(
        self, agent_mode, user_mode, expected, installs_aib, installs_keycloak
    ):
        from types import SimpleNamespace
        from unittest.mock import patch

        captured = {}

        def fake_helm(args, check=True, **kwargs):
            captured["operator"] = args
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        with patch("kaos_cli.install.check_helm_installed", return_value=True), patch(
            "kaos_cli.install.run_helm_command", side_effect=fake_helm
        ), patch("kaos_cli.install._install_aib", return_value=True) as mock_aib, patch(
            "kaos_cli.install._install_keycloak", return_value=True
        ) as mock_keycloak:
            result = runner.invoke(
                app,
                [
                    "system",
                    "install",
                    "--agent-auth-enabled",
                    agent_mode,
                    "--user-auth-enabled",
                    user_mode,
                    "--aib-chart-path",
                    "aib/chart",
                    "--chart-path",
                    "operator/chart",
                ],
            )

        assert result.exit_code == 0, result.output
        if installs_aib:
            mock_aib.assert_called_once()
        else:
            mock_aib.assert_not_called()
        if installs_keycloak:
            mock_keycloak.assert_called_once()
        else:
            mock_keycloak.assert_not_called()
        if agent_mode == "keycloak":
            assert (
                "kubectl create secret generic kaos-oidc-registration "
                "-n kaos-system --from-literal=token=<token>" in result.output
            )
        args = captured["operator"]
        rendered = {args[i + 1] for i, arg in enumerate(args) if arg == "--set"}
        assert rendered == expected

    @pytest.mark.parametrize(
        "flag,expected",
        [
            (
                "--agent-auth-enabled",
                "security.agentAuth.identity.provider=serviceaccount",
            ),
            ("--user-auth-enabled", "security.userAuth.audience=kaos"),
        ],
    )
    def test_auth_flags_without_values_use_independent_defaults(self, flag, expected):
        from unittest.mock import patch
        from types import SimpleNamespace

        captured = {}

        def fake_helm(args, check=True, **kwargs):
            if "upgrade" in args and any(
                "kaos-operator" in a or a.endswith("/chart") for a in args
            ):
                captured["args"] = args
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        with patch("kaos_cli.install.check_helm_installed", return_value=True), patch(
            "kaos_cli.install.run_helm_command", side_effect=fake_helm
        ), patch("kaos_cli.install._run_kubectl") as mock_kubectl:
            mock_kubectl.return_value = SimpleNamespace(
                returncode=0, stdout="", stderr=""
            )
            result = runner.invoke(
                app,
                [
                    "system",
                    "install",
                    flag,
                    "--chart-path",
                    "operator/chart",
                ],
            )

        assert result.exit_code == 0, result.output
        joined = " ".join(captured.get("args", []))
        assert expected in joined
        assert "gatewayAPI.enabled=true" in joined

    @pytest.mark.parametrize(
        "flag,message",
        [
            ("--agent-auth-enabled", "Invalid agent auth mode"),
            ("--user-auth-enabled", "Invalid user auth mode"),
        ],
    )
    def test_auth_flags_reject_unknown_modes(self, flag, message):
        result = runner.invoke(app, ["system", "install", flag, "nonsense"])
        assert result.exit_code != 0
        assert message in strip_ansi(result.output)

    def test_conflicting_values_for_one_auth_plane_are_rejected(self):
        result = runner.invoke(
            app,
            [
                "system",
                "install",
                "--user-auth-enabled",
                "keycloak",
                "--user-auth-enabled",
                "none",
            ],
        )
        assert result.exit_code != 0
        assert "--user-auth-enabled may only be specified once" in strip_ansi(
            result.output
        )

    def test_removed_auth_preset_flag_is_rejected(self):
        result = runner.invoke(
            app, ["system", "install", "--auth-enabled", "aib-keycloak"]
        )
        assert result.exit_code != 0
        assert "No such option: --auth-enabled" in strip_ansi(result.output)

    def test_token_exchange_expands_keycloak_aib_and_operator_wiring(self):
        from types import SimpleNamespace
        from unittest.mock import patch

        captured = {}

        def fake_helm(args, check=True, **kwargs):
            captured["operator"] = args
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        with patch("kaos_cli.install.check_helm_installed", return_value=True), patch(
            "kaos_cli.install.run_helm_command", side_effect=fake_helm
        ), patch("kaos_cli.install._install_aib", return_value=True) as mock_aib, patch(
            "kaos_cli.install._install_keycloak", return_value=True
        ) as mock_keycloak:
            result = runner.invoke(
                app,
                [
                    "system",
                    "install",
                    "--token-exchange-enabled",
                    "--aib-chart-path",
                    "aib/chart",
                    "--chart-path",
                    "operator/chart",
                ],
            )

        assert result.exit_code == 0, result.output
        mock_keycloak.assert_called_once()
        mock_aib.assert_called_once()
        aib_args = mock_aib.call_args.kwargs["extra_set"]
        joined_aib = " ".join(aib_args)
        assert "extProc.enabled=true" in joined_aib
        assert "EXTPROC_OAUTH2_ISSUER" in joined_aib
        assert "EXTPROC_OAUTH2_CLIENT_ID" in joined_aib
        assert "EXTPROC_OAUTH2_CLIENT_SECRET" in joined_aib
        assert "EXTPROC_OAUTH2_CLIENT_ASSERTION_TYPE" in joined_aib
        assert "EXTPROC_OAUTH2_TOKEN_ENDPOINT" not in joined_aib
        assert "EXTPROC_OAUTH2_TLS_ALLOW_HTTP" not in joined_aib
        assert "EXTPROC_OAUTH2_CLIENT_CREDENTIALS_ENDPOINT" not in joined_aib
        assert "extProc.oauth2.clientCredentialsEndpoint=" in joined_aib
        assert 'client_assertion.azp == "kaos"' in joined_aib

        assert mock_keycloak.call_args.args[-1] is True

        joined = " ".join(captured["operator"])
        assert "security.agentAuth.identity.provider=oidc" in joined
        assert "security.userAuth.audience=kaos" in joined
        assert "security.tokenExchange.enabled=true" in joined
        assert "security.tokenExchange.aib.adminUrl=" in joined
        assert "security.tokenExchange.extProc.port=50051" in joined

    @pytest.mark.parametrize(
        "args,message",
        [
            (
                [
                    "--agent-auth-enabled",
                    "service-account",
                    "--aib-chart-path",
                    "aib/chart",
                ],
                "requires --agent-auth-enabled keycloak",
            ),
            (
                ["--user-auth-enabled", "none", "--aib-chart-path", "aib/chart"],
                "requires --user-auth-enabled keycloak",
            ),
            ([], "requires --aib-chart-path"),
        ],
    )
    def test_token_exchange_rejects_incompatible_postures(self, args, message):
        result = runner.invoke(
            app, ["system", "install", "--token-exchange-enabled", *args]
        )
        assert result.exit_code != 0
        assert message in strip_ansi(result.output)

    def test_install_without_auth_flags_emits_no_security_values(self):
        from types import SimpleNamespace
        from unittest.mock import patch

        captured = {}

        def fake_helm(args, check=True, **kwargs):
            captured["operator"] = args
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        with patch("kaos_cli.install.check_helm_installed", return_value=True), patch(
            "kaos_cli.install.run_helm_command", side_effect=fake_helm
        ):
            result = runner.invoke(
                app,
                ["system", "install", "--chart-path", "operator/chart"],
            )

        assert result.exit_code == 0, result.output
        rendered = {
            captured["operator"][i + 1]
            for i, arg in enumerate(captured["operator"])
            if arg == "--set"
        }
        assert not any(value.startswith("security.") for value in rendered)

    def test_gateway_api_strict_standalone_without_auth(self):
        """--gateway-api-strict alone emits the strict value without an auth preset."""
        from unittest.mock import patch
        from types import SimpleNamespace

        captured = {}

        def fake_helm(args, check=True, **kwargs):
            if "upgrade" in args and any(
                "kaos-operator" in a or a.endswith("/chart") for a in args
            ):
                captured["args"] = args
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        with patch("kaos_cli.install.check_helm_installed", return_value=True), patch(
            "kaos_cli.install.run_helm_command", side_effect=fake_helm
        ), patch("kaos_cli.install._run_kubectl") as mock_kubectl:
            mock_kubectl.return_value = SimpleNamespace(
                returncode=0, stdout="", stderr=""
            )
            result = runner.invoke(
                app,
                [
                    "system",
                    "install",
                    "--gateway-api-strict",
                    "--chart-path",
                    "operator/chart",
                ],
            )

        assert result.exit_code == 0, result.output
        joined = " ".join(captured.get("args", []))
        assert "security.strictGatewayApi.enabled=true" in joined
        # No auth preset means no agentAuth wiring.
        assert "security.agentAuth.extAuthzUrl=" not in joined
        """--monitoring-enabled without value defaults to signoz (not an invalid backend error)."""
        from unittest.mock import patch

        with patch("kaos_cli.install.check_helm_installed", return_value=False):
            result = runner.invoke(app, ["system", "install", "--monitoring-enabled"])
        # Should not error on invalid backend (signoz is valid)
        assert "Invalid monitoring backend" not in result.output

    def test_uninstall_monitoring_enabled_without_value(self):
        """--monitoring-enabled without value defaults to signoz on uninstall."""
        from unittest.mock import patch

        with patch("kaos_cli.install.check_helm_installed", return_value=False):
            result = runner.invoke(app, ["system", "uninstall", "--monitoring-enabled"])
        assert "Invalid monitoring backend" not in result.output


# ─── Optional value flag preprocessing ──────────────────────────────────


class TestPreprocessOptionalValueFlag:
    def test_flag_without_value_inserts_default(self):
        from kaos_cli.utils import preprocess_optional_value_flag

        args = ["--monitoring-enabled", "--other-flag"]
        result = preprocess_optional_value_flag(args, "--monitoring-enabled", "signoz")
        assert result == ["--monitoring-enabled", "signoz", "--other-flag"]

    def test_flag_with_value_preserves_it(self):
        from kaos_cli.utils import preprocess_optional_value_flag

        args = ["--monitoring-enabled", "jaeger", "--other-flag"]
        result = preprocess_optional_value_flag(args, "--monitoring-enabled", "signoz")
        assert result == ["--monitoring-enabled", "jaeger", "--other-flag"]

    def test_flag_at_end_inserts_default(self):
        from kaos_cli.utils import preprocess_optional_value_flag

        args = ["--some-flag", "--monitoring-enabled"]
        result = preprocess_optional_value_flag(args, "--monitoring-enabled", "signoz")
        assert result == ["--some-flag", "--monitoring-enabled", "signoz"]

    def test_flag_not_present_unchanged(self):
        from kaos_cli.utils import preprocess_optional_value_flag

        args = ["--other-flag", "value"]
        result = preprocess_optional_value_flag(args, "--monitoring-enabled", "signoz")
        assert result == ["--other-flag", "value"]


# ─── Version command ────────────────────────────────────────────────────


class TestVersion:
    def test_version_output(self):
        result = runner.invoke(app, ["version"])
        assert result.exit_code == 0
        assert "kaos-cli" in result.output


# ─── Agent init command ─────────────────────────────────────────────────


class TestAgentInit:
    def test_init_creates_files(self, tmp_path):
        target = str(tmp_path / "my-agent")
        result = runner.invoke(app, ["agent", "init", target])
        assert result.exit_code == 0
        assert (tmp_path / "my-agent" / "agent.py").exists()
        assert (tmp_path / "my-agent" / "pyproject.toml").exists()
        assert (tmp_path / "my-agent" / "README.md").exists()

    def test_init_agent_has_pydantic_agent(self, tmp_path):
        target = str(tmp_path / "my-agent")
        result = runner.invoke(app, ["agent", "init", target])
        assert result.exit_code == 0
        content = (tmp_path / "my-agent" / "agent.py").read_text()
        assert "Agent(" in content
        assert "agent.tool_plain" in content

    def test_init_pyproject_has_pais_dep(self, tmp_path):
        target = str(tmp_path / "my-agent")
        result = runner.invoke(app, ["agent", "init", target])
        assert result.exit_code == 0
        content = (tmp_path / "my-agent" / "pyproject.toml").read_text()
        assert "pydantic-ai" in content

    def test_init_skips_existing_without_force(self, tmp_path):
        target = str(tmp_path / "my-agent")
        runner.invoke(app, ["agent", "init", target])
        result = runner.invoke(app, ["agent", "init", target])
        assert result.exit_code == 0
        assert "Skipping" in strip_ansi(result.output)

    def test_init_force_overwrites(self, tmp_path):
        target = str(tmp_path / "my-agent")
        runner.invoke(app, ["agent", "init", target])
        result = runner.invoke(app, ["agent", "init", target, "--force"])
        assert result.exit_code == 0
        assert "Skipping" not in strip_ansi(result.output)


# ─── Agent build command ────────────────────────────────────────────────


class TestAgentBuild:
    def test_build_help(self):
        result = runner.invoke(app, ["agent", "build", "--help"])
        assert result.exit_code == 0
        output = strip_ansi(result.output)
        assert "--image" in output
        assert "--kind-load" in output
        assert "--push" in output
        assert "--create-dockerfile" in output
        assert "target" in output.lower()

    def test_build_missing_directory(self):
        result = runner.invoke(
            app,
            ["agent", "build", "--image", "test:latest", "--dir", "/nonexistent"],
        )
        assert result.exit_code != 0

    def test_build_missing_entry_point(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text("[project]\nname='test'\n")
        result = runner.invoke(
            app,
            ["agent", "build", "--image", "test:latest", "--dir", str(tmp_path)],
        )
        assert result.exit_code != 0
        assert "Module" in result.output or "not found" in result.output

    def test_build_missing_pyproject(self, tmp_path):
        (tmp_path / "agent.py").write_text("# empty")
        result = runner.invoke(
            app,
            ["agent", "build", "--image", "test:latest", "--dir", str(tmp_path)],
        )
        assert result.exit_code != 0
        assert "pyproject.toml" in result.output


# ─── Agent run command ──────────────────────────────────────────────────


class TestAgentRun:
    def test_run_help(self):
        result = runner.invoke(app, ["agent", "run", "--help"])
        assert result.exit_code == 0
        output = strip_ansi(result.output)
        assert "--host" in output
        assert "--port" in output
        assert "--reload" in output

    def test_run_missing_file(self):
        result = runner.invoke(app, ["agent", "run", "nonexistent.py"])
        assert result.exit_code != 0


# ─── MCP run command ────────────────────────────────────────────────────


class TestMcpRun:
    def test_run_help(self):
        result = runner.invoke(app, ["mcp", "run", "--help"])
        assert result.exit_code == 0
        output = strip_ansi(result.output)
        assert "--host" in output
        assert "--port" in output
        assert "--reload" in output

    def test_run_missing_file(self):
        result = runner.invoke(app, ["mcp", "run", "nonexistent.py"])
        assert result.exit_code != 0
