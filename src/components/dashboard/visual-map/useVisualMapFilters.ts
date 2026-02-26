import { useState, useCallback, useMemo } from 'react';
import type { Node, Edge } from '@xyflow/react';
import type { ResourceKind, ResourceNodeData } from './types';

export function useVisualMapFilters() {
  const [kindFilter, setKindFilter] = useState<Set<ResourceKind>>(new Set(['ModelAPI', 'MCPServer', 'Agent']));
  const [statusFilter, setStatusFilter] = useState<Set<string>>(new Set());
  const [searchQuery, setSearchQuery] = useState('');

  const toggleKind = useCallback((kind: ResourceKind) => {
    setKindFilter((prev) => {
      const next = new Set(prev);
      if (next.has(kind)) {
        if (next.size > 1) next.delete(kind); // Keep at least one
      } else {
        next.add(kind);
      }
      return next;
    });
  }, []);

  const toggleStatus = useCallback((status: string) => {
    setStatusFilter((prev) => {
      const next = new Set(prev);
      if (next.has(status)) next.delete(status);
      else next.add(status);
      return next;
    });
  }, []);

  const applyFilters = useCallback((nodes: Node[], edges: Edge[]): { nodes: Node[]; edges: Edge[] } => {
    const dimmedNodeIds = new Set<string>();

    const filteredNodes = nodes.map((node) => {
      if (node.type !== 'resourceNode') return node;
      const data = node.data as unknown as ResourceNodeData;

      let matches = true;

      // Kind filter
      if (!kindFilter.has(data.resourceType)) matches = false;

      // Status filter (only if any status is selected)
      if (statusFilter.size > 0) {
        const s = data.status?.toLowerCase();
        // Map deployment-aware statuses to their base filter
        const statusMap: Record<string, string> = { updating: 'pending', progressing: 'pending' };
        const mappedStatus = statusMap[s] || s;
        if (!statusFilter.has(mappedStatus)) matches = false;
      }

      // Search
      if (searchQuery) {
        const q = searchQuery.toLowerCase();
        const nameMatch = data.label.toLowerCase().includes(q);
        const nsMatch = data.namespace.toLowerCase().includes(q);
        if (!nameMatch && !nsMatch) matches = false;
      }

      if (!matches) {
        dimmedNodeIds.add(node.id);
        return {
          ...node,
          data: { ...data, isDimmed: true, isHighlighted: false },
        };
      }

      const isHighlighted = searchQuery.length > 0;
      return {
        ...node,
        data: { ...data, isDimmed: false, isHighlighted },
      };
    });

    const filteredEdges = edges.map((edge) => {
      const dimmed = dimmedNodeIds.has(edge.source) || dimmedNodeIds.has(edge.target);
      return {
        ...edge,
        style: { ...edge.style, opacity: dimmed ? 0.1 : 1 },
        animated: dimmed ? false : edge.animated,
        labelStyle: { ...edge.labelStyle, opacity: dimmed ? 0 : 1 },
      };
    });

    return { nodes: filteredNodes, edges: filteredEdges };
  }, [kindFilter, statusFilter, searchQuery]);

  return {
    kindFilter,
    statusFilter,
    searchQuery,
    toggleKind,
    toggleStatus,
    setSearchQuery,
    applyFilters,
  };
}
