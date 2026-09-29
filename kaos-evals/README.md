# KAOS Evals

`kaos-evals` is the evaluation library and local runner for KAOS agents. It owns the portable suite and result contract, deterministic gate decisions, the Pydantic Evals engine boundary, OpenAI-compatible target adapters, and evaluation telemetry.

| Install | Modules | Dependencies |
| --- | --- | --- |
| `kaos-evals` (core) | contracts and gates | Pydantic, PyYAML, OpenTelemetry API |
| `kaos-evals[runner]` | harness, targets, runner, telemetry export | + Pydantic Evals, Pydantic AI, httpx, OpenTelemetry SDK |

The core contract does not import the evaluation engine. Pydantic Evals is an implementation detail behind the harness boundary, so persisted reports and gate decisions use only KAOS-owned models.

This package runs evaluations locally against an in-process app or an OpenAI-compatible HTTP endpoint. Kubernetes Jobs, CRDs, operator integration, CLI commands, examples, and the runner container are outside this package's current boundary.

## Development

```bash
uv venv
source .venv/bin/activate
make build
make test
make lint
```

All dependency installation and commands use uv. The runner extra pins the validated engine version so report mapping remains reproducible.
