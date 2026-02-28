import { describe, it, expect } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useVisualMapFilters } from '@/components/dashboard/visual-map/useVisualMapFilters';
import type { Node, Edge } from '@xyflow/react';
import type { ResourceNodeData } from '@/components/dashboard/visual-map/types';

function makeResourceNode(id: string, resourceType: string, status: string, label?: string): Node {
  return {
    id,
    type: 'resourceNode',
    position: { x: 0, y: 0 },
    data: {
      resourceType,
      label: label || id,
      namespace: 'default',
      status,
    },
  };
}

describe('useVisualMapFilters', () => {
  it('initializes with all kinds enabled and no status/search filters', () => {
    const { result } = renderHook(() => useVisualMapFilters());
    expect(result.current.kindFilter.has('ModelAPI')).toBe(true);
    expect(result.current.kindFilter.has('MCPServer')).toBe(true);
    expect(result.current.kindFilter.has('Agent')).toBe(true);
    expect(result.current.statusFilter.size).toBe(0);
    expect(result.current.searchQuery).toBe('');
  });

  describe('toggleKind', () => {
    it('removes a kind when toggling an active kind', () => {
      const { result } = renderHook(() => useVisualMapFilters());
      act(() => result.current.toggleKind('ModelAPI'));
      expect(result.current.kindFilter.has('ModelAPI')).toBe(false);
    });

    it('adds a kind when toggling an inactive kind', () => {
      const { result } = renderHook(() => useVisualMapFilters());
      act(() => result.current.toggleKind('ModelAPI')); // remove
      act(() => result.current.toggleKind('ModelAPI')); // re-add
      expect(result.current.kindFilter.has('ModelAPI')).toBe(true);
    });

    it('keeps at least one kind active', () => {
      const { result } = renderHook(() => useVisualMapFilters());
      act(() => result.current.toggleKind('ModelAPI'));
      act(() => result.current.toggleKind('MCPServer'));
      // Only Agent left — toggling it should keep it
      act(() => result.current.toggleKind('Agent'));
      expect(result.current.kindFilter.size).toBe(1);
      expect(result.current.kindFilter.has('Agent')).toBe(true);
    });
  });

  describe('toggleStatus', () => {
    it('adds and removes status filters', () => {
      const { result } = renderHook(() => useVisualMapFilters());
      act(() => result.current.toggleStatus('ready'));
      expect(result.current.statusFilter.has('ready')).toBe(true);
      act(() => result.current.toggleStatus('ready'));
      expect(result.current.statusFilter.has('ready')).toBe(false);
    });
  });

  describe('applyFilters', () => {
    const nodes: Node[] = [
      makeResourceNode('agent-1', 'Agent', 'Ready', 'my-agent'),
      makeResourceNode('mcp-1', 'MCPServer', 'Ready', 'my-mcp'),
      makeResourceNode('model-1', 'ModelAPI', 'Failed', 'my-model'),
    ];
    const edges: Edge[] = [
      { id: 'e1', source: 'model-1', target: 'agent-1', style: {}, animated: true },
    ];

    it('dims nodes that do not match kind filter', () => {
      const { result } = renderHook(() => useVisualMapFilters());
      act(() => result.current.toggleKind('ModelAPI')); // disable ModelAPI

      const filtered = result.current.applyFilters(nodes, edges);
      const modelNode = filtered.nodes.find((n) => n.id === 'model-1')!;
      const agentNode = filtered.nodes.find((n) => n.id === 'agent-1')!;

      expect((modelNode.data as unknown as ResourceNodeData).isDimmed).toBe(true);
      expect((agentNode.data as unknown as ResourceNodeData).isDimmed).toBe(false);
    });

    it('dims edges connected to dimmed nodes', () => {
      const { result } = renderHook(() => useVisualMapFilters());
      act(() => result.current.toggleKind('ModelAPI'));

      const filtered = result.current.applyFilters(nodes, edges);
      const edge = filtered.edges[0];
      expect(edge.style?.opacity).toBe(0.1);
    });

    it('filters by search query on name', () => {
      const { result } = renderHook(() => useVisualMapFilters());
      act(() => result.current.setSearchQuery('my-agent'));

      const filtered = result.current.applyFilters(nodes, edges);
      const agentNode = filtered.nodes.find((n) => n.id === 'agent-1')!;
      const mcpNode = filtered.nodes.find((n) => n.id === 'mcp-1')!;

      expect((agentNode.data as unknown as ResourceNodeData).isDimmed).toBe(false);
      expect((agentNode.data as unknown as ResourceNodeData).isHighlighted).toBe(true);
      expect((mcpNode.data as unknown as ResourceNodeData).isDimmed).toBe(true);
    });

    it('filters by status when status filter is active', () => {
      const { result } = renderHook(() => useVisualMapFilters());
      act(() => result.current.toggleStatus('failed'));

      const filtered = result.current.applyFilters(nodes, edges);
      const modelNode = filtered.nodes.find((n) => n.id === 'model-1')!;
      const agentNode = filtered.nodes.find((n) => n.id === 'agent-1')!;

      expect((modelNode.data as unknown as ResourceNodeData).isDimmed).toBe(false);
      expect((agentNode.data as unknown as ResourceNodeData).isDimmed).toBe(true);
    });

    it('passes through non-resourceNode nodes unchanged', () => {
      const headerNode: Node = {
        id: 'header-Agent',
        type: 'columnHeader',
        position: { x: 0, y: 0 },
        data: { label: 'Agent', count: 1 },
      };
      const { result } = renderHook(() => useVisualMapFilters());
      const filtered = result.current.applyFilters([headerNode], []);
      expect(filtered.nodes[0]).toEqual(headerNode);
    });
  });
});
