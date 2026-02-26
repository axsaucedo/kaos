

# Visual Map Fixes Plan

## Summary

Six issues to fix across 3 files. The root causes are: (a) agent-to-agent edges are never created from `agentNetwork.access`, (b) the eye toggle is blocked by the fingerprint stability check, and (c) cluster vertical positioning allows overlap.

## Changes

### 1. useVisualMapLayout.ts -- Add agent-to-agent edges + fix eye toggle

**Add agent-to-agent edges in `buildGraph`:**
- After the existing MCPServer edge loop inside the `agents.forEach`, add a new block that reads `agent.spec.agentNetwork?.access` 
- For each referenced agent name, create an edge from the current agent to the referenced agent (source = current agent, target = referenced agent)
- Style these edges with `hsl(var(--agent-color))` (purple), animated, label = "a2a"
- This will create the correct hierarchy: supervisor -> analysis-lead, supervisor -> research-lead, analysis-lead -> analyst-1, research-lead -> researcher-1, research-lead -> researcher-2

**Fix eye toggle (dimModelAPIEdges not updating edges):**
- The `useMemo` returns `changed: false` when fingerprint is unchanged, even though `dimModelAPIEdges` changed
- Split edge building from layout: always rebuild edges when `dimModelAPIEdges` changes, but only re-layout nodes when the structural fingerprint changes
- Add a separate `useMemo` for edges that depends on `dimModelAPIEdges` and always returns fresh edges
- Or simpler: include `dimModelAPIEdges` in the fingerprint so toggling it forces a rebuild

**Update `resourceFingerprint`:**
- Include `agent.spec.agentNetwork?.access` in the agent fingerprint string so that agent-to-agent relationship changes trigger re-layout

### 2. layout-engine.ts -- Fix cluster vertical overlap for disconnected components

**Problem:** `columnYOffset` is tracked per-column. Two clusters that don't share any columns can be placed at the same Y, causing visual overlap.

**Fix:** Track a single `globalYOffset` that advances after each cluster. All clusters start at `max(globalYOffset, max of all column offsets)`. This ensures disconnected components never share the same vertical band.

**Agent multi-column already works in the engine** -- the `computeAgentDepths` BFS correctly assigns depths. The reason it shows only one column currently is that there are no agent-to-agent edges being fed in (fix 1 above solves this).

### 3. DynamicEdge.tsx -- Already correct (step paths with dynamic anchors)

No changes needed. The `getSmoothStepPath` with `bestAnchors` already provides square lines with 4-point dynamic anchor selection.

---

## Technical Details

### Agent-to-agent edge creation (in buildGraph)

```text
agent.spec.agentNetwork?.access?.forEach((targetAgentName) => {
  const targetId = nodeId('Agent', agent.metadata.namespace, targetAgentName);
  edges.push({
    id: `edge-a2a-${agent.metadata.name}-${targetAgentName}`,
    source: agentId,
    target: targetId,
    type: 'dynamic',
    animated: true,
    label: 'a2a',
    style: { stroke: 'hsl(var(--agent-color))', strokeWidth: 2 },
    markerEnd: { type: MarkerType.ArrowClosed, color: 'hsl(var(--agent-color))' },
    ...
  });
});
```

### Eye toggle fix

Change the `useMemo` to always regenerate edges but only re-layout when structural fingerprint changes:

```text
// Structural fingerprint (excludes dimModelAPIEdges)
const structuralFP = resourceFingerprint(modelAPIs, mcpServers, agents);
const structurallyChanged = structuralFP !== prevFingerprint.current;

// Always rebuild edges (they depend on dimModelAPIEdges)
const { nodes: graphNodes, edges } = buildGraph(..., dimModelAPIEdges);

// Only re-layout if structure changed
if (structurallyChanged || !hasInitialized.current) {
  layoutedNodes = computeLayout(graphNodes, edges, lockedNodeIds);
  prevFingerprint.current = structuralFP;
}

return { initialNodes: layoutedNodes, initialEdges: edges, changed: structurallyChanged };
```

### Cluster overlap fix (layout-engine.ts)

Replace per-column Y tracking with a global row approach:

```text
let globalY = 0;

clusters.forEach((cluster) => {
  // All nodes in this cluster start at globalY
  clusterByCol.forEach((colNodes, col) => {
    colNodes.forEach((node, i) => {
      positioned.set(node.id, {
        x: colX(col),
        y: globalY + i * (NODE_HEIGHT + nodeSep),
      });
    });
  });

  // Advance globalY by the tallest column in this cluster + gap
  globalY += maxClusterHeight + clusterGap;
});
```

### Files to update

1. `src/components/dashboard/visual-map/useVisualMapLayout.ts` -- agent-to-agent edges, eye toggle fix, fingerprint update
2. `src/components/dashboard/visual-map/layout-engine.ts` -- global Y offset for non-overlapping clusters
3. `.github/instructions/components.instructions.md` -- document agent-to-agent edge source

