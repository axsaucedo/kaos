"""KAOS-owned evaluation suite and result contract."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from pydantic.alias_generators import to_camel

CONTRACT_VERSION = "1"


class ContractModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
    )


class EvaluatorKind(StrEnum):
    CONTAINS = "contains"
    EQUALS = "equals"
    REGEX = "regex"
    IS_JSON = "is_json"
    MAX_DURATION = "max_duration"
    LLM_JUDGE = "llm_judge"


class Verdict(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    ERROR = "error"


class FailureKind(StrEnum):
    CANDIDATE_ERROR = "candidate_error"
    EVALUATOR_INCONCLUSIVE = "evaluator_inconclusive"
    RUN_ERROR = "run_error"


class EvaluatorSpec(ContractModel):
    name: str = Field(min_length=1)
    kind: EvaluatorKind
    config: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_config(self) -> "EvaluatorSpec":
        config = self.config
        allowed: set[str]
        required: set[str]
        if self.kind == EvaluatorKind.CONTAINS:
            allowed, required = {"value", "caseSensitive"}, {"value"}
            if "value" in config and not isinstance(config["value"], str):
                raise ValueError("config.value must be a string")
            if "caseSensitive" in config and not isinstance(config["caseSensitive"], bool):
                raise ValueError("config.caseSensitive must be a boolean")
        elif self.kind == EvaluatorKind.EQUALS:
            allowed, required = {"value"}, {"value"}
        elif self.kind == EvaluatorKind.REGEX:
            allowed, required = {"pattern", "flags"}, {"pattern"}
            if "pattern" in config and not isinstance(config["pattern"], str):
                raise ValueError("config.pattern must be a string")
            if "flags" in config and not isinstance(config["flags"], str):
                raise ValueError("config.flags must be a string")
            if isinstance(config.get("pattern"), str):
                try:
                    re.compile(config["pattern"])
                except re.error as exc:
                    raise ValueError(f"config.pattern is invalid: {exc}") from exc
        elif self.kind == EvaluatorKind.IS_JSON:
            allowed, required = set(), set()
        elif self.kind == EvaluatorKind.MAX_DURATION:
            allowed, required = {"seconds"}, {"seconds"}
            seconds = config.get("seconds")
            if seconds is not None and (
                isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or seconds <= 0
            ):
                raise ValueError("config.seconds must be greater than zero")
        else:
            allowed, required = {
                "rubric",
                "model",
                "includeInput",
                "includeExpectedOutput",
                "score",
            }, {"rubric", "model"}
            for key in ("rubric", "model"):
                if key in config and (not isinstance(config[key], str) or not config[key]):
                    raise ValueError(f"config.{key} must be a non-empty string")
            for key in ("includeInput", "includeExpectedOutput", "score"):
                if key in config and not isinstance(config[key], bool):
                    raise ValueError(f"config.{key} must be a boolean")

        missing = required - config.keys()
        if missing:
            raise ValueError(f"config.{sorted(missing)[0]} is required for {self.kind}")
        unknown = config.keys() - allowed
        if unknown:
            raise ValueError(f"config.{sorted(unknown)[0]} is not valid for {self.kind}")
        return self


class GateSpec(ContractModel):
    min_pass_rate: float = Field(default=1.0, ge=0, le=1)
    thresholds: dict[str, float] = Field(default_factory=dict)
    critical_tags: list[str] = Field(default_factory=list)
    max_total_duration_seconds: float | None = Field(default=None, gt=0)
    max_total_tokens: int | None = Field(default=None, gt=0)
    max_total_cost_usd: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_thresholds(self) -> "GateSpec":
        for name, value in self.thresholds.items():
            if not name:
                raise ValueError("thresholds evaluator name must not be empty")
            if isinstance(value, bool) or not 0 <= value <= 1:
                raise ValueError(f"thresholds.{name} must be between 0 and 1")
        return self


class EvalCase(ContractModel):
    id: str = Field(min_length=1)
    prompt: str | None = None
    messages: list[dict[str, Any]] | None = None
    expected_output: Any | None = None
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    evaluators: list[EvaluatorSpec] = Field(default_factory=list)

    @model_validator(mode="after")
    def exactly_one_input(self) -> "EvalCase":
        if (self.prompt is None) == (self.messages is None):
            raise ValueError("exactly one of prompt or messages is required")
        if self.prompt is not None and not self.prompt:
            raise ValueError("prompt must not be empty")
        if self.messages is not None and not self.messages:
            raise ValueError("messages must not be empty")
        return self

    @property
    def input(self) -> str | list[dict[str, Any]]:
        return self.prompt if self.prompt is not None else self.messages or []


class RunSpec(ContractModel):
    max_concurrency: int = Field(default=4, ge=1)
    repeat: int = Field(default=1, ge=1)
    timeout_seconds: float = Field(default=60, gt=0)


class TargetSpec(ContractModel):
    mode: str = Field(default="http", pattern="^(http|local)$")
    url: str | None = None
    model: str = "agent"

    @model_validator(mode="after")
    def require_http_url(self) -> "TargetSpec":
        if self.mode == "http" and not self.url:
            raise ValueError("url is required when mode is http")
        return self


class EvalSuite(ContractModel):
    name: str = Field(min_length=1)
    version: str = "1"
    evaluators: list[EvaluatorSpec] = Field(default_factory=list)
    cases: list[EvalCase] = Field(min_length=1)
    gates: GateSpec = Field(default_factory=GateSpec)
    run: RunSpec = Field(default_factory=RunSpec)

    @model_validator(mode="after")
    def unique_names(self) -> "EvalSuite":
        case_ids = [case.id for case in self.cases]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("cases.id values must be unique")
        evaluator_names = [evaluator.name for evaluator in self.evaluators]
        if len(evaluator_names) != len(set(evaluator_names)):
            raise ValueError("evaluators.name values must be unique")
        return self

    @classmethod
    def load(cls, path: str | Path) -> "EvalSuite":
        return load_suite(path)

    def canonical_json(self) -> str:
        return json.dumps(
            self.model_dump(mode="json", by_alias=True),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )

    def suite_hash(self) -> str:
        return hashlib.sha256(self.canonical_json().encode()).hexdigest()


class EvaluatorResult(ContractModel):
    name: str
    value: bool | int | float | str | None = None
    passed: bool | None = None
    reason: str | None = None
    failure_kind: FailureKind | None = None


class CaseResult(ContractModel):
    case_id: str
    repetition: int = Field(default=1, ge=1)
    tags: list[str] = Field(default_factory=list)
    output: Any | None = None
    duration_seconds: float = Field(default=0, ge=0)
    usage: dict[str, float | int] = Field(default_factory=dict)
    trace_id: str | None = None
    evaluator_results: list[EvaluatorResult] = Field(default_factory=list)
    passed: bool = False
    failure_kind: FailureKind | None = None
    error: str | None = None


class GateEvaluation(ContractModel):
    verdict: Verdict
    pass_rate: float = Field(ge=0, le=1)
    passed_cases: int = Field(ge=0)
    total_cases: int = Field(ge=0)
    failed_rules: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)


class Provenance(ContractModel):
    suite_hash: str
    target: TargetSpec
    engine_version: str
    contract_version: str = CONTRACT_VERSION
    judge_models: dict[str, str] = Field(default_factory=dict)
    started_at: datetime
    finished_at: datetime


class RunResult(ContractModel):
    suite_name: str
    verdict: Verdict
    cases: list[CaseResult]
    gate: GateEvaluation
    provenance: Provenance | None = None
    failure_kind: FailureKind | None = None
    error: str | None = None


def load_suite(path: str | Path) -> EvalSuite:
    suite_path = Path(path)
    try:
        text = suite_path.read_text()
    except OSError as exc:
        raise ValueError(f"cannot read suite {suite_path}: {exc}") from exc
    try:
        data = json.loads(text) if suite_path.suffix.lower() == ".json" else yaml.safe_load(text)
    except (json.JSONDecodeError, yaml.YAMLError) as exc:
        raise ValueError(f"invalid suite document {suite_path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"invalid suite document {suite_path}: root must be an object")
    try:
        return EvalSuite.model_validate(data)
    except ValidationError as exc:
        fields = ", ".join(".".join(str(part) for part in error["loc"]) for error in exc.errors())
        raise ValueError(
            f"invalid suite {suite_path}; offending field(s): {fields}: {exc}"
        ) from exc


__all__ = [
    "CONTRACT_VERSION",
    "CaseResult",
    "EvalCase",
    "EvalSuite",
    "EvaluatorKind",
    "EvaluatorResult",
    "EvaluatorSpec",
    "FailureKind",
    "GateEvaluation",
    "GateSpec",
    "Provenance",
    "RunResult",
    "RunSpec",
    "TargetSpec",
    "Verdict",
    "load_suite",
]
