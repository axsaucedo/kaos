"""End-to-end two-identity propagation across agent hops (A -> B -> MCP).

Wires three instrumented apps together in-process via httpx ASGITransport and asserts,
using the real aib SDK, that:

* the user **subject** (principal + Authorization) is propagated unchanged across hops,
* the **actor** is overridden per hop (each agent authenticates as itself), and
* a request id is generated at the edge and stays stable down the chain.
"""

import aib
import httpx
import pytest
from fastapi import FastAPI, Request


def _record_app(actor, recorder, downstream=None, downstream_url=None):
    app = FastAPI()
    aib.instrument_fastapi(app, actor=actor, actor_token=f"{actor}#token")

    @app.get("/call")
    async def call(request: Request):
        recorder.update({k.lower(): v for k, v in request.headers.items()})
        if downstream is None:
            return {"leaf": True}
        resp = await downstream.get(downstream_url)
        return resp.json()

    return app


@pytest.mark.asyncio
async def test_two_identity_propagation_across_hops():
    aib.instrument_httpx()
    aib.ctx.replace({})

    seen_b = {}  # headers agent B received from agent A
    seen_c = {}  # headers the MCP leaf received from agent B

    leaf = _record_app("kaos://mcpserver/default/github", seen_c)
    client_c = httpx.AsyncClient(transport=httpx.ASGITransport(app=leaf), base_url="http://c")

    agent_b = _record_app("kaos://agent/default/B", seen_b, client_c, "http://c/call")
    client_b = httpx.AsyncClient(transport=httpx.ASGITransport(app=agent_b), base_url="http://b")

    agent_a = _record_app("kaos://agent/default/A", {}, client_b, "http://b/call")
    client_a = httpx.AsyncClient(transport=httpx.ASGITransport(app=agent_a), base_url="http://a")

    # Inbound user request to A: user subject only (no actor, no request id).
    await client_a.get(
        "http://a/call",
        headers={
            "authorization": "Bearer user-subject-alice",
            "x-principal": "keycloak://kaos/alice",
        },
    )

    # User subject is carried unchanged all the way to the leaf.
    assert seen_c["x-principal"] == "keycloak://kaos/alice"
    assert seen_c["authorization"] == "Bearer user-subject-alice"

    # Actor is each hop's own identity: A->B carries actor A, B->leaf carries actor B.
    assert seen_b["x-actor"] == "kaos://agent/default/A"
    assert seen_b["x-agent-authorization"] == "Bearer kaos://agent/default/A#token"
    assert seen_c["x-actor"] == "kaos://agent/default/B"
    assert seen_c["x-agent-authorization"] == "Bearer kaos://agent/default/B#token"

    # The decision would key on the actor (B), never the subject principal.
    assert seen_c["x-actor"] != seen_c["x-principal"]

    # A request id is generated at the edge and stays stable down the chain.
    assert seen_b["x-request-id"].startswith("req-")
    assert seen_b["x-request-id"] == seen_c["x-request-id"]

    for client in (client_a, client_b, client_c):
        await client.aclose()
