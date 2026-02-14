---
phase: 01-native-tool-calling
plan: 06
subsystem: testing
tags: [ginkgo, envtest, e2e, function-calling, ollama, smollm2]

# Dependency graph
requires:
  - phase: 01-native-tool-calling plan 02
    provides: FunctionCalling CRD field and FUNCTION_CALLING env var mapping in agent_controller.go
provides:
  - Operator integration tests verifying FunctionCalling CRD field → FUNCTION_CALLING env var mapping
  - E2E test configuration for text-based function calling with Ollama smollm2:135m
affects: [01-native-tool-calling]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Integration test pattern for CRD config → env var mapping using envtest"
    - "E2E tests explicitly set functionCalling mode per model capability"

key-files:
  created: []
  modified:
    - operator/controllers/integration/agent_test.go
    - operator/tests/e2e/conftest.py
    - operator/tests/e2e/test_agentic_loop_e2e.py
    - operator/tests/e2e/test_mcp_tools_e2e.py
    - operator/tests/e2e/test_multi_agent_e2e.py
    - data-plane/kaos-framework/tests/conftest.py

key-decisions:
  - "Integration tests use full envtest reconciliation path (not unit-testing constructEnvVars directly) since it's a method on AgentReconciler"
  - "E2E tests set functionCalling in CRD spec.config (operator E2E) and FUNCTION_CALLING env var (data-plane subprocess fixtures)"

patterns-established:
  - "FunctionCalling test pattern: create Agent CRD → reconcile → verify FUNCTION_CALLING env var on resulting Deployment"

# Metrics
duration: 4min
completed: 2026-02-14
---

# Phase 01 Plan 06: Operator & E2E Test Updates for FunctionCalling Summary

**Ginkgo integration tests for FunctionCalling CRD→env var pipeline, plus E2E text-mode config for Ollama smollm2:135m compatibility**

## Performance

- **Duration:** 4 min
- **Started:** 2026-02-14T13:02:27Z
- **Completed:** 2026-02-14T13:06:28Z
- **Tasks:** 2
- **Files modified:** 6

## Accomplishments
- 3 new Ginkgo integration tests verifying FunctionCalling CRD field maps to FUNCTION_CALLING env var (default→native, explicit text, explicit native)
- All 9 E2E Agent creation helpers updated to set `functionCalling: "text"` in CRD config dicts
- All 3 data-plane subprocess fixtures updated with `FUNCTION_CALLING=text` env var
- Full operator test suite passes (31 tests including 3 new ones)

## Task Commits

Each task was committed atomically:

1. **Task 1: Add operator integration tests for FunctionCalling field** - `2fc9527` (test)
2. **Task 2: Update E2E tests for text fallback mode** - `b4e151d` (fix)

## Files Created/Modified
- `operator/controllers/integration/agent_test.go` - 3 new Ginkgo test cases for FunctionCalling default/text/native values
- `operator/tests/e2e/conftest.py` - Added `functionCalling: "text"` to `create_agent_resource()` config
- `operator/tests/e2e/test_agentic_loop_e2e.py` - Added `functionCalling: "text"` to worker, coordinator, and nowait agent configs
- `operator/tests/e2e/test_mcp_tools_e2e.py` - Added `functionCalling: "text"` to `create_agent_with_mcp()` and multi-MCP agent inline spec
- `operator/tests/e2e/test_multi_agent_e2e.py` - Added `functionCalling: "text"` to worker-1, worker-2, and coordinator configs
- `data-plane/kaos-framework/tests/conftest.py` - Added `FUNCTION_CALLING=text` to agent_server, agent_server_no_mcp, and multi_agent_cluster fixtures

## Decisions Made
- Used full envtest integration path for testing (not unit-testing constructEnvVars directly) because it's a method on AgentReconciler, not a standalone function
- Set `functionCalling: "text"` in CRD spec.config for operator E2E tests (maps to env var via controller) and `FUNCTION_CALLING=text` directly in env dict for data-plane subprocess fixtures

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Test file location different from plan**
- **Found during:** Task 1
- **Issue:** Plan referenced `operator/controllers/agent_controller_test.go` but integration tests live in `operator/controllers/integration/agent_test.go`
- **Fix:** Added tests to the correct file following existing Ginkgo/envtest patterns
- **Files modified:** operator/controllers/integration/agent_test.go
- **Verification:** `make test-unit` passes all 31 tests
- **Committed in:** 2fc9527

**2. [Rule 3 - Blocking] E2E test files in different location than plan**
- **Found during:** Task 2
- **Issue:** Plan referenced `data-plane/kaos-framework/tests/test_agentic_loop_e2e.py` but E2E tests are at `operator/tests/e2e/`
- **Fix:** Updated files at correct locations in both `operator/tests/e2e/` and `data-plane/kaos-framework/tests/conftest.py`
- **Files modified:** 5 files across both directories
- **Verification:** All Python files compile cleanly
- **Committed in:** b4e151d

---

**Total deviations:** 2 auto-fixed (2 blocking - file path corrections)
**Impact on plan:** File locations differed from plan but all intended changes were applied correctly. No scope creep.

## Issues Encountered
None — tests passed on first run.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- All operator integration tests pass including new FunctionCalling tests
- E2E tests configured for text-mode compatibility with smollm2:135m
- Ready for plan 07 (if any) or phase completion

---
*Phase: 01-native-tool-calling*
*Completed: 2026-02-14*
