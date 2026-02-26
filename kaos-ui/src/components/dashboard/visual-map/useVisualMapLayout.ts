import { useCallback, useRef, useState, useMemo, useEffect } from 'react';
import type { Node, Edge } from '@xyflow/react';
import { computeLayout } from './layout-engine';
import type { ResourceNodeData } from './types';
import type { ModelAPI, MCPServer, Agent, DeploymentStatusInfo } from '@/types/kubernetes';
import { MarkerType } from '@xyflow/react';

const POSITIONS_STORAGE_KEY = 'visual-map-node-positions';

/**
 * Compute effective status from resource phase + deployment info.
 * Mirrors the logic used in DeploymentStatusCard for rolling updates.
 */
function computeEffectiveStatus(resource: ModelAPI | MCPServer | Agent): string {
  const phase = resource.status?.phase || 'Unknown';
  const deployment = (resource.status as any)?.deployment as DeploymentStatusInfo | undefined;
  if (!deployment) return phase;

  const { replicas = 0, readyReplicas = 0, updatedReplicas = 0 } = deployment;
  if (replicas > 0 && updatedReplicas < replicas) return 'Updating';
  if (replicas > 0 && readyReplicas === 0) return 'Pending';
  if (replicas > 0 && readyReplicas < replicas) return 'Progressing';
  if (readyReplicas > 0 && readyReplicas >= replicas) return 'Ready';
  return phase;
}

function buildGraph(
  modelAPIs: ModelAPI[],
  mcpServers: MCPServer[],
  agents: Agent[],
) {
  const nodes: Node[] = [];
  const edges: Edge[] = [];
  const nodeId = (kind: string, ns: string, name: string) => `${kind}/${ns}/${name}`;

  // Column headers
  (['ModelAPI', 'Agent', 'MCPServer'] as const).forEach((key) => {
    const list = key === 'ModelAPI' ? modelAPIs : key === 'MCPServer' ? mcpServers : agents;
    const labels: Record<string, string> = { ModelAPI: 'Model APIs', Agent: 'Agents', MCPServer: 'MCP Servers' };
    nodes.push({
      id: `header-${key}`,
      type: 'columnHeader',
      position: { x: 0, y: -60 },
      data: { label: labels[key], count: list.length },
      draggable: false,
      selectable: false,
    });
  });

  modelAPIs.forEach((r) => {
    nodes.push({
      id: nodeId('ModelAPI', r.metadata.namespace, r.metadata.name),
      type: 'resourceNode',
      position: { x: 0, y: 0 },
      data: {
        label: r.metadata.name, namespace: r.metadata.namespace,
        status: computeEffectiveStatus(r), statusMessage: r.status?.message,
        resourceType: 'ModelAPI', resource: r,
      } satisfies ResourceNodeData,
    });
  });

  mcpServers.forEach((r) => {
    nodes.push({
      id: nodeId('MCPServer', r.metadata.namespace, r.metadata.name),
      type: 'resourceNode',
      position: { x: 0, y: 0 },
      data: {
        label: r.metadata.name, namespace: r.metadata.namespace,
        status: computeEffectiveStatus(r), statusMessage: r.status?.message,
        resourceType: 'MCPServer', resource: r,
      } satisfies ResourceNodeData,
    });
  });

  agents.forEach((agent) => {
    const agentId = nodeId('Agent', agent.metadata.namespace, agent.metadata.name);
    nodes.push({
      id: agentId,
      type: 'resourceNode',
      position: { x: 0, y: 0 },
      data: {
        label: agent.metadata.name, namespace: agent.metadata.namespace,
        status: computeEffectiveStatus(agent), statusMessage: agent.status?.message,
        resourceType: 'Agent', resource: agent,
      } satisfies ResourceNodeData,
    });

    // ModelAPI edge — gray
    if (agent.spec.modelAPI) {
      const sourceId = nodeId('ModelAPI', agent.metadata.namespace, agent.spec.modelAPI);
      edges.push({
        id: `edge-modelapi-${agent.metadata.name}`,
        source: sourceId, target: agentId, type: 'dynamic',
        animated: true, label: 'model',
        style: { stroke: 'hsl(var(--modelapi-color))', strokeWidth: 2 },
        markerEnd: { type: MarkerType.ArrowClosed, color: 'hsl(var(--modelapi-color))' },
        labelStyle: { fill: 'hsl(var(--muted-foreground))', fontSize: 10 },
        labelBgStyle: { fill: 'hsl(var(--card))', fillOpacity: 0.9 },
      });
    }

    // MCPServer edges — light blue
    agent.spec.mcpServers?.forEach((mcpName) => {
      const sourceId = nodeId('MCPServer', agent.metadata.namespace, mcpName);
      edges.push({
        id: `edge-mcp-${mcpName}-${agent.metadata.name}`,
        source: sourceId, target: agentId, type: 'dynamic',
        animated: true, label: 'tools',
        style: { stroke: 'hsl(var(--mcpserver-color))', strokeWidth: 2 },
        markerEnd: { type: MarkerType.ArrowClosed, color: 'hsl(var(--mcpserver-color))' },
        labelStyle: { fill: 'hsl(var(--muted-foreground))', fontSize: 10 },
        labelBgStyle: { fill: 'hsl(var(--card))', fillOpacity: 0.9 },
      });
    });

    // Agent-to-agent edges — purple
    agent.spec.agentNetwork?.access?.forEach((targetAgentName: string) => {
      const targetId = nodeId('Agent', agent.metadata.namespace, targetAgentName);
      edges.push({
        id: `edge-a2a-${agent.metadata.name}-${targetAgentName}`,
        source: agentId, target: targetId, type: 'dynamic',
        animated: true, label: 'a2a',
        style: { stroke: 'hsl(var(--agent-color))', strokeWidth: 2 },
        markerEnd: { type: MarkerType.ArrowClosed, color: 'hsl(var(--agent-color))' },
        labelStyle: { fill: 'hsl(var(--muted-foreground))', fontSize: 10 },
        labelBgStyle: { fill: 'hsl(var(--card))', fillOpacity: 0.9 },
      });
    });
  });

  return { nodes, edges };
}

