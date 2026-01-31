"""
Mock Model Server for deterministic testing.

Provides a simple FastAPI server that returns mock_response from request body,
enabling deterministic testing of agentic loops without needing a real LLM.
"""

import json
import time
import uuid
import logging
from typing import Dict, Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
import uvicorn

logger = logging.getLogger(__name__)


def create_mock_model_app() -> FastAPI:
    """Create a mock model server app."""
    app = FastAPI(title="Mock Model Server")

    @app.get("/health")
    async def health():
        return {"status": "healthy"}

    @app.get("/v1/models")
    async def models():
        return {"data": [{"id": "mock-model"}]}

    @app.post("/v1/chat/completions")
    async def chat_completions(request: Request):
        body = await request.json()

        # Get mock_response from request, default to simple response
        mock_response = body.get("mock_response", "This is a mock response.")
        model = body.get("model", "mock-model")
        stream = body.get("stream", False)

        if stream:
            return await _stream_response(mock_response, model)
        else:
            return _complete_response(mock_response, model)

    return app


def _complete_response(content: str, model: str) -> JSONResponse:
    """Generate non-streaming completion response."""
    return JSONResponse(
        {
            "id": f"chatcmpl-{uuid.uuid4().hex[:8]}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": len(content.split()),
                "total_tokens": 10 + len(content.split()),
            },
        }
    )


async def _stream_response(content: str, model: str) -> StreamingResponse:
    """Generate streaming completion response."""

    async def generate():
        chat_id = f"chatcmpl-{uuid.uuid4().hex[:8]}"
        created = int(time.time())

        # Stream content word by word
        words = content.split()
        for i, word in enumerate(words):
            chunk = {
                "id": chat_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "delta": {"content": word + (" " if i < len(words) - 1 else "")},
                        "finish_reason": None,
                    }
                ],
            }
            yield f"data: {json.dumps(chunk)}\n\n"

        # Final chunk
        final = {
            "id": chat_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": model,
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
        }
        yield f"data: {json.dumps(final)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


class MockModelServer:
    """Manager for mock model server process."""

    def __init__(self, port: int = 19000):
        self.port = port
        self.url = f"http://localhost:{port}"
        self.process = None

    def start(self, timeout: int = 10) -> bool:
        """Start the mock server in a subprocess."""
        import subprocess
        import os
        from pathlib import Path
        import httpx

        logger.info(f"Starting mock model server on port {self.port}")

        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"

        repo_root = Path(__file__).parent.parent

        self.process = subprocess.Popen(
            [
                "python",
                "-c",
                f"""
import uvicorn
from tests.mock_model_server import create_mock_model_app
app = create_mock_model_app()
uvicorn.run(app, host='0.0.0.0', port={self.port}, log_level='warning')
""",
            ],
            cwd=str(repo_root),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        # Wait for readiness
        import time

        start = time.time()
        while time.time() - start < timeout:
            try:
                resp = httpx.get(f"{self.url}/health", timeout=1.0)
                if resp.status_code == 200:
                    logger.info(f"Mock model server ready at {self.url}")
                    return True
            except Exception:
                pass
            time.sleep(0.3)

        self.stop()
        return False

    def stop(self):
        """Stop the mock server."""
        if self.process:
            logger.info("Stopping mock model server")
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except Exception:
                self.process.kill()


# For direct running
if __name__ == "__main__":
    app = create_mock_model_app()
    uvicorn.run(app, host="0.0.0.0", port=19000)
