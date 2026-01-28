---
applyTo: "python/**"
---

# Python Agent Framework Instructions

## Quick Reference
```bash
cd python
source .venv/bin/activate
python -m pytest tests/ -v      # Run all tests
make lint                       # Run linting (black + ty check)
make format                     # Auto-format code
```

## Project Structure
- `agent/client.py`: Agent, RemoteAgent, AgentCard classes
- `agent/server.py`: AgentServer with A2A endpoints
- `agent/memory.py`: LocalMemory for session/event management
- `agent/telemetry/`: OpenTelemetry instrumentation (tracing, metrics)
- `mcptools/`: MCP (Model Context Protocol) tools
- `modelapi/`: Model API client for OpenAI-compatible servers

## Key Environment Variables
| Variable | Description |
|----------|-------------|
| `AGENT_NAME` | Agent name (required) |
| `MODEL_API_URL` | LLM API base URL (required) |
| `MODEL_NAME` | Model name (required) |
| `AGENT_SUB_AGENTS` | Direct format: `"name:url,name:url"` |
| `DEBUG_MOCK_RESPONSES` | JSON array of mock responses for testing |
| `OTEL_ENABLED` | Enable OpenTelemetry instrumentation |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | OTLP exporter endpoint |

## Testing Patterns
- Use `DEBUG_MOCK_RESPONSES` for deterministic tests
- Tests use `pytest-asyncio` for async test functions
- Use `@pytest.mark.parametrize` for testing multiple cases

## Code Style
- Use `black` for formatting
- Use `ty` for type checking
- Prefer async/await patterns
- Minimal comments (only when clarification needed)

## API Endpoints
- `GET /health`: Health probe
- `GET /ready`: Readiness probe  
- `GET /.well-known/agent`: A2A agent card
- `POST /v1/chat/completions`: OpenAI-compatible chat endpoint
