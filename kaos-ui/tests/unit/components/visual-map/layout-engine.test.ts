import { describe, it, expect } from 'vitest';
import { computeLayout } from '@/components/dashboard/visual-map/layout-engine';
import type { Node, Edge } from '@xyflow/react';

function makeNode(id: string, resourceType: string, type = 'resourceNode'): Node {
  return {
    id,
    type,
    position: { x: 0, y: 0 },
    data: { resourceType, label: id, namespace: 'default', status: 'Ready' },
  };
}

function makeHeaderNode(kind: string): Node {
  return {
    id: `header-${kind}`,
    type: 'columnHeader',
    position: { x: 0, y: 0 },
    data: { label: kind, count: 0 },
  };
}

describe('computeLayout', () => {
  it('returns empty array for empty input', () => {
    const result = computeLayout([], []);
    expect(result).toEqual([]);
  });

  it('positions a single agent node', () => {
    const nodes = [makeNode('agent-1', 'Agent')];
    const result = computeLayout(nodes, []);
    expect(result).toHaveLength(1);
    expect(result[0].position).toBeDefined();
  });

  it('places ModelAPIs left of Agents, MCPServers right of Agents', () => {
    const nodes = [
      makeNode('model-1', 'ModelAPI'),
      makeNode('agent-1', 'Agent'),
      makeNode('mcp-1', 'MCPServer'),
    ];
    const edges: Edge[] = [
      { id: 'e1', source: 'model-1', target: 'agent-1' },
      { id: 'e2', source: 'mcp-1', target: 'agent-1' },
    ];

    const result = computeLayout(nodes, edges);

    const modelPos = result.find((n) => n.id === 'model-1')!.position;
    const agentPos = result.find((n) => n.id === 'agent-1')!.position;
    const mcpPos = result.find((n) => n.id === 'mcp-1')!.position;

    expect(modelPos.x).toBeLessThan(agentPos.x);
    expect(mcpPos.x).toBeGreaterThan(agentPos.x);
  });

  it('handles multiple agents with dependency depth', () => {
    const nodes = [
      makeNode('agent-a', 'Agent'),
      makeNode('agent-b', 'Agent'),
    ];
    const edges: Edge[] = [
      { id: 'e1', source: 'agent-a', target: 'agent-b' },
    ];

    const result = computeLayout(nodes, edges);
    const posA = result.find((n) => n.id === 'agent-a')!.position;
    const posB = result.find((n) => n.id === 'agent-b')!.position;

    // agent-b depends on agent-a, so agent-b gets higher depth → further right
    expect(posB.x).toBeGreaterThan(posA.x);
  });

  it('positions header nodes above resource nodes', () => {
    const nodes = [
      makeHeaderNode('Agent'),
      makeNode('agent-1', 'Agent'),
    ];
    const result = computeLayout(nodes, []);

    const header = result.find((n) => n.id === 'header-Agent')!;
    const agent = result.find((n) => n.id === 'agent-1')!;

    expect(header.position.y).toBeLessThan(agent.position.y);
  });

  it('does not move locked nodes', () => {
    const nodes = [makeNode('agent-1', 'Agent')];
    nodes[0].position = { x: 999, y: 999 };
    const locked = new Set(['agent-1']);

    const result = computeLayout(nodes, [], locked);
    expect(result[0].position).toEqual({ x: 999, y: 999 });
  });

  it('clusters connected components together', () => {
    const nodes = [
      makeNode('model-1', 'ModelAPI'),
      makeNode('agent-1', 'Agent'),
      makeNode('model-2', 'ModelAPI'),
      makeNode('agent-2', 'Agent'),
    ];
    const edges: Edge[] = [
      { id: 'e1', source: 'model-1', target: 'agent-1' },
      { id: 'e2', source: 'model-2', target: 'agent-2' },
    ];

    const result = computeLayout(nodes, edges);

    // Both clusters should be laid out without overlapping
    const agent1Y = result.find((n) => n.id === 'agent-1')!.position.y;
    const agent2Y = result.find((n) => n.id === 'agent-2')!.position.y;
    expect(agent1Y).not.toBe(agent2Y);
  });

  it('handles a complex graph with ModelAPI → Agent → MCPServer', () => {
    const nodes = [
      makeHeaderNode('ModelAPI'),
      makeHeaderNode('Agent'),
      makeHeaderNode('MCPServer'),
      makeNode('m1', 'ModelAPI'),
      makeNode('a1', 'Agent'),
      makeNode('a2', 'Agent'),
      makeNode('mcp1', 'MCPServer'),
    ];
    const edges: Edge[] = [
      { id: 'e1', source: 'm1', target: 'a1' },
      { id: 'e2', source: 'mcp1', target: 'a1' },
      { id: 'e3', source: 'a1', target: 'a2' },
    ];

    const result = computeLayout(nodes, edges);
    expect(result).toHaveLength(7);

    // All nodes should have defined positions
    result.forEach((node) => {
      expect(node.position).toBeDefined();
      expect(typeof node.position.x).toBe('number');
      expect(typeof node.position.y).toBe('number');
    });
  });
});
