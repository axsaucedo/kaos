"""Entrypoint: build the service from the environment and serve it with uvicorn."""

from __future__ import annotations

import uvicorn

from kaos_memory.service import create_app
from kaos_memory.settings import MemorySettings, build_service


def main() -> None:
    settings = MemorySettings()
    app = create_app(build_service(settings))
    uvicorn.run(app, host=settings.host, port=settings.port)


if __name__ == "__main__":
    main()
