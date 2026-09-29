from dataclasses import dataclass, field


@dataclass
class FakeTargetResponse:
    output: object
    duration_seconds: float = 0
    usage: dict[str, float | int] = field(default_factory=dict)
    trace_id: str | None = None
