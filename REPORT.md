# KAOS Development Report

## Overview

This report covers the comprehensive A2A protocol, autonomous execution, TaskEvent simplification, and frontend extension work across multiple PRs.

---

## PR #114: KAOS-UI Frontend — Autonomous & A2A Support

**Branch:** `feat/ui-autonomous-a2a`  
**Status:** ✅ Complete — All tasks implemented, tested, committed

### Phase 1: Core Frontend Features (Tasks 1-9)

| # | Task | Status | Commit |
|---|------|--------|--------|
| 1 | Sync TypeScript types with Go CRD | ✅ Done | `4a6b1a8` |
| 2 | A2A proxy client methods | ✅ Done | `4dc10c1` |
| 3 | Autonomous badges & indicators | ✅ Done | `f91d0c4` |
| 4 | Autonomous config in create/edit dialogs | ✅ Done | `da6b8a7` |
| 5 | A2A debug screen | ✅ Done | `eb6dfbf` |
| 6 | Enhanced memory screen | ✅ Done | `308e690` |
| 7 | Fix sendA2AMessage signature | ✅ Done | `590bcef` |
| 8 | Playwright E2E tests | ✅ Done | `f6cf630` |
| 9 | Documentation & REPORT.md | ✅ Done | `fbba308` |

### Phase 2: UI Fixes, Enhanced Testing & CLI Sample (Tasks 1-8)

| # | Task | Status | Commit | Details |
|---|------|--------|--------|---------|
| 1 | Fix memory tab UX | ✅ Done | `60c67a8` | Conversation default view, auto-scroll-to-bottom, diff-based live mode (no jitter) |
| 2 | Fix A2A tab auto-switch | ✅ Done | `3481458` | Clicking task history auto-switches to Get/Cancel tab with task ID populated |
| 3 | Fix A2A mode label | ✅ Done | `e2f622b` | "Autonomous" → "Async Task" in mode dropdown |
| 4 | Remove visual map edge labels | ✅ Done | `93a02ab` | Removed "model"/"a2a"/"tools" text from edge connectors |
| 5 | Add autonomous CLI sample | ✅ Done | `200b824` | Sample 6: kubernetes MCP + report tools monitoring agent |
| 6 | Enhance Playwright tests | ✅ Done | `96f91d9` | Rewrote shallow tests → real multi-step workflow tests |
| 7 | Manual testing + bug fix | ✅ Done | `3f21130` | Found & fixed missing autonomous section in AgentOverview |
| 8 | Update REPORT.md | ✅ Done | `06ccab5` | Comprehensive report |

### Phase 3: Autonomous Sample Deployment & Playwright Stability (Tasks 1-4)

| # | Task | Status | Commit | Details |
|---|------|--------|--------|---------|
| 1 | Deploy autonomous monitoring sample | ✅ Done | — | Deployed to kaos-hierarchy with zalando-modelapi |
| 2 | Manual test autonomous sample | ✅ Done | — | Verified tool calls, health reports, interactive chat |
| 3 | Fix all broken Playwright tests | ✅ Done | `9b5aacd` | Fixed 12 pre-existing failures → 125/125 pass (2 skipped) |
| 4 | Debug guide & REPORT update | ✅ Done | This commit | Setup/debugging guide included below |

### Phase 3: Autonomous Sample Testing Results

**Deployed resources** (kaos-hierarchy namespace):
- Agent: `cluster-monitor` — autonomous monitoring with 120s interval
- MCPServers: `monitor-k8s-mcp` (kubernetes runtime), `monitor-report-mcp` (python-string)
- Model: `gemini/gemini-flash-latest` via `zalando-modelapi`
- ClusterRole: Cross-namespace read access (kaos-hierarchy, kaos-autonomous, envoy-gateway-system, kube-system, kaos-operator)

**Manual testing results:**
| Test | Result | Details |
|------|--------|---------|
| Autonomous task submission | ✅ PASS | Task `task_52103afe7275` submitted on startup |
| Tool calls (pods_list, events_list, etc.) | ✅ PASS | 23 memory events, 6+ different tool types used |
| Health report generation | ✅ PASS | Detailed reports: 46 pods checked, 3 unhealthy identified |
| Interactive chat via /v1/chat/completions | ✅ PASS | Agent correctly listed 8 agents in namespace |
| Budget enforcement (120s interval) | ✅ PASS | Autonomous loop runs within configured budgets |

