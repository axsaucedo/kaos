# Contributing to Pydantic AI Server

This directory is managed as a git subtree in the [KAOS monorepo](https://github.com/axsaucedo/agentic-kubernetes-operator).

All development happens here. Changes are automatically synced to the standalone mirror at [axsaucedo/pydantic-ai-server](https://github.com/axsaucedo/pydantic-ai-server).

## Development

```bash
cd pydantic-ai-server
source .venv/bin/activate
python -m pytest tests/ -v    # Run tests
make lint                      # Linting
```
