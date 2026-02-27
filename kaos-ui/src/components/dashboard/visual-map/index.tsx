import React, { useState, useCallback, useEffect, useMemo, useRef } from 'react';
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  useNodesState,
  useEdgesState,
  useReactFlow,
  useOnViewportChange,
  type NodeTypes,
  type EdgeTypes,
  type Viewport,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { ReactFlowProvider } from '@xyflow/react';
import { TooltipProvider } from '@/components/ui/tooltip';
import { ResourceStatusLegend } from './ResourceStatusLegend';
import { Bot } from 'lucide-react';
import { useKubernetesStore } from '@/stores/kubernetesStore';
import { ResourceNode, VisualMapZoomContext, VisualMapCompactContext } from './ResourceNode';
import { ColumnHeaderNode } from './ColumnHeaderNode';
import { DynamicEdge } from './DynamicEdge';
import { VisualMapToolbar } from './VisualMapToolbar';
import { VisualMapContextMenu } from './VisualMapContextMenu';
import { useVisualMapLayout } from './useVisualMapLayout';
import { useVisualMapFilters } from './useVisualMapFilters';
import type { ResourceNodeData, ResourceKind } from './types';

// Edit dialogs
import { AgentEditDialog } from '@/components/resources/AgentEditDialog';
import { MCPServerEditDialog } from '@/components/resources/MCPServerEditDialog';
import { ModelAPIEditDialog } from '@/components/resources/ModelAPIEditDialog';
// Create dialogs
import { AgentCreateDialog } from '@/components/resources/AgentCreateDialog';
import { MCPServerCreateDialog } from '@/components/resources/MCPServerCreateDialog';
import { ModelAPICreateDialog } from '@/components/resources/ModelAPICreateDialog';

import type { Agent, MCPServer, ModelAPI } from '@/types/kubernetes';

const VIEWPORT_STORAGE_KEY = 'visual-map-viewport';

function loadSavedViewport(): Viewport | undefined {
  try {
    const saved = localStorage.getItem(VIEWPORT_STORAGE_KEY);
    if (saved) return JSON.parse(saved) as Viewport;
  } catch { /* ignore */ }
  return undefined;
}

function saveViewport(vp: Viewport) {
  try {
    localStorage.setItem(VIEWPORT_STORAGE_KEY, JSON.stringify(vp));
  } catch { /* ignore */ }
}

// ── Wrap ResourceNode with context menu + edit handler ──
function ContextMenuResourceNode({ data, ...rest }: { data: ResourceNodeData; [key: string]: any }) {
  const { fitView } = useReactFlow();

  const handleFocusNode = useCallback((nodeId: string) => {
    fitView({ nodes: [{ id: nodeId }], padding: 0.5, duration: 400 });
  }, [fitView]);

  const handleEditNode = useCallback((data: ResourceNodeData) => {
    const store = useKubernetesStore.getState();
    store.setSelectedResource(data.resource);
    store.setSelectedResourceMode('edit');
  }, []);

  return (
    <VisualMapContextMenu data={data} onFocusNode={handleFocusNode} onEditNode={handleEditNode}>
      <div>
        <ResourceNode data={data} onEdit={handleEditNode} />
      </div>
    </VisualMapContextMenu>
  );
}

const nodeTypes: NodeTypes = {
  resourceNode: ContextMenuResourceNode as any,
  columnHeader: ColumnHeaderNode as any,
};

const edgeTypes: EdgeTypes = {
  dynamic: DynamicEdge as any,
};

