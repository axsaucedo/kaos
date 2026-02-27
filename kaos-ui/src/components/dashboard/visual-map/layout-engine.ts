import type { Node, Edge } from '@xyflow/react';

const NODE_WIDTH = 240;
const NODE_HEIGHT = 120;

export interface LayoutOptions {
  nodeSep?: number;
  rankSep?: number;
}

const DEFAULT_OPTIONS: LayoutOptions = {
  nodeSep: 80,
  rankSep: 300,
};

/**
 * Build an adjacency map from edges for clustering and depth analysis.
 */
function buildAdjacency(edges: Edge[]) {
  const forward = new Map<string, Set<string>>();
  const reverse = new Map<string, Set<string>>();
  edges.forEach((e) => {
    if (!forward.has(e.source)) forward.set(e.source, new Set());
    forward.get(e.source)!.add(e.target);
    if (!reverse.has(e.target)) reverse.set(e.target, new Set());
    reverse.get(e.target)!.add(e.source);
  });
  return { forward, reverse };
}

/**
 * Find connected clusters using union-find on edges.
 * Returns an array of sets, each containing connected node IDs.
 */
function findClusters(nodeIds: string[], edges: Edge[]): Set<string>[] {
  const parent = new Map<string, string>();
  nodeIds.forEach((id) => parent.set(id, id));

  function find(x: string): string {
    while (parent.get(x) !== x) {
      parent.set(x, parent.get(parent.get(x)!)!);
      x = parent.get(x)!;
    }
    return x;
  }

  function union(a: string, b: string) {
    const ra = find(a);
    const rb = find(b);
    if (ra !== rb) parent.set(ra, rb);
  }

  edges.forEach((e) => {
    if (parent.has(e.source) && parent.has(e.target)) {
      union(e.source, e.target);
    }
  });

  const clusters = new Map<string, Set<string>>();
  nodeIds.forEach((id) => {
    const root = find(id);
    if (!clusters.has(root)) clusters.set(root, new Set());
    clusters.get(root)!.add(id);
  });

  return Array.from(clusters.values());
}

/**
 * Compute agent dependency depth via BFS from agents with no agent dependencies.
 * Agents that depend on other agents get higher depth values → more columns.
 */
function computeAgentDepths(
  agentNodes: Node[],
  edges: Edge[],
): Map<string, number> {
  const agentIds = new Set(agentNodes.map((n) => n.id));
  // Only consider agent-to-agent edges
  const agentEdges = edges.filter((e) => agentIds.has(e.source) && agentIds.has(e.target));
  const { reverse } = buildAdjacency(agentEdges);

  const depths = new Map<string, number>();

  // BFS: start from agents with no incoming agent edges (depth 0)
  const queue: string[] = [];
  agentNodes.forEach((n) => {
    if (!reverse.has(n.id) || reverse.get(n.id)!.size === 0) {
      depths.set(n.id, 0);
      queue.push(n.id);
    }
  });

  // If all agents have incoming edges (cycle), just assign depth 0 to all
  if (queue.length === 0) {
    agentNodes.forEach((n) => depths.set(n.id, 0));
    return depths;
  }

  const { forward } = buildAdjacency(agentEdges);
  while (queue.length > 0) {
    const current = queue.shift()!;
    const currentDepth = depths.get(current)!;
    const children = forward.get(current);
    if (children) {
      children.forEach((child) => {
        const existing = depths.get(child) ?? -1;
        if (currentDepth + 1 > existing) {
          depths.set(child, currentDepth + 1);
          queue.push(child);
        }
      });
    }
  }

  // Ensure all agents have a depth
  agentNodes.forEach((n) => {
    if (!depths.has(n.id)) depths.set(n.id, 0);
  });

  return depths;
}

/**
 * Compute layout positions for nodes in a clustered 3+ column layout.
 * Columns: ModelAPI (left), Agent(s) (middle, multi-column by depth), MCPServer (right).
 * Connected components are clustered together vertically.
 */
