"""KAOS production-grade agent memory.

``kaos_memory`` is the one source of truth for KAOS memory: the wire contract,
the tiered storage engine and HTTP service, the service client, and an optional
Pydantic AI integration. It is packaged so consumers only pull what they use:

- the core install exposes the :mod:`kaos_memory.contract` schemas and the
  :class:`~kaos_memory.client.MemoryServiceClient` (Pydantic + httpx only);
- the ``service`` extra adds the storage engine and FastAPI service
  (:mod:`kaos_memory.app`, :mod:`kaos_memory.stores`, :mod:`kaos_memory.config`),
  which pull the heavy engine dependencies (Mem0, Chroma/pgvector, tiktoken);
- the ``pydantic-ai`` extra adds :mod:`kaos_memory.pydantic_ai` — message/turn
  adapters and a memory toolset for direct Pydantic AI integration.

Only the lightweight contract and client are imported eagerly here; the service
and Pydantic AI surfaces are imported from their submodules so importing this
package never drags in the engine or an agent framework.
"""

from kaos_memory.client import MemoryServiceClient
from kaos_memory.contract import (
    FailureMode,
    ForgetRequest,
    ForgetResponse,
    MediumTermContext,
    RecallRequest,
    RecallResponse,
    Scope,
    ScopeLevel,
    ShortTermContext,
    Turn,
    WriteRequest,
    WriteResponse,
    scope_key,
)

__version__ = "0.4.8.dev0"

__all__ = [
    "MemoryServiceClient",
    "Scope",
    "ScopeLevel",
    "scope_key",
    "FailureMode",
    "RecallRequest",
    "RecallResponse",
    "WriteRequest",
    "WriteResponse",
    "ForgetRequest",
    "ForgetResponse",
    "Turn",
    "ShortTermContext",
    "MediumTermContext",
]
