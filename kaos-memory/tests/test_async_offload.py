"""The async handlers must offload blocking store/Mem0 work to the bounded executor.

If a handler ran its synchronous recall directly on the event loop, a blocking call would
stall the loop and serialise requests. Driving two concurrent recalls whose bodies rendezvous
on a barrier proves the work runs in parallel on the KAOS-owned pool, off the loop.
"""

import asyncio
import threading

import httpx
import pytest
from httpx import ASGITransport

from kaos_memory.app import MemoryService, RecallResponse, create_app
from typing import cast

SCOPE = {"level": "user", "principal": "a"}


class _BarrierService:
    """A stand-in service whose recall blocks until ``n`` concurrent calls arrive."""

    def __init__(self, n: int) -> None:
        self.barrier = threading.Barrier(n, timeout=5)

    def recall(self, req) -> RecallResponse:
        self.barrier.wait()  # only returns once n callers are here simultaneously
        return RecallResponse()

    def readiness(self) -> dict:
        return {"ready": True, "stores": {}}


@pytest.mark.asyncio
async def test_recall_requests_run_concurrently_on_the_bounded_pool():
    service = _BarrierService(2)
    app = create_app(cast(MemoryService, service), request_concurrency=2)
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        body = {"scope": SCOPE, "query": "q"}
        r1, r2 = await asyncio.gather(
            client.post("/v1/recall", json=body),
            client.post("/v1/recall", json=body),
        )
    # Both only complete because the two handlers reached the barrier in parallel; a
    # loop-blocking handler would deadlock the barrier and surface an error instead.
    assert r1.status_code == 200
    assert r2.status_code == 200
