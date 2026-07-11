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
        assert len(files) == 7
        names = [f.stem for f in files]
        assert "1-simple-echo-agent" in names
        assert "5-proxy-external-api" in names
        assert "7-memory-agent" in names


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
        assert "--auth-enabled" in output
        # The fine-grained auth knobs are collapsed into the preset and no longer
        # exposed on the command surface.
        assert "--authz-provider" not in output
        assert "--agent-jwt-verification" not in output
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


class TestAuthWiring:
    @pytest.fixture(autouse=True)
    def _stub_gateway_install(self):
        """Stub the gateway install/wait helpers so preset-driven installs.

        The auth presets force --gateway-enabled, which otherwise polls the
        cluster for GatewayClass acceptance for 60s. Tests here assert on the
        operator --set wiring, not the gateway bootstrap, so short-circuit it.
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
        assert "security.agentAuth.issuer=http://aib.aib-system:8000" in joined
        assert "security.agentAuth.credentialSecretPrefix=kaos-aib" in joined
        # Each value is preceded by a --set flag.
        assert args.count("--set") == 3

    def test_default_endpoints_use_auth_namespace(self):
        from kaos_cli.install import (
            _default_ext_authz_url,
            _default_auth_issuer,
            _default_auth_admin_url,
        )

        assert _default_ext_authz_url("custom-ns").startswith(
            "aib-access-check-grpc.custom-ns"
        )
        assert _default_ext_authz_url("custom-ns").endswith(":9191")
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
                    "--auth-enabled",
                    "aib-keycloak",
                    "--chart-path",
                    "operator/chart",
                ],
            )

        assert result.exit_code == 0, result.output
        joined = " ".join(captured.get("args", []))
        assert "security.agentAuth.extAuthzUrl=" in joined
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

    def test_build_auth_operator_args_includes_ext_proc_url(self):
        from kaos_cli.install import _build_auth_operator_args

        args = _build_auth_operator_args(
            "aib-access-check-grpc.aib-system:9191",
            "http://aib.aib-system:8000",
            "kaos-aib",
            ext_proc_url="aib-agentic-identity-broker-extproc.aib-system:50051",
        )
        joined = " ".join(args)
        assert (
            "security.agentAuth.extProcUrl="
            "aib-agentic-identity-broker-extproc.aib-system:50051" in joined
        )

    def test_build_auth_operator_args_omits_ext_proc_url_when_unset(self):
        from kaos_cli.install import _build_auth_operator_args

        args = _build_auth_operator_args(
            "aib-access-check-grpc.aib-system:9191",
            "http://aib.aib-system:8000",
            "kaos-aib",
        )
        assert "security.agentAuth.extProcUrl=" not in " ".join(args)

    def test_build_auth_operator_args_kaos_authorization(self):
        from kaos_cli.install import _build_auth_operator_args

        args = _build_auth_operator_args(
            "aib-access-check-grpc.aib-system:9191",
            "http://aib.aib-system:8000",
            "kaos-aib",
            authz_provider="kaos",
            policy_data_source="automated",
            agent_jwt_verification="verified",
            policy_configmap_name="kaos-authz-policy",
            policy_configmap_namespace="aib-system",
        )
        joined = " ".join(args)
        assert "security.agentAuth.authorization.provider=kaos" in joined
        assert "security.agentAuth.authorization.policyDataSource=automated" in joined
        assert (
            "security.agentAuth.authorization.agentJwtVerification=verified" in joined
        )
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
            authz_provider="kaos",
            policy_data_source="manual",
            policy_rego_override=True,
        )
        joined = " ".join(args)
        assert "security.agentAuth.authorization.policyRegoOverride=true" in joined
        assert "security.agentAuth.authorization.policyDataSource=manual" in joined

    def test_build_auth_operator_args_broker_external_off_switch(self):
        from kaos_cli.install import _build_auth_operator_args

        args = _build_auth_operator_args(
            "aib-access-check-grpc.aib-system:9191",
            "http://aib.aib-system:8000",
            "kaos-aib",
            admin_url="http://aib.aib-system:8000/api",
            authz_provider="aib",
            policy_data_source="external",
            authz_gateway_extension="ext_authz",
        )
        joined = " ".join(args)
        assert "security.agentAuth.authorization.provider=aib" in joined
        assert "security.agentAuth.authorization.policyDataSource=external" in joined
        assert "security.agentAuth.authorization.gatewayExtension=ext_authz" in joined
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

    def test_default_ext_proc_url(self):
        from kaos_cli.install import _default_ext_proc_url

        url = _default_ext_proc_url("custom-ns", "aib")
        assert url == (
            "aib-agentic-identity-broker-extproc.custom-ns.svc.cluster.local:50051"
        )

    def test_build_aib_extproc_args(self):
        from kaos_cli.install import _build_aib_extproc_args

        args = _build_aib_extproc_args("extproc-gateway", "secret")
        joined = " ".join(args)
        assert "extProc.enabled=true" in joined
        assert "extProc.oauth2.clientId=extproc-gateway" in joined
        assert "extProc.oauth2.clientSecret=secret" in joined
        # The in-cluster broker enduser endpoint is plain http, so the ExtProc
        # binary must be told to accept http:// endpoints at startup.
        assert "extProc.oauth2.allowHttp=true" in joined
        # Issuer/tokenEndpoint are omitted unless supplied (chart defaults apply).
        assert "extProc.oauth2.issuer" not in joined
        assert "extProc.oauth2.tokenEndpoint" not in joined

    def test_build_aib_extproc_args_with_endpoints(self):
        from kaos_cli.install import _build_aib_extproc_args

        args = _build_aib_extproc_args(
            "extproc-gateway",
            "secret",
            issuer="http://keycloak.keycloak.svc.cluster.local:8080/realms/kaos",
            token_endpoint="http://broker.aib.svc.cluster.local:8080/oauth2/token",
        )
        joined = " ".join(args)
        assert (
            "extProc.oauth2.issuer="
            "http://keycloak.keycloak.svc.cluster.local:8080/realms/kaos" in joined
        )
        assert (
            "extProc.oauth2.tokenEndpoint="
            "http://broker.aib.svc.cluster.local:8080/oauth2/token" in joined
        )

    def test_build_aib_hybrid_broker_args(self):
        from kaos_cli.install import _build_aib_hybrid_broker_args

        issuer = "http://keycloak.keycloak.svc.cluster.local:8080/realms/kaos"
        joined = " ".join(_build_aib_hybrid_broker_args(issuer))
        assert "broker.oauth2AuthorizationServer.mode=hybrid" in joined
        assert (
            f"broker.oauth2AuthorizationServer.proxy.upstreamIssuerUri={issuer}"
            in joined
        )
        assert (
            "broker.oauth2AuthorizationServer.proxy.upstreamTokenEndpoint="
            f"{issuer}/protocol/openid-connect/token" in joined
        )
        assert (
            "broker.oauth2AuthorizationServer.proxy.upstreamAuthorizeEndpoint="
            f"{issuer}/protocol/openid-connect/auth" in joined
        )
        assert "urn:ietf:params:oauth:grant-type:token-exchange" in joined
        assert "broker.tokenExchange.expectedAudience=token-exchange-broker" in joined

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

    def test_keycloak_realm_json_registers_extproc_client(self):
        from kaos_cli.install import (
            AUTH_EXT_PROC_CLIENT_ID,
            AUTH_EXT_PROC_CLIENT_SECRET,
            AUTH_TOKEN_EXCHANGE_AUDIENCE,
            _keycloak_realm_json,
        )

        realm = _keycloak_realm_json(
            "kaos", "kaos", "kaos-dev-secret", "kaos", "kaos-user", "kaos-password"
        )
        clients = {c["clientId"]: c for c in realm["clients"]}
        # The ExtProc gateway service-account client is registered so the
        # token-exchange sidecar can mint its client assertion.
        assert AUTH_EXT_PROC_CLIENT_ID in clients
        extproc = clients[AUTH_EXT_PROC_CLIENT_ID]
        assert extproc["secret"] == AUTH_EXT_PROC_CLIENT_SECRET
        assert extproc["serviceAccountsEnabled"] is True
        # Both clients carry the token-exchange broker audience the broker enforces.
        for client_id in ("kaos", AUTH_EXT_PROC_CLIENT_ID):
            audiences = [
                m["config"].get("included.custom.audience")
                for m in clients[client_id]["protocolMappers"]
            ]
            assert AUTH_TOKEN_EXCHANGE_AUDIENCE in audiences

    def test_default_user_auth_issuer(self):
        from kaos_cli.install import _default_user_auth_issuer

        issuer = _default_user_auth_issuer("kc-ns", "keycloak")
        assert issuer == "http://keycloak.kc-ns.svc.cluster.local:8080/realms/kaos"

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
                    "--auth-enabled",
                    "aib-keycloak",
                    "--chart-path",
                    "operator/chart",
                ],
            )

        assert result.exit_code == 0, result.output
        joined = " ".join(captured.get("args", []))
        assert "security.userAuth.issuer=" in joined
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
                    "--auth-enabled",
                    "kaos-internal",
                    "--chart-path",
                    "operator/chart",
                ],
            )

        assert result.exit_code == 0, result.output
        mock_kc.assert_not_called()
        joined = " ".join(captured.get("args", []))
        assert "security.userAuth" not in joined
        # Agent-auth wiring is unaffected.
        assert "security.agentAuth.extAuthzUrl=" in joined
        # Demo posture selects the KAOS-owned policy provider with header-trusted
        # agent JWT.
        assert "security.agentAuth.authorization.provider=kaos" in joined
        assert "security.agentAuth.authorization.agentJwtVerification=skip" in joined
        # The demo preset bakes in the policy ConfigMap projection target.
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
                    "--auth-enabled",
                    "aib-keycloak",
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
                    "--auth-enabled",
                    "aib-keycloak",
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

    def test_expand_auth_preset_keycloak_aib(self):
        from kaos_cli.install import _expand_auth_preset

        kwargs = _expand_auth_preset("aib-keycloak", "kaos-system")
        assert kwargs["auth_enabled"] is True
        assert kwargs["user_auth"] is True
        assert kwargs["token_exchange"] is True
        assert kwargs["authz_provider"] == "aib"
        assert kwargs["authz_gateway_extension"] == "ext_proc"
        assert kwargs["agent_jwt_verification"] == "verified"

    def test_expand_auth_preset_kaos_internal(self):
        from kaos_cli.install import _expand_auth_preset

        kwargs = _expand_auth_preset("kaos-internal", "kaos-system")
        assert kwargs["auth_enabled"] is True
        assert kwargs["user_auth"] is False
        assert kwargs["token_exchange"] is False
        assert kwargs["authz_provider"] == "kaos"
        assert kwargs["agent_jwt_verification"] == "skip"
        # The demo preset bakes in the policy ConfigMap projection target so no
        # extra flags are needed for the operator to project policy data.
        assert kwargs["policy_configmap_name"] == "kaos-authz-policy"
        assert kwargs["policy_configmap_namespace"] == "kaos-system"

    def test_expand_auth_preset_aib_only(self):
        from kaos_cli.install import _expand_auth_preset

        kwargs = _expand_auth_preset("aib-only", "kaos-system")
        assert kwargs["auth_enabled"] is True
        assert kwargs["user_auth"] is False
        assert kwargs["token_exchange"] is False
        assert kwargs["authz_provider"] == "aib"
        assert kwargs["agent_jwt_verification"] == "verified"

    def test_auth_enabled_without_value_defaults_to_aib_keycloak(self):
        """--auth-enabled with no value selects the keycloak-aib preset."""
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
                    "--auth-enabled",
                    "--chart-path",
                    "operator/chart",
                ],
            )

        assert result.exit_code == 0, result.output
        joined = " ".join(captured.get("args", []))
        assert "security.agentAuth.authorization.provider=aib" in joined
        # Preset implies the gateway is installed for enforcement.
        assert "gatewayAPI.enabled=true" in joined

    def test_auth_enabled_rejects_unknown_preset(self):
        result = runner.invoke(app, ["system", "install", "--auth-enabled", "nonsense"])
        assert result.exit_code != 0
        assert "Invalid auth preset" in strip_ansi(result.output)

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
