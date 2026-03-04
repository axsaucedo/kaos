"""A2A protocol module: TaskManager, JSON-RPC dispatcher, and route setup.

Provides:
- TaskManager: Orchestrates task lifecycle (submit, execute, cancel) wrapping TaskStore
- JSON-RPC 2.0 models and error codes
- setup_a2a_routes(): Mounts A2A endpoints on a FastAPI app
"""

import asyncio
import logging
from typing import Dict, Any, Optional, Union, Callable, AsyncIterator, TYPE_CHECKING

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

if TYPE_CHECKING:
    from pais.taskstore import TaskStore, Task

logger = logging.getLogger(__name__)


# --- JSON-RPC 2.0 Models ---


class JsonRpcRequest(BaseModel):
    """JSON-RPC 2.0 request envelope."""

    jsonrpc: str = "2.0"
    method: str
    params: Optional[Dict[str, Any]] = None
    id: Optional[Union[str, int]] = None


class JsonRpcError(BaseModel):
    """JSON-RPC 2.0 error object."""

    code: int
    message: str
    data: Optional[Any] = None


class JsonRpcResponse(BaseModel):
    """JSON-RPC 2.0 response envelope."""

    jsonrpc: str = "2.0"
    result: Optional[Any] = None
    error: Optional[JsonRpcError] = None
    id: Optional[Union[str, int]] = None

    def to_dict(self) -> dict:
        d: dict = {"jsonrpc": self.jsonrpc, "id": self.id}
        if self.error is not None:
            d["error"] = self.error.model_dump()
        else:
            d["result"] = self.result
        return d


# JSON-RPC error codes
JSONRPC_PARSE_ERROR = -32700
JSONRPC_INVALID_REQUEST = -32600
JSONRPC_METHOD_NOT_FOUND = -32601
JSONRPC_INVALID_PARAMS = -32602
JSONRPC_INTERNAL_ERROR = -32603
JSONRPC_TASK_NOT_FOUND = -32001


# Type alias for the process callback used by TaskManager
ProcessFn = Callable[..., AsyncIterator[str]]


class TaskManager:
    """Orchestrates A2A task lifecycle: submit, execute, cancel.

    Wraps a TaskStore (pure storage) with execution logic and asyncio task tracking.
    The process_fn callback is called to actually process messages (typically AgentServer._process_message).
    """

    def __init__(self, task_store: "TaskStore", process_fn: ProcessFn):
        self._task_store = task_store
        self._process_fn = process_fn
        self._running_tasks: Dict[str, "asyncio.Task[None]"] = {}

    @property
    def task_store(self) -> "TaskStore":
        return self._task_store

    async def submit_task(self, input_message: str, session_id: Optional[str] = None) -> "Task":
        """Create a task and spawn async execution. Returns the task in submitted state."""
        task = await self._task_store.create_task(
            session_id=session_id,
            input_message=input_message,
        )
        asyncio_task = asyncio.create_task(self._execute_task(task.id, input_message))
        self._running_tasks[task.id] = asyncio_task
        asyncio_task.add_done_callback(lambda _: self._running_tasks.pop(task.id, None))
        logger.info(f"Submitted task {task.id} for session {task.session_id}")
        return task

    async def _execute_task(self, task_id: str, input_message: str) -> None:
        """Execute a task asynchronously using the process callback."""
        from pais.taskstore import TaskState

        task = await self._task_store.get_task(task_id)
        if not task:
            logger.error(f"Task {task_id} not found for execution")
            return

        updated = await self._task_store.update_task_state(task_id, TaskState.WORKING, "Processing")
        if not updated:
            logger.error(f"Failed to transition task {task_id} to working")
            return

        try:
            response_content = ""
            async for chunk in self._process_fn(
                input_message, session_id=task.session_id, stream=False
            ):
                response_content += chunk

            await self._task_store.set_task_output(task_id, response_content)
            await self._task_store.update_task_state(task_id, TaskState.COMPLETED, "Done")
            logger.info(f"Task {task_id} completed")

        except asyncio.CancelledError:
            await self._task_store.update_task_state(task_id, TaskState.CANCELED, "Canceled")
            logger.info(f"Task {task_id} canceled")

        except Exception as e:
            logger.error(f"Task {task_id} failed: {e}")
            await self._task_store.update_task_state(task_id, TaskState.FAILED, str(e))

    async def cancel_task(self, task_id: str) -> bool:
        """Cancel a running task. Returns True if cancellation was initiated."""
        result = await self._task_store.cancel_task(task_id)
        if not result:
            return False

        asyncio_task = self._running_tasks.get(task_id)
        if asyncio_task and not asyncio_task.done():
            asyncio_task.cancel()
        return True

    async def get_task(self, task_id: str) -> Optional["Task"]:
        """Retrieve a task by ID."""
        return await self._task_store.get_task(task_id)

    async def list_tasks(self, session_id: Optional[str] = None):
        """List tasks, optionally filtered by session."""
        return await self._task_store.list_tasks(session_id)

    async def shutdown(self) -> None:
        """Cancel all running tasks and close the task store."""
        for task_id, asyncio_task in list(self._running_tasks.items()):
            if not asyncio_task.done():
                asyncio_task.cancel()
                logger.debug(f"Canceled running task {task_id} on shutdown")
        await self._task_store.close()


