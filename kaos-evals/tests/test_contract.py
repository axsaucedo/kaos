import json

import pytest
import yaml
from pydantic import ValidationError

from kaos_evals.contract import EvalCase, EvalSuite, EvaluatorSpec, GateSpec, load_suite

SUITE = {
    "name": "smoke",
    "evaluators": [
        {"name": "has-answer", "kind": "contains", "config": {"value": "42"}},
        {"name": "fast", "kind": "max_duration", "config": {"seconds": 2}},
    ],
    "cases": [
        {"id": "question", "prompt": "What is six times seven?", "tags": ["critical"]},
        {
            "id": "chat",
            "messages": [{"role": "user", "content": "Hello"}],
            "expectedOutput": "Hi",
        },
    ],
    "gates": {"minPassRate": 0.5, "thresholds": {"has-answer": 0.8}},
    "run": {"maxConcurrency": 2, "repeat": 2, "timeoutSeconds": 5},
}


def test_yaml_and_json_round_trip(tmp_path):
    yaml_path = tmp_path / "suite.yaml"
    yaml_path.write_text(yaml.safe_dump(SUITE))
    suite = load_suite(yaml_path)

    json_path = tmp_path / "suite.json"
    json_path.write_text(suite.model_dump_json(by_alias=True))
    restored = EvalSuite.load(json_path)

    assert restored == suite
    assert restored.cases[1].expected_output == "Hi"
    assert restored.model_dump(by_alias=True)["gates"]["minPassRate"] == 0.5


def test_hash_is_stable_under_mapping_key_reordering():
    reordered = json.loads(json.dumps(SUITE))
    reordered["gates"]["thresholds"] = {"z": 0.2, "has-answer": 0.8}
    original = json.loads(json.dumps(reordered))
    reordered["gates"]["thresholds"] = {"has-answer": 0.8, "z": 0.2}

    assert (
        EvalSuite.model_validate(original).suite_hash()
        == EvalSuite.model_validate(reordered).suite_hash()
    )


def test_hash_changes_when_content_changes():
    changed = json.loads(json.dumps(SUITE))
    changed["cases"][0]["prompt"] = "Changed"

    assert (
        EvalSuite.model_validate(SUITE).suite_hash()
        != EvalSuite.model_validate(changed).suite_hash()
    )


@pytest.mark.parametrize(
    ("kind", "config", "field"),
    [
        ("contains", {}, "config.value"),
        ("regex", {"pattern": "["}, "config.pattern"),
        ("is_json", {"unexpected": True}, "config.unexpected"),
        ("max_duration", {"seconds": 0}, "config.seconds"),
        ("llm_judge", {"rubric": "Good"}, "config.model"),
    ],
)
def test_evaluator_config_validation_names_field(kind, config, field):
    with pytest.raises(ValidationError, match=field):
        EvaluatorSpec(name="test", kind=kind, config=config)


def test_case_requires_exactly_one_input_form():
    with pytest.raises(ValidationError, match="exactly one of prompt or messages"):
        EvalCase(id="missing")
    with pytest.raises(ValidationError, match="exactly one of prompt or messages"):
        EvalCase(id="both", prompt="Hi", messages=[{"role": "user", "content": "Hi"}])


@pytest.mark.parametrize(
    "kwargs",
    [
        {"min_pass_rate": -0.1},
        {"min_pass_rate": 1.1},
        {"thresholds": {"judge": -0.1}},
        {"thresholds": {"judge": 1.1}},
        {"max_total_tokens": 0},
        {"max_total_duration_seconds": 0},
        {"max_total_cost_usd": -1},
    ],
)
def test_gate_bounds(kwargs):
    with pytest.raises(ValidationError):
        GateSpec(**kwargs)


def test_loader_error_names_offending_field(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text("name: bad\ncases:\n  - id: missing-input\n")

    with pytest.raises(ValueError, match=r"offending field\(s\): cases.0"):
        load_suite(path)
