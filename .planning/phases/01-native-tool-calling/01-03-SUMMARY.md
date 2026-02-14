---
phase: 01-native-tool-calling
plan: 03
subsystem: agent
tags: [agent, dual-path, tool-calling, native, function-calling, dispatch]

# Dependency graph
requires:
  - 01-01 (ToolCall/ModelResponse dataclasses, process_message tools param)
provides:
  - Dual-path agentic loop (native vs text mode dispatch)
  - _get_tools_for_api() converting MCP tools + sub-agents to OpenAI format
  - _is_delegation_call() identifying delegate_to_<name> pseudo-tools
  - function_calling parameter on Agent class
  - System prompt omits tool schemas in native mode
affects: [01-04, 01-05]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Native path uses role:tool messages with tool_call_id for OpenAI-compatible conversation history"
    - "Text path preserved unchanged for backward compatibility"
    - "Sub-agents registered as delegate_to_<name> pseudo-tools with {task: string} schema"
    - "tools kwarg conditionally passed to process_message to preserve mock subclass compat"

key-files:
  created: []
  modified:
    - data-plane/kaos-framework/agent/client.py

key-decisions:
  - "Default function_calling='text' for backward compatibility — existing tests all use text mode"
  - "tools kwarg only passed to process_message when non-None, avoiding TypeError on mock subclasses that lack tools param"
  - "_call_model returns Union[str, ModelResponse] to handle both mock and real API paths"

patterns-established:
  - "Native mode: ModelResponse.tool_calls → execute → role:tool messages → continue loop"
  - "Text mode: response.content → _parse_action() → execute → role:user messages (unchanged)"
  - "delegate_to_<name> pseudo-tool pattern for sub-agent registration in OpenAI tools format"

# Metrics
duration: 5min
completed: 2026-02-14
---

# Phase 1 Plan 3: Agent Dual-Path Dispatch Summary

**Dual-path dispatch in Agent._agentic_loop — native mode reads tool_calls from ModelResponse with OpenAI-format conversation history, text mode uses existing _parse_action unchanged**

## Performance

- **Duration:** 5 min
- **Started:** 2026-02-14T12:48:25Z
- **Completed:** 2026-02-14T12:53:27Z
- **Tasks:** 3
- **Files modified:** 1

## Accomplishments
- Added `function_calling` parameter to Agent.__init__ (default "text" for backward compat)
- Added `_get_tools_for_api()` converting MCP tools and sub-agents to OpenAI-format tool definitions
- Added `_is_delegation_call()` helper to identify `delegate_to_<name>` pseudo-tools and extract agent names
- Implemented dual-path dispatch in `_agentic_loop`: native path reads `ModelResponse.tool_calls`, text path uses `_parse_action`
- Native path sends proper `role:tool` messages with `tool_call_id` for OpenAI-compatible conversation history
- Native path handles both tool calls and delegation pseudo-tools
- Updated `_build_system_prompt()` to skip tool schema injection in native mode (schemas sent via API parameter)
- Updated `_call_model()` to accept optional `tools` parameter and return `Union[str, ModelResponse]`
- Phase 2 (final response) never sends tools parameter
- All 47 existing tests pass without modification

## Task Commits

Each task was committed atomically:

1. **Task 1: Add _get_tools_for_api and delegate_to pseudo-tool registration** - `70e70ee` (feat)
2. **Task 2: Implement dual-path dispatch in _agentic_loop** - `08024b4` (feat)
3. **Task 3: Skip tool schemas in system prompt for native mode** - `bae8a90` (feat)

## Files Created/Modified
- `data-plane/kaos-framework/agent/client.py` — Added function_calling param, _get_tools_for_api(), _is_delegation_call(), dual-path dispatch in _agentic_loop, conditional system prompt, updated _call_model return type

## Decisions Made
- Default `function_calling="text"` for full backward compatibility — all existing tests create Agents without this param and continue working
- `tools` kwarg only passed to `process_message` when non-None to avoid `TypeError` on mock subclasses that don't accept `tools` parameter (mock updates deferred to Plan 05)
- `_call_model` returns `Union[str, ModelResponse]` since mock path returns `str` and real API returns `ModelResponse`

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Conditionally pass tools kwarg to process_message**
- **Found during:** Task 2 (test validation)
- **Issue:** Mock `process_message` in test files doesn't accept `tools` keyword — passing `tools=None` causes `TypeError: got an unexpected keyword argument 'tools'`
- **Fix:** Only include `tools` in kwargs dict when non-None; pass via `**kwargs` unpacking
- **Files modified:** data-plane/kaos-framework/agent/client.py
- **Verification:** All 47 tests pass
- **Committed in:** `08024b4` (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (1 blocking)
**Impact on plan:** Minimal — conditional kwarg passing is a clean pattern. Plan 05 will update test mocks to accept `tools` parameter.

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Dual-path dispatch ready for Plan 04 (streaming ModelResponse) and Plan 05 (test updates)
- Native mode fully functional but requires real API endpoint (not mocks) to exercise
- Text mode fully backward compatible

---
*Phase: 01-native-tool-calling*
*Completed: 2026-02-14*

## Self-Check: PASSED

- [x] data-plane/kaos-framework/agent/client.py exists
- [x] .planning/phases/01-native-tool-calling/01-03-SUMMARY.md exists
- [x] Commit 70e70ee found in git log
- [x] Commit 08024b4 found in git log
- [x] Commit bae8a90 found in git log