function resourceFingerprint(modelAPIs: ModelAPI[], mcpServers: MCPServer[], agents: Agent[]): string {
  const m = modelAPIs.map(r => `${r.metadata.namespace}/${r.metadata.name}:${r.status?.phase}:${(r.status as any)?.deployment?.readyReplicas ?? ''}/${(r.status as any)?.deployment?.replicas ?? ''}`).sort().join(',');
  const s = mcpServers.map(r => `${r.metadata.namespace}/${r.metadata.name}:${r.status?.phase}:${(r.status as any)?.deployment?.readyReplicas ?? ''}/${(r.status as any)?.deployment?.replicas ?? ''}`).sort().join(',');
  const a = agents.map(r => `${r.metadata.namespace}/${r.metadata.name}:${r.status?.phase}:${r.spec.modelAPI}:${r.spec.mcpServers?.sort().join('+')}:${r.spec.agentNetwork?.access?.sort().join('+') ?? ''}:${(r.status as any)?.deployment?.readyReplicas ?? ''}/${(r.status as any)?.deployment?.replicas ?? ''}`).sort().join(',');
  return `${m}|${s}|${a}`;
}

function loadSavedPositions(): Map<string, { x: number; y: number }> {
  try {
    const saved = localStorage.getItem(POSITIONS_STORAGE_KEY);
    if (saved) {
      const parsed = JSON.parse(saved) as Record<string, { x: number; y: number }>;
      return new Map(Object.entries(parsed));
    }
  } catch { /* ignore */ }
  return new Map();
}

function savePositions(positions: Map<string, { x: number; y: number }>) {
  try {
    const obj: Record<string, { x: number; y: number }> = {};
    positions.forEach((pos, id) => { obj[id] = pos; });
    localStorage.setItem(POSITIONS_STORAGE_KEY, JSON.stringify(obj));
  } catch { /* ignore */ }
}

export function useVisualMapLayout(
  modelAPIs: ModelAPI[],
  mcpServers: MCPServer[],
  agents: Agent[],
) {
  const lockedPositions = useRef<Map<string, { x: number; y: number }>>(loadSavedPositions());
  const prevFingerprint = useRef<string>('');
  const hasInitialized = useRef(false);
  const prevLayoutNodes = useRef<Node[]>([]);
  const prevNodeIds = useRef<Set<string>>(new Set());

  const structuralFP = useMemo(
    () => resourceFingerprint(modelAPIs, mcpServers, agents),
    [modelAPIs, mcpServers, agents],
  );

  const { initialNodes, initialEdges, changed, newNodeIds } = useMemo(() => {
    const structurallyChanged = structuralFP !== prevFingerprint.current;
    const { nodes: graphNodes, edges } = buildGraph(modelAPIs, mcpServers, agents);

    // Detect new nodes
    const currentIds = new Set(graphNodes.filter(n => n.type === 'resourceNode').map(n => n.id));
    const newIds = new Set<string>();
    if (hasInitialized.current) {
      currentIds.forEach(id => {
        if (!prevNodeIds.current.has(id)) newIds.add(id);
      });
    }
    prevNodeIds.current = currentIds;

    let layoutedNodes: Node[];
    if (structurallyChanged || !hasInitialized.current) {
      prevFingerprint.current = structuralFP;
      hasInitialized.current = true;
      layoutedNodes = computeLayout(graphNodes, edges, new Set(lockedPositions.current.keys()));

      // Apply saved positions for locked nodes
      layoutedNodes = layoutedNodes.map(node => {
        const saved = lockedPositions.current.get(node.id);
        if (saved) return { ...node, position: saved };
        return node;
      });

      prevLayoutNodes.current = layoutedNodes;
    } else {
      layoutedNodes = prevLayoutNodes.current;
    }

    return { initialNodes: layoutedNodes, initialEdges: edges, changed: structurallyChanged, newNodeIds: newIds };
  }, [modelAPIs, mcpServers, agents, structuralFP]);

  const handleNodeDragStop = useCallback((_: any, node: Node) => {
    lockedPositions.current.set(node.id, { ...node.position });
    savePositions(lockedPositions.current);
  }, []);

  const reLayout = useCallback((currentNodes: Node[], currentEdges: Edge[]): Node[] => {
    lockedPositions.current.clear();
    savePositions(lockedPositions.current);
    return computeLayout(currentNodes, currentEdges, new Set());
  }, []);

  return {
    initialNodes,
    initialEdges,
    changed,
    newNodeIds,
    handleNodeDragStop,
    reLayout,
  };
}