### Phase 3: Playwright Fix Details

**Root causes found and fixed:**

1. **Duplicate edit dialogs (visual-map bug)** — Both `Index.tsx` and `visual-map/index.tsx` rendered edit dialogs from shared state. Since visual map is always-mounted, clicking edit opened TWO identical dialogs. Fix: removed duplicate dialog rendering from visual-map (Index.tsx already handles it).

2. **Memory mock tests (7 failures)** — Default view changed to 'conversation' but tests asserted badge content only visible in 'raw' view. Fix: added `page.locator('[data-testid="memory-view-raw"]').click()` before assertions.

3. **A2A send test (1 failure)** — Test waited for `[data-testid="a2a-task-detail"]` after sending, but that element only exists in the "Get/Cancel Task" tab. Fix: added route mocking + corrected flow (wait for history entry → click → auto-switches to tasks tab).

4. **CRUD UPDATE button click (2 failures)** — CSS selector `button[type="submit"]` failed silently within dialog's ScrollArea. Fix: changed to `getByRole('button', { name: /Update ModelAPI/i })` which handles scroll/viewport correctly.

**Final Playwright results:** 125 passed, 0 failed, 2 skipped

### Autonomous Monitoring Sample — Setup & Debugging Guide

#### Deploying the Sample

```bash
# 1. Ensure KIND cluster is running with KAOS installed
kaos system install --gateway-enabled --metallb-enabled --wait

# 2. Deploy the autonomous monitoring sample
cd operator/config/samples
kubectl apply -f 6-autonomous-monitor.yaml -n kaos-hierarchy

# 3. Wait for resources to be ready
kubectl wait --for=condition=Ready agent/cluster-monitor -n kaos-hierarchy --timeout=120s
kubectl wait --for=condition=Ready mcpserver/monitor-k8s-mcp -n kaos-hierarchy --timeout=120s
kubectl wait --for=condition=Ready mcpserver/monitor-report-mcp -n kaos-hierarchy --timeout=120s
```

#### Checking Agent Status

```bash
# Check agent pod logs
kubectl logs -n kaos-hierarchy -l app=agent-cluster-monitor --tail=50

# Check autonomous task submission
kubectl logs -n kaos-hierarchy -l app=agent-cluster-monitor | grep -i "autonomous\|task"

# View memory events (via port-forward)
kubectl port-forward -n kaos-hierarchy svc/agent-cluster-monitor 8000:8000
curl http://localhost:8000/memory/events?session_id=autonomous | jq '.events | length'
curl http://localhost:8000/memory/events?session_id=autonomous | jq '.events[-3:]'
```

#### Interacting with the Agent

```bash
# Interactive chat
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "List all agents in the cluster"}]}'

# A2A SendMessage
curl -X POST http://localhost:8000/ \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc": "2.0", "method": "SendMessage", "params": {"message": {"role": "user", "parts": [{"type": "text", "text": "Generate a health report"}]}}, "id": "1"}'

# Using kaos CLI
kaos agent a2a send cluster-monitor -n kaos-hierarchy -m "Check pod status"
kaos agent a2a card cluster-monitor -n kaos-hierarchy
```

#### macOS/KIND Port-Forward Setup

```bash
# Gateway access (MetalLB IPs not accessible from macOS host)
kubectl port-forward -n envoy-gateway-system svc/envoy-gateway 8888:80 &
export GATEWAY_URL=http://localhost:8888

# Direct agent access
kubectl port-forward -n kaos-hierarchy svc/agent-cluster-monitor 8000:8000 &

# UI proxy
kaos ui --no-browser  # Proxy at http://localhost:8010
```

#### Troubleshooting

