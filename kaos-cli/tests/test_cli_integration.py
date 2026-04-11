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
                "agent", "deploy", "auto-agent",
                "--modelapi", "api", "--model", "m1",
                "--autonomous", "Monitor system health",
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
                "agent", "deploy", "auto-agent",
                "--modelapi", "api", "--model", "m1",
                "--autonomous", "Check health",
                "--auto-max-iter-runtime", "120",
                "--auto-interval", "5.0",
                "--task-max-iterations", "20",
                "--task-max-runtime", "600",
                "--task-max-tool-calls", "100",
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
                "agent", "deploy", "auto-agent",
                "--modelapi", "api", "--model", "m1",
                "--task-max-iterations", "0",
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
                "agent", "deploy", "auto-agent",
                "--modelapi", "api", "--model", "m1",
                "--description", "Auto agent",
                "--autonomous", "Do work",
                "--mcp", "echo-mcp",
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
                "agent", "deploy", "basic-agent",
                "--modelapi", "api", "--model", "m1",
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
        assert "--mode" in output
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
                assert doc["kind"] != "Namespace", "Namespace doc should be filtered out"
                assert doc["metadata"].get("namespace") == "test-ns", (
                    f"{doc['kind']} {doc['metadata']['name']} missing namespace override"
                )

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
        assert len(files) == 6
        names = [f.stem for f in files]
        assert "1-simple-echo-agent" in names
        assert "5-proxy-external-api" in names


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
            result = runner.invoke(
                app, ["ui", "--monitoring-enabled", "--no-browser"]
            )
        # Should not error on invalid backend; fails on service not found instead
        assert "Invalid monitoring backend" not in result.output
        assert "signoz" in result.output.lower()


# ─── System install flags ───────────────────────────────────────────────


class TestSystemInstallFlags:
    def test_install_help_shows_gateway_flag(self):
        result = runner.invoke(app, ["system", "install", "--help"])
        assert result.exit_code == 0
        output = strip_ansi(result.output)
        assert "--gateway-enabled" in output
        assert "--metallb-enabled" in output
        assert "--redis-enabled" in output

    def test_uninstall_help_shows_gateway_flag(self):
        result = runner.invoke(app, ["system", "uninstall", "--help"])
        assert result.exit_code == 0
        output = strip_ansi(result.output)
        assert "--gateway-enabled" in output
        assert "--metallb-enabled" in output
        assert "--redis-enabled" in output

    def test_install_invalid_monitoring_backend(self):
        result = runner.invoke(
            app, ["system", "install", "--monitoring-enabled", "invalid"]
        )
        assert result.exit_code != 0
        assert "Invalid monitoring backend" in result.output

    def test_install_monitoring_enabled_without_value(self):
        """--monitoring-enabled without value defaults to signoz (not an invalid backend error)."""
        from unittest.mock import patch

        with patch("kaos_cli.install.check_helm_installed", return_value=False):
            result = runner.invoke(
                app, ["system", "install", "--monitoring-enabled"]
            )
        # Should not error on invalid backend (signoz is valid)
        assert "Invalid monitoring backend" not in result.output

    def test_uninstall_monitoring_enabled_without_value(self):
        """--monitoring-enabled without value defaults to signoz on uninstall."""
        from unittest.mock import patch

        with patch("kaos_cli.install.check_helm_installed", return_value=False):
            result = runner.invoke(
                app, ["system", "uninstall", "--monitoring-enabled"]
            )
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