export function computeLayout(
  nodes: Node[],
  edges: Edge[],
  lockedNodeIds: Set<string> = new Set(),
  options: LayoutOptions = {},
): Node[] {
  const opts = { ...DEFAULT_OPTIONS, ...options };
  const rankSep = opts.rankSep!;
  const nodeSep = opts.nodeSep!;

  const resourceNodes = nodes.filter((n) => n.type === 'resourceNode');
  const headerNodes = nodes.filter((n) => n.type === 'columnHeader');

  // Separate by type
  const modelAPINodes = resourceNodes.filter((n) => (n.data as any)?.resourceType === 'ModelAPI');
  const mcpServerNodes = resourceNodes.filter((n) => (n.data as any)?.resourceType === 'MCPServer');
  const agentNodes = resourceNodes.filter((n) => (n.data as any)?.resourceType === 'Agent');

  // Compute agent dependency depths for multi-column
  const agentDepths = computeAgentDepths(agentNodes, edges);
  const maxAgentDepth = Math.max(0, ...Array.from(agentDepths.values()));
  const agentColumnCount = maxAgentDepth + 1;

  // Column X positions: ModelAPI=0, Agent columns=1..N, MCPServer=N+1
  const modelAPIX = 0;
  const agentBaseCol = 1;
  const mcpServerCol = agentBaseCol + agentColumnCount;

  function colX(col: number) {
    return col * rankSep;
  }

  // Find clusters among resource nodes
  const clusters = findClusters(resourceNodes.map((n) => n.id), edges);

  // Sort clusters: largest first for visual prominence
  clusters.sort((a, b) => b.size - a.size);

  // Track global Y offset to prevent disconnected clusters from overlapping
  let globalYOffset = 0;

  // Position nodes cluster by cluster
  const positioned = new Map<string, { x: number; y: number }>();

  clusters.forEach((cluster) => {
    // Group cluster nodes by their column
    const clusterByCol = new Map<number, Node[]>();

    cluster.forEach((nodeId) => {
      const node = resourceNodes.find((n) => n.id === nodeId);
      if (!node) return;
      const rt = (node.data as any)?.resourceType as string;
      let col: number;
      if (rt === 'ModelAPI') col = 0;
      else if (rt === 'MCPServer') col = mcpServerCol;
      else col = agentBaseCol + (agentDepths.get(nodeId) ?? 0);

      if (!clusterByCol.has(col)) clusterByCol.set(col, []);
      clusterByCol.get(col)!.push(node);
    });

    // Find the max height this cluster needs in any column
    let maxClusterHeight = 0;
    clusterByCol.forEach((colNodes) => {
      const h = colNodes.length * (NODE_HEIGHT + nodeSep);
      if (h > maxClusterHeight) maxClusterHeight = h;
    });

    // Sort nodes within each column to align connected nodes on the same row
    // Build a mapping of which row each agent is in, so MCPServers can align
    const agentRowMap = new Map<string, number>();

    // First pass: position agents (they define the row structure)
    const agentCols = Array.from(clusterByCol.entries()).filter(([col]) => col !== 0 && col !== mcpServerCol);
    agentCols.forEach(([col, colNodes]) => {
      colNodes.forEach((node, i) => {
        if (!lockedNodeIds.has(node.id)) {
          const y = globalYOffset + i * (NODE_HEIGHT + nodeSep);
          positioned.set(node.id, { x: colX(col), y });
          agentRowMap.set(node.id, y);
        }
      });
    });

    // Second pass: position ModelAPIs aligned to their connected agents
    const modelAPICol = clusterByCol.get(0);
    if (modelAPICol) {
      modelAPICol.forEach((node, i) => {
        if (lockedNodeIds.has(node.id)) return;
        // Find connected agents and average their Y
        const connectedAgentYs: number[] = [];
        edges.forEach(e => {
          if (e.source === node.id && agentRowMap.has(e.target)) {
            connectedAgentYs.push(agentRowMap.get(e.target)!);
          }
        });
        const y = connectedAgentYs.length > 0
          ? connectedAgentYs.reduce((a, b) => a + b, 0) / connectedAgentYs.length
          : globalYOffset + i * (NODE_HEIGHT + nodeSep);
        positioned.set(node.id, { x: colX(0), y });
      });
    }

    // Third pass: position MCPServers aligned to their connected agents
    const mcpCol = clusterByCol.get(mcpServerCol);
    if (mcpCol) {
      mcpCol.forEach((node, i) => {
        if (lockedNodeIds.has(node.id)) return;
        const connectedAgentYs: number[] = [];
        edges.forEach(e => {
          if (e.source === node.id && agentRowMap.has(e.target)) {
            connectedAgentYs.push(agentRowMap.get(e.target)!);
          }
        });
        const y = connectedAgentYs.length > 0
          ? connectedAgentYs.reduce((a, b) => a + b, 0) / connectedAgentYs.length
          : globalYOffset + i * (NODE_HEIGHT + nodeSep);
        positioned.set(node.id, { x: colX(mcpServerCol), y });
      });
    }

    // Advance global Y offset by the tallest column in this cluster + gap
    const clusterGap = nodeSep * 1.5;
    globalYOffset += maxClusterHeight + clusterGap;
  });

  // Also position any orphan nodes (no edges, not in any cluster with others)
  resourceNodes.forEach((node) => {
    if (positioned.has(node.id) || lockedNodeIds.has(node.id)) return;
    const rt = (node.data as any)?.resourceType as string;
    let col: number;
    if (rt === 'ModelAPI') col = 0;
    else if (rt === 'MCPServer') col = mcpServerCol;
    else col = agentBaseCol + (agentDepths.get(node.id) ?? 0);

    positioned.set(node.id, { x: colX(col), y: globalYOffset });
    globalYOffset += NODE_HEIGHT + nodeSep;
  });

  const layoutedResourceNodes = resourceNodes.map((node) => {
    if (lockedNodeIds.has(node.id)) return node;
    const pos = positioned.get(node.id);
    if (!pos) return node;
    return { ...node, position: pos };
  });

  // Position headers above each column
  const headerMap: Record<string, number> = {
    ModelAPI: 0,
    Agent: agentBaseCol,
    MCPServer: mcpServerCol,
  };

  const layoutedHeaders = headerNodes.map((header) => {
    const kind = header.id.replace('header-', '');
    const col = headerMap[kind];
    if (col === undefined) return header;

    // Find min Y for nodes in this column range
    let minY = 0;
    const relevantNodes = layoutedResourceNodes.filter((n) => {
      if (lockedNodeIds.has(n.id)) return false;
      const rt = (n.data as any)?.resourceType;
      return rt === kind;
    });
    if (relevantNodes.length > 0) {
      minY = Math.min(...relevantNodes.map((n) => n.position.y));
    }

    return {
      ...header,
      position: { x: colX(col), y: minY - 60 },
    };
  });

  return [...layoutedHeaders, ...layoutedResourceNodes];
}
