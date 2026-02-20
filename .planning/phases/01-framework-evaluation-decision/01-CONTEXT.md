# Phase 1: Framework Evaluation & Decision - Context

**Gathered:** 2026-02-20
**Status:** Ready for planning

<domain>
## Phase Boundary

Complete a framework comparison matrix covering all 9 candidate frameworks (Pydantic AI, LangChain/LangGraph, CrewAI, Google ADK, AutoGen, Semantic Kernel, LlamaIndex, Haystack, DSPy) across 10 evaluation dimensions, produce a recommendation document with clear rationale, and define an adapter contract specifying required and optional interfaces for any framework integration. This phase produces documents only -- no code changes.

</domain>

<decisions>
## Implementation Decisions

### Comparison matrix format
- Hybrid format: numeric scores (1-10) per dimension AND narrative explanation per framework per dimension
- All 10 dimensions weighted equally -- raw totals decide ranking
- 10 dimensions: Provider Agnosticism, MCP, Memory, OTel, A2A, Extensibility, Maturity, Developer Experience, Ecosystem Size, License Risk
- Per-score confidence levels: each individual score tagged HIGH/MEDIUM/LOW based on evidence quality
- Layered document: executive summary at the top (decision-maker readable), full technical detail in the body (engineer readable)

### Recommendation depth
- Equal depth for all 9 frameworks -- no framework gets abbreviated treatment
- Google ADK evaluated objectively like the others, with a separate note documenting the team's rejection based on real experience
- Evidence standard: documentation-based (official docs + existing research files)
- Single unified document containing matrix, per-framework analysis, and final recommendation
- Single recommendation path -- no fallback strategy documented (deal with fallback if needed later)

### Adapter contract scope
- Comprehensive coverage: endpoints, env var mapping, memory interface, OTel interface, MCP interface, health checks, graceful shutdown, container lifecycle -- cover as much as possible
- Where full coverage isn't feasible, acknowledge gaps and note that adapters/extensions can fill them later
- Required core + optional extensions structure: core interfaces (endpoints, env vars, memory) are mandatory; extended capabilities (MCP server, A2A protocol) are optional
- Format: Markdown specification document (not OpenAPI or Python Protocols)
- Validation: manual review for now, automated compliance test suite deferred to a later phase when there's something to test against

### Evaluation methodology
- Documentation-based analysis only -- no hands-on prototyping in this phase
- Existing `.planning/research/` files are the primary source; supplement with official docs where needed (not re-verifying from scratch)
- No selective prototyping -- that happens in Phase 6+

### Claude's Discretion
- Internal document structure and section ordering
- Level of detail in narrative sections (as long as all 9 frameworks get equal treatment)
- How to present the executive summary visualization (table, ranked list, etc.)

</decisions>

<specifics>
## Specific Ideas

- The user emphasized that the adapter contract should be as comprehensive as possible but pragmatic -- acknowledge what can't be covered and point to adapters/extensions for those gaps
- ADK must be evaluated fairly despite being pre-rejected -- the matrix should show WHY it was rejected through objective scoring, not just assert the rejection

</specifics>

<deferred>
## Deferred Ideas

None -- discussion stayed within phase scope

</deferred>

---

*Phase: 01-framework-evaluation-decision*
*Context gathered: 2026-02-20*
