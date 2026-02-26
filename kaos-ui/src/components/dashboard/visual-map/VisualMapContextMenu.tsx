import React from 'react';
import { useNavigate } from 'react-router-dom';
import {
  ContextMenu,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuSeparator,
  ContextMenuTrigger,
} from '@/components/ui/context-menu';
import { Eye, FileCode, Boxes, Stethoscope, Wrench, MessageSquare, Focus, Pencil } from 'lucide-react';
import type { ResourceNodeData, ResourceKind } from './types';
import { RESOURCE_ROUTES } from './types';

interface VisualMapContextMenuProps {
  children: React.ReactNode;
  data: ResourceNodeData;
  onFocusNode: (nodeId: string) => void;
  onEditNode: (data: ResourceNodeData) => void;
}

const ICON_MAP: Record<string, typeof Eye> = {
  overview: Eye,
  yaml: FileCode,
  pods: Boxes,
  diagnostics: Stethoscope,
  tools: Wrench,
  chat: MessageSquare,
};

function getMenuItems(kind: ResourceKind): { label: string; tab: string; icon: string }[] {
  const base: { label: string; tab: string; icon: string }[] = [
    { label: 'View Overview', tab: 'overview', icon: 'overview' },
    { label: 'View YAML', tab: 'yaml', icon: 'yaml' },
    { label: 'View Pods', tab: 'pods', icon: 'pods' },
  ];
  if (kind === 'ModelAPI') base.push({ label: 'View Diagnostics', tab: 'diagnostics', icon: 'diagnostics' });
  if (kind === 'MCPServer') base.push({ label: 'View Tools', tab: 'tools', icon: 'tools' });
  if (kind === 'Agent') base.push({ label: 'Open Chat', tab: 'chat', icon: 'chat' });
  return base;
}

export function VisualMapContextMenu({ children, data, onFocusNode, onEditNode }: VisualMapContextMenuProps) {
  const navigate = useNavigate();
  const route = RESOURCE_ROUTES[data.resourceType];
  const { namespace, name } = data.resource.metadata;
  const basePath = `/${route}/${namespace}/${name}`;
  const nodeId = `${data.resourceType}/${namespace}/${name}`;

  const menuItems = getMenuItems(data.resourceType);

  return (
    <ContextMenu>
      <ContextMenuTrigger asChild>{children}</ContextMenuTrigger>
      <ContextMenuContent className="w-48">
        {menuItems.map((item) => {
          const Icon = ICON_MAP[item.icon] || Eye;
          return (
            <ContextMenuItem
              key={item.tab}
              onClick={() => navigate(item.tab === 'overview' ? basePath : `${basePath}?tab=${item.tab}`)}
              className="gap-2"
            >
              <Icon className="h-4 w-4" />
              {item.label}
            </ContextMenuItem>
          );
        })}
        <ContextMenuSeparator />
        <ContextMenuItem onClick={() => onFocusNode(nodeId)} className="gap-2">
          <Focus className="h-4 w-4" />
          Focus in Graph
        </ContextMenuItem>
        <ContextMenuItem onClick={() => onEditNode(data)} className="gap-2">
          <Pencil className="h-4 w-4" />
          Edit
        </ContextMenuItem>
      </ContextMenuContent>
    </ContextMenu>
  );
}
