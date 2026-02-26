import type { ModelAPI, MCPServer, Agent } from '@/types/kubernetes';

export type ResourceKind = 'ModelAPI' | 'MCPServer' | 'Agent';

export interface ResourceNodeData {
  label: string;
  namespace: string;
  status: string;
  statusMessage?: string;
  resourceType: ResourceKind;
  resource: ModelAPI | MCPServer | Agent;
  isHighlighted?: boolean;
  isDimmed?: boolean;
}

export interface ColumnHeaderData {
  label: string;
  count: number;
  onAdd?: () => void;
}

export interface VisualMapFilterState {
  kindFilter: Set<ResourceKind>;
  statusFilter: Set<string>;
  searchQuery: string;
}

export const RESOURCE_ROUTES: Record<ResourceKind, string> = {
  ModelAPI: 'modelapis',
  MCPServer: 'mcpservers',
  Agent: 'agents',
};

export const RESOURCE_QUICK_ACTIONS: Record<ResourceKind, { icon: string; label: string; tab: string }[]> = {
  Agent: [
    { icon: 'Info', label: 'Overview', tab: 'overview' },
    { icon: 'MessageSquare', label: 'Chat', tab: 'chat' },
    { icon: 'Brain', label: 'Memory', tab: 'memory' },
  ],
  MCPServer: [
    { icon: 'Info', label: 'Overview', tab: 'overview' },
    { icon: 'Wrench', label: 'Tools', tab: 'tools' },
  ],
  ModelAPI: [
    { icon: 'Info', label: 'Overview', tab: 'overview' },
    { icon: 'Stethoscope', label: 'Diagnostics', tab: 'diagnostics' },
  ],
};

export const CONTEXT_MENU_ITEMS: Record<ResourceKind, { label: string; tab?: string; action?: string }[]> = {
  ModelAPI: [
    { label: 'View Overview', tab: 'overview' },
    { label: 'View YAML', tab: 'yaml' },
    { label: 'View Pods', tab: 'pods' },
    { label: 'View Diagnostics', tab: 'diagnostics' },
    { label: 'Focus in Graph', action: 'focus' },
    { label: 'Edit', action: 'edit' },
  ],
  MCPServer: [
    { label: 'View Overview', tab: 'overview' },
    { label: 'View YAML', tab: 'yaml' },
    { label: 'View Pods', tab: 'pods' },
    { label: 'View Tools', tab: 'tools' },
    { label: 'Focus in Graph', action: 'focus' },
    { label: 'Edit', action: 'edit' },
  ],
  Agent: [
    { label: 'View Overview', tab: 'overview' },
    { label: 'View YAML', tab: 'yaml' },
    { label: 'View Pods', tab: 'pods' },
    { label: 'Open Chat', tab: 'chat' },
    { label: 'Focus in Graph', action: 'focus' },
    { label: 'Edit', action: 'edit' },
  ],
};