| Issue | Solution |
|-------|----------|
| Agent pod CrashLoopBackOff | Check ModelAPI secret: `kubectl get secret -n kaos-hierarchy` |
| No tool calls in logs | Verify MCP servers are Ready: `kubectl get mcpserver -n kaos-hierarchy` |
| Empty memory events | Check autonomous goal is set: `kubectl get agent cluster-monitor -o yaml` |
| 503 from Gateway | Wait for Gateway pods: `kubectl wait -n envoy-gateway-system --for=condition=available deploy --all` |
| 3.1 Visual map no edge labels | ✅ PASS | 22 nodes, 17 edges, 0 text labels |
| 4.1 Auto badge in agent list | ✅ PASS | test-auto-agent shows "Auto" badge |
| 4.2 Agent detail shows goal | ✅ PASS | Autonomous Execution section with goal, intervals, budgets |
| 4.3 Non-autonomous no badge | ✅ PASS | researcher-1 correctly has no Auto badge |
| 5.1 CLI samples list | ✅ PASS | 6-autonomous-monitor listed with correct description |

**Bug found during manual testing:**
- `AgentOverview.tsx` was missing the Autonomous Execution section (only `ResourceDetailDrawer.tsx` had it)
- Fixed in commit `3f21130`: Added Autonomous Execution card showing goal, interval, iteration runtime, and task budgets

### Playwright Test Results (Final)

**Unit tests:** 63/63 passed  
**Playwright tests:** 125/125 passed, 0 failed, 2 skipped  
All pre-existing failures fixed in Phase 3 (commit `9b5aacd`)

### Enhanced Playwright Tests Summary

**A2A Debug (`functional/agent-a2a.spec.ts`):**
- Send interactive message → verify task detail appears
- Send async task → verify mode badge and task status
- Send → history → auto-switch to Get/Cancel tab (multi-step workflow)
- Mode dropdown validation (Interactive vs Async Task)

**Memory Views (`functional/agent-memory-views.spec.ts`):**
- Default conversation view verification
- View switching (chat ↔ raw)
- Session filter functionality
- Live mode toggle
- Scroll-to-bottom behavior

**Autonomous Read (`read/agent-autonomous.spec.ts`):**
- Combined autonomous badge validation (list + detail)
- Detail navigation with goal and A2A tab availability
- Edge label regression guard (no text labels on visual map)

---

## Previous PRs (Summary)

### PR #104: A2A Protocol & TaskManager (Merged)
- Implemented A2A JSON-RPC 2.0 endpoint (SendMessage, GetTask, CancelTask)
- TaskManager ABC with LocalTaskManager and NullTaskManager
- A2A-compliant agent cards
- RemoteAgent with A2A protocol support

### PR #105: A2A Phase 2 Refinements (Merged)
- Extracted a2a.py from server.py
- Synchronous delegation via A2A
- DelegationToolset as Pydantic AI AbstractToolset
- OTel instrumentation for TaskManager

### PR #107: Autonomous Execution (Merged)
- Self-loop autonomous agent execution
- Budget enforcement (iterations, time, tool calls)
- CRD autonomous config
- Startup-activated and A2A-triggered modes

### PR #108: CRD Restructuring (Merged)
- Simplified autonomous config (boolean mode → goal-based activation)
- TaskConfig grouping
- CLI updates for autonomous commands

### PR #110: CLI Extensions & Documentation (Merged)
- `kaos agent a2a send` / `get` / `cancel` / `card` commands
- `kaos agent autonomous trigger` / `status` commands
- Autonomous monitoring sample
- Comprehensive documentation updates

### PR #112: TaskEvent Simplification (Merged)
- Removed redundant TaskEvent system
- Memory as single source of truth for execution history
- Simplified task status tracking

---

## Architecture Decisions

1. **A2A Protocol**: JSON-RPC 2.0 at root path, separate from `/v1/chat/completions`
2. **Autonomous modes**: Goal-based activation (goal present = autonomous enabled)
3. **Delegation**: DelegationToolset as AbstractToolset (same pattern as MCPServerStreamableHTTP)
4. **Memory over TaskEvents**: Single source of truth for execution history
5. **UI detail page**: Full-page route (`/agents/:ns/:name`) with tabs, not drawer