// ── Inner component (needs ReactFlowProvider) ──
function VisualMapInner() {
  const { modelAPIs, mcpServers, agents, selectedResource, selectedResourceMode, setSelectedResource, setSelectedResourceMode } = useKubernetesStore();
  const [zoom, setZoom] = useState(1);

  // Create dialog state
  const [createKind, setCreateKind] = useState<ResourceKind | null>(null);
  const hasInitialFit = useRef(false);

  const {
    initialNodes,
    initialEdges,
    changed,
    newNodeIds,
    handleNodeDragStop,
    reLayout,
  } = useVisualMapLayout(modelAPIs, mcpServers, agents);

  const [nodes, setNodes, onNodesChange] = useNodesState(initialNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(initialEdges);

  const { fitView, setViewport } = useReactFlow();

  // Sync nodes when structural change
  useEffect(() => {
    if (changed) {
      setNodes(initialNodes);
    }
  }, [initialNodes, changed, setNodes]);

  // Sync edges always
  useEffect(() => {
    setEdges(initialEdges);
  }, [initialEdges, setEdges]);

  // Auto-focus on newly created resources
  useEffect(() => {
    if (newNodeIds.size > 0) {
      const ids = Array.from(newNodeIds);
      setTimeout(() => {
        fitView({ nodes: ids.map(id => ({ id })), padding: 0.5, duration: 400 });
      }, 100);
    }
  }, [newNodeIds, fitView]);

  // Restore saved viewport on first mount, or fitView if none saved
  useEffect(() => {
    if (hasInitialFit.current) return;
    hasInitialFit.current = true;
    const saved = loadSavedViewport();
    if (saved) {
      setTimeout(() => setViewport(saved, { duration: 0 }), 50);
    } else {
      setTimeout(() => fitView({ padding: 0.3, duration: 300 }), 50);
    }
  }, [fitView, setViewport]);

  // Persist viewport on change
  useOnViewportChange({
    onChange: useCallback((vp: Viewport) => {
      setZoom(vp.zoom);
      saveViewport(vp);
    }, []),
  });

  const {
    kindFilter, statusFilter, searchQuery,
    toggleKind, toggleStatus, setSearchQuery, applyFilters,
  } = useVisualMapFilters();

  const { nodes: displayNodes, edges: displayEdges } = useMemo(
    () => applyFilters(nodes, edges),
    [nodes, edges, applyFilters],
  );

  const handleReLayout = useCallback(() => {
    const layoutedNodes = reLayout(nodes, edges);
    setNodes(layoutedNodes);
    setTimeout(() => fitView({ padding: 0.3, duration: 300 }), 50);
  }, [nodes, edges, reLayout, setNodes, fitView]);

  const handleFitView = useCallback(() => {
    fitView({ padding: 0.3, duration: 300 });
  }, [fitView]);

  const handleCreateResource = useCallback((kind: ResourceKind) => {
    setCreateKind(kind);
  }, []);

  // Determine what's being edited
  const editingAgent = selectedResourceMode === 'edit' && selectedResource?.kind === 'Agent' ? selectedResource as Agent : null;
  const editingMCPServer = selectedResourceMode === 'edit' && selectedResource?.kind === 'MCPServer' ? selectedResource as MCPServer : null;
  const editingModelAPI = selectedResourceMode === 'edit' && selectedResource?.kind === 'ModelAPI' ? selectedResource as ModelAPI : null;

  const closeEdit = useCallback(() => {
    setSelectedResource(null);
    setSelectedResourceMode(null);
  }, [setSelectedResource, setSelectedResourceMode]);

  const isEmpty = modelAPIs.length === 0 && mcpServers.length === 0 && agents.length === 0;

  if (isEmpty) {
    return (
      <div className="flex flex-col items-center justify-center h-[calc(100vh-200px)] text-muted-foreground gap-3">
        <Bot className="h-12 w-12 opacity-30" />
        <p className="text-sm">No resources found. Create ModelAPIs, MCPServers, or Agents to see them here.</p>
      </div>
    );
  }

  return (
    <VisualMapZoomContext.Provider value={zoom}>
      <VisualMapCompactContext.Provider value={false}>
        <TooltipProvider delayDuration={200}>
          <div className="h-[calc(100vh-140px)] w-full rounded-xl border border-border bg-card overflow-hidden relative">
            <VisualMapToolbar
              kindFilter={kindFilter}
              statusFilter={statusFilter}
              searchQuery={searchQuery}
              onToggleKind={toggleKind}
              onToggleStatus={toggleStatus}
              onSearchChange={setSearchQuery}
              onReLayout={handleReLayout}
              onFitView={handleFitView}
              onCreateResource={handleCreateResource}
            />

            <ReactFlow
              nodes={displayNodes}
              edges={displayEdges}
              onNodesChange={onNodesChange}
              onEdgesChange={onEdgesChange}
              onNodeDragStop={handleNodeDragStop}
              nodeTypes={nodeTypes}
              edgeTypes={edgeTypes}
              proOptions={{ hideAttribution: true }}
              minZoom={0.3}
              maxZoom={2}
            >
              <Background gap={20} size={1} className="!bg-background" />
              <Controls className="!bg-card !border-border !shadow-sm [&>button]:!bg-card [&>button]:!border-border [&>button]:!text-foreground" />
              <MiniMap
                nodeColor={(node) => {
                  const rt = (node.data as unknown as ResourceNodeData)?.resourceType;
                  if (rt === 'ModelAPI') return 'hsl(var(--modelapi-color))';
                  if (rt === 'MCPServer') return 'hsl(var(--mcpserver-color))';
                  if (rt === 'Agent') return 'hsl(var(--agent-color))';
                  return 'hsl(var(--muted-foreground))';
                }}
                className="!bg-card !border-border"
                maskColor="hsl(var(--background) / 0.7)"
              />
            </ReactFlow>
            <ResourceStatusLegend modelAPIs={modelAPIs} mcpServers={mcpServers} agents={agents} />
          </div>

          {/* Edit Dialogs */}
          {editingAgent && (
            <AgentEditDialog agent={editingAgent} open onClose={closeEdit} />
          )}
          {editingMCPServer && (
            <MCPServerEditDialog mcpServer={editingMCPServer} open onClose={closeEdit} />
          )}
          {editingModelAPI && (
            <ModelAPIEditDialog modelAPI={editingModelAPI} open onClose={closeEdit} />
          )}

          {/* Create Dialogs */}
          <AgentCreateDialog open={createKind === 'Agent'} onClose={() => setCreateKind(null)} />
          <MCPServerCreateDialog open={createKind === 'MCPServer'} onClose={() => setCreateKind(null)} />
          <ModelAPICreateDialog open={createKind === 'ModelAPI'} onClose={() => setCreateKind(null)} />
        </TooltipProvider>
      </VisualMapCompactContext.Provider>
    </VisualMapZoomContext.Provider>
  );
}

export function VisualMapEnhanced() {
  return (
    <ReactFlowProvider>
      <VisualMapInner />
    </ReactFlowProvider>
  );
}
