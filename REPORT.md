# OTEL Logging Correlation Analysis

## Executive Summary

This report analyzes the current implementation of logging for OpenTelemetry (OTEL) trace correlation in KAOS, specifically examining:
1. Whether `logger.debug` statements are appropriate for OTEL correlation
2. Whether memory events should replace or supplement debug logs
3. Whether exceptions are properly logged with `logger.error` for correlation
4. Whether log statements are correctly ordered relative to span lifecycle

**Key Findings:**
- ~~Current `logger.debug` for failures is **problematic**~~ → Fixed: now uses `logger.error`
- Memory events and logs serve **different purposes** - both should be retained
- ~~Several exception paths **lack `logger.error`** calls~~ → Fixed: added `logger.error`
- ~~Log statements were placed **after** span ends~~ → Fixed: logs now precede `span_failure`

---

## Issue 1: Debug Logging in Exception Paths (FIXED)

**Problem:** The implementation used `logger.debug` for failures:

```python
# BEFORE (problematic)
except Exception as e:
    failed = True
    self._otel.span_failure(e)
    logger.debug(f"Model call failed: ...")  # ❌ DEBUG level, invisible at INFO
    raise
```

**Solution:** Changed to `logger.error`:

```python
# AFTER (fixed)
except Exception as e:
    failed = True
    logger.error(f"Model call failed: ...")  # ✅ ERROR level, always visible
    self._otel.span_failure(e)
    raise
```

---

## Issue 2: Log/Span Ordering (FIXED)

**Problem:** Logs were emitted AFTER `span_failure()` which detaches the context:

```python
# BEFORE (problematic)
except Exception as e:
    self._otel.span_failure(e)  # ← Context detached here
    logger.error(...)           # ← Log has NO trace correlation!
```

The `span_failure()` method calls `otel_context.detach(state.token)`, removing the span from the current context. Any logs after this point lose their trace_id/span_id correlation.

**Solution:** Reordered to log BEFORE span ends:

```python
# AFTER (fixed)
except Exception as e:
    logger.error(...)           # ✅ Log while span is active
    self._otel.span_failure(e)  # ← Context detached after log
```

Similarly for span_begin - logs should come AFTER span starts:

```python
# BEFORE (problematic)
logger.debug(f"Executing tool: {tool_name}")  # ← No span context yet
self._otel.span_begin(f"tool.{tool_name}")

# AFTER (fixed)
self._otel.span_begin(f"tool.{tool_name}")    # ← Span starts
logger.debug(f"Executing tool: {tool_name}")  # ✅ Log with span context
```

**Affected Locations (all fixed):**
| Method | Issue | Fix |
|--------|-------|-----|
| `_call_model` | logger.error after span_failure | Reordered |
| `_execute_tool` | logger.debug before span_begin, logger.error after span_failure | Reordered both |
| `_execute_delegation` | logger.debug before span_begin, logger.error after span_failure | Reordered both |
| `process_message` | logger.error after span_failure | Reordered |

---

## Issue 3: Memory Events vs Debug Logs

**Analysis:** These serve different purposes and should both be retained.

| Aspect | Memory Events | Debug Logs |
|--------|--------------|------------|
| **Purpose** | Agent working memory for context | Observability output |
| **Visibility** | Internal (agent use) | External (SigNoz, logs) |
| **Query-ability** | Limited (in-memory) | Searchable in log systems |
| **Trace Correlation** | Via metadata field | Via log format with trace_id |

**Recommendation:** Keep both - no changes needed.

---

## Correct Log/Span Ordering Pattern

```python
# Correct pattern for traced operations:

self._otel.span_begin("operation.name")       # 1. Start span (attaches context)
logger.debug("Starting operation...")          # 2. Log with span context

failed = False
try:
    result = do_work()
    logger.debug("Operation succeeded")        # 3. Success log (still in span)
    return result
except Exception as e:
    failed = True
    logger.error(f"Operation failed: {e}")     # 4. Error log (still in span)
    self._otel.span_failure(e)                 # 5. End span with error
    raise
finally:
    if not failed:
        self._otel.span_success()              # 6. End span with success
```

**Key Rule:** All logs must occur BETWEEN `span_begin` and `span_success/span_failure`.

---

## Validation Checklist

- [x] `logger.error` used for all failure paths
- [x] Logs occur BEFORE `span_failure()` (while context active)
- [x] Logs occur AFTER `span_begin()` (after context attached)
- [x] Memory events still include trace context
- [x] All unit tests pass
- [x] Linting passes