# --- JSON-RPC Dispatcher ---


async def _handle_jsonrpc(request: Request, task_manager: TaskManager) -> JSONResponse:
    """Dispatch JSON-RPC 2.0 requests for A2A task methods."""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(
            JsonRpcResponse(
                error=JsonRpcError(code=JSONRPC_PARSE_ERROR, message="Parse error"),
            ).to_dict()
        )

    try:
        rpc_req = JsonRpcRequest(**body)
    except Exception:
        return JSONResponse(
            JsonRpcResponse(
                error=JsonRpcError(
                    code=JSONRPC_INVALID_REQUEST, message="Invalid JSON-RPC request"
                ),
            ).to_dict()
        )

    method = rpc_req.method
    params = rpc_req.params or {}
    rpc_id = rpc_req.id

    if method == "tasks/send":
        return await _jsonrpc_tasks_send(task_manager, params, rpc_id)
    elif method == "tasks/get":
        return await _jsonrpc_tasks_get(task_manager, params, rpc_id)
    elif method == "tasks/cancel":
        return await _jsonrpc_tasks_cancel(task_manager, params, rpc_id)
    else:
        return JSONResponse(
            JsonRpcResponse(
                id=rpc_id,
                error=JsonRpcError(
                    code=JSONRPC_METHOD_NOT_FOUND,
                    message=f"Method not found: {method}",
                ),
            ).to_dict()
        )


async def _jsonrpc_tasks_send(
    task_manager: TaskManager,
    params: Dict[str, Any],
    rpc_id: Optional[Union[str, int]],
) -> JSONResponse:
    """Handle tasks/send: create and submit a task."""
    message = params.get("message")
    if not message:
        return JSONResponse(
            JsonRpcResponse(
                id=rpc_id,
                error=JsonRpcError(
                    code=JSONRPC_INVALID_PARAMS,
                    message="Missing required 'message' parameter",
                ),
            ).to_dict()
        )

    parts = message.get("parts", [])
    text_parts = [p.get("text", "") for p in parts if p.get("type") == "text"]
    input_text = " ".join(text_parts) if text_parts else message.get("text", "")

    if not input_text:
        return JSONResponse(
            JsonRpcResponse(
                id=rpc_id,
                error=JsonRpcError(
                    code=JSONRPC_INVALID_PARAMS,
                    message="Message must contain text content",
                ),
            ).to_dict()
        )

    session_id = params.get("sessionId")
    task = await task_manager.submit_task(input_text, session_id=session_id)

    return JSONResponse(JsonRpcResponse(id=rpc_id, result=task.to_dict()).to_dict())


async def _jsonrpc_tasks_get(
    task_manager: TaskManager,
    params: Dict[str, Any],
    rpc_id: Optional[Union[str, int]],
) -> JSONResponse:
    """Handle tasks/get: retrieve task status."""
    task_id = params.get("id")
    if not task_id:
        return JSONResponse(
            JsonRpcResponse(
                id=rpc_id,
                error=JsonRpcError(
                    code=JSONRPC_INVALID_PARAMS,
                    message="Missing required 'id' parameter",
                ),
            ).to_dict()
        )

    task = await task_manager.get_task(task_id)
    if not task:
        return JSONResponse(
            JsonRpcResponse(
                id=rpc_id,
                error=JsonRpcError(
                    code=JSONRPC_TASK_NOT_FOUND,
                    message=f"Task not found: {task_id}",
                ),
            ).to_dict()
        )

    return JSONResponse(JsonRpcResponse(id=rpc_id, result=task.to_dict()).to_dict())


async def _jsonrpc_tasks_cancel(
    task_manager: TaskManager,
    params: Dict[str, Any],
    rpc_id: Optional[Union[str, int]],
) -> JSONResponse:
    """Handle tasks/cancel: cancel a running task."""
    task_id = params.get("id")
    if not task_id:
        return JSONResponse(
            JsonRpcResponse(
                id=rpc_id,
                error=JsonRpcError(
                    code=JSONRPC_INVALID_PARAMS,
                    message="Missing required 'id' parameter",
                ),
            ).to_dict()
        )

    canceled = await task_manager.cancel_task(task_id)
    if not canceled:
        task = await task_manager.get_task(task_id)
        if not task:
            return JSONResponse(
                JsonRpcResponse(
                    id=rpc_id,
                    error=JsonRpcError(
                        code=JSONRPC_TASK_NOT_FOUND,
                        message=f"Task not found: {task_id}",
                    ),
                ).to_dict()
            )
        # Task exists but already terminal
        return JSONResponse(JsonRpcResponse(id=rpc_id, result=task.to_dict()).to_dict())

    task = await task_manager.get_task(task_id)
    return JSONResponse(
        JsonRpcResponse(id=rpc_id, result=task.to_dict() if task else None).to_dict()
    )


def setup_a2a_routes(app: FastAPI, task_manager: TaskManager) -> None:
    """Mount A2A JSON-RPC endpoint on a FastAPI app."""

    @app.post("/")
    async def jsonrpc_endpoint(request: Request):
        """A2A JSON-RPC 2.0 endpoint for task lifecycle management."""
        return await _handle_jsonrpc(request, task_manager)
