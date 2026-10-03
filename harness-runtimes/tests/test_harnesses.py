"""Adapter-level tests. These need no harness binary and no model endpoint."""

import json
import os

import pytest

from kaos_harness.harnesses import (
    REGISTRY,
    ClaudeHarness,
    HarnessConfig,
    PiHarness,
    get_harness,
)


def config(tmp_path, **overrides):
    return HarnessConfig(
        model_api_url="http://modelapi.default.svc:80",
        model_name="qwen3",
        state_dir=str(tmp_path),
        **overrides,
    )


def test_registry_holds_the_known_harnesses():
    assert set(REGISTRY) == {"pi", "claude"}


def test_unknown_harness_is_a_clear_error(tmp_path):
    with pytest.raises(ValueError, match="unknown harness"):
        get_harness("dsh", config(tmp_path))


def test_pi_writes_an_openai_provider_pointing_at_the_modelapi(tmp_path):
    """pi speaks OpenAI chat completions, so a KAOS ModelAPI works unchanged."""
    harness = get_harness("pi", config(tmp_path))
    harness.prepare()
    written = json.load(open(os.path.join(tmp_path, ".pi", "agent", "models.json")))
    provider = written["providers"]["kaos-modelapi"]
    assert provider["baseUrl"] == "http://modelapi.default.svc:80/v1"
    assert provider["api"] == "openai-completions"
    assert provider["models"][0]["id"] == "qwen3"


def test_pi_reads_its_config_from_the_state_dir(tmp_path):
    harness = get_harness("pi", config(tmp_path))
    assert harness.environ()["HOME"] == str(tmp_path)


def test_pi_is_driven_over_the_rpc_event_stream(tmp_path):
    """`--mode rpc` is the only pi surface carrying tool lifecycle and usage."""
    harness = PiHarness(config(tmp_path, instructions="be terse"))
    argv = harness.argv("sess-1")
    assert argv[1:3] == ["--mode", "rpc"]
    assert "--session-id" in argv and "sess-1" in argv
    for flag in ("--no-extensions", "--no-skills", "--no-context-files"):
        assert flag in argv
    assert argv[argv.index("--append-system-prompt") + 1] == "be terse"


def test_claude_is_configured_over_the_anthropic_env_vars(tmp_path):
    """Claude Code speaks /v1/messages only; base URL arrives as an env var."""
    harness = ClaudeHarness(config(tmp_path))
    env = harness.environ()
    assert env["ANTHROPIC_BASE_URL"] == "http://modelapi.default.svc:80"
    assert env["ANTHROPIC_AUTH_TOKEN"]
    assert harness.argv("do it")[1] == "-p"


def test_missing_binary_is_reported_not_raised(tmp_path):
    harness = get_harness("pi", config(tmp_path, binary=str(tmp_path / "nope")))
    assert harness.available() is False
