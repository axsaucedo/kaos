import React, { createContext, useContext } from 'react';
import { useNavigate } from 'react-router-dom';
import { Handle, Position } from '@xyflow/react';
import { Box, Server, Bot, Info, MessageSquare, Brain, Wrench, Stethoscope, AlertTriangle, Pencil } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Tooltip, TooltipTrigger, TooltipContent } from '@/components/ui/tooltip';
import type { ResourceNodeData, ResourceKind } from './types';
import { RESOURCE_ROUTES } from './types';

// Context for zoom level and compact mode toggle (zoom no longer triggers compact)
export const VisualMapZoomContext = createContext<number>(1);
export const VisualMapCompactContext = createContext<boolean>(false);

const ICON_MAP = { Box, Server, Bot, Info, MessageSquare, Brain, Wrench, Stethoscope };

const RESOURCE_CONFIG: Record<ResourceKind, {
  icon: typeof Box;
  colorClass: string;
  badgeVariant: 'modelapi' | 'mcpserver' | 'agent';
  quickActions: { icon: keyof typeof ICON_MAP; label: string; tab: string }[];
}> = {
  ModelAPI: {
    icon: Box,
    colorClass: 'border-l-[hsl(var(--modelapi-color))]',
    badgeVariant: 'modelapi',
    quickActions: [
      { icon: 'Info', label: 'Overview', tab: 'overview' },
      { icon: 'Stethoscope', label: 'Diagnostics', tab: 'diagnostics' },
    ],
  },
  MCPServer: {
    icon: Server,
    colorClass: 'border-l-[hsl(var(--mcpserver-color))]',
    badgeVariant: 'mcpserver',
    quickActions: [
      { icon: 'Info', label: 'Overview', tab: 'overview' },
      { icon: 'Wrench', label: 'Tools', tab: 'tools' },
    ],
  },
  Agent: {
    icon: Bot,
    colorClass: 'border-l-[hsl(var(--agent-color))]',
    badgeVariant: 'agent',
    quickActions: [
      { icon: 'Info', label: 'Overview', tab: 'overview' },
      { icon: 'MessageSquare', label: 'Chat', tab: 'chat' },
      { icon: 'Brain', label: 'Memory', tab: 'memory' },
    ],
  },
};

function getStatusVariant(status: string): 'success' | 'warning' | 'destructive' | 'secondary' {
  switch (status?.toLowerCase()) {
    case 'ready':
    case 'running': return 'success';
    case 'pending':
    case 'waiting':
    case 'updating':
    case 'progressing': return 'warning';
    case 'failed':
    case 'error': return 'destructive';
    default: return 'secondary';
  }
}

function getStatusDotColor(status: string): string {
  switch (status?.toLowerCase()) {
    case 'ready':
    case 'running': return 'bg-success';
    case 'pending':
    case 'waiting':
    case 'updating':
    case 'progressing': return 'bg-warning';
    case 'failed':
    case 'error': return 'bg-destructive';
    default: return 'bg-muted-foreground';
  }
}

function hasWarning(statusMessage?: string): boolean {
  if (!statusMessage) return false;
  const lower = statusMessage.toLowerCase();
  return lower.includes('error') || lower.includes('warning') || lower.includes('fail') || lower.includes('crash');
}

export function ResourceNode({ data, onEdit }: { data: ResourceNodeData; onEdit?: (data: ResourceNodeData) => void }) {
  const navigate = useNavigate();
  const zoom = useContext(VisualMapZoomContext);
  const isCompact = useContext(VisualMapCompactContext);
  const config = RESOURCE_CONFIG[data.resourceType];
  const Icon = config.icon;
  const route = RESOURCE_ROUTES[data.resourceType];
  const { namespace, name } = data.resource.metadata;
  const basePath = `/${route}/${namespace}/${name}`;

  const handleQuickAction = (tab: string, e: React.MouseEvent) => {
    e.stopPropagation();
    navigate(tab === 'overview' ? basePath : `${basePath}?tab=${tab}`);
  };
  const handleEdit = (e: React.MouseEvent) => {
    e.stopPropagation();
    onEdit?.(data);
  };

  const statusDot = getStatusDotColor(data.status);
  const showWarning = hasWarning(data.statusMessage);

  // All 4 handles always present so dynamic edges can connect to any side
  const handles = (
    <>
      <Handle type="target" position={Position.Top} id="top" className="!w-2 !h-2 !bg-muted-foreground/40 !border-none" />
      <Handle type="target" position={Position.Left} id="left" className="!w-2 !h-2 !bg-muted-foreground/40 !border-none" />
      <Handle type="source" position={Position.Bottom} id="bottom" className="!w-2 !h-2 !bg-muted-foreground/40 !border-none" />
      <Handle type="source" position={Position.Right} id="right" className="!w-2 !h-2 !bg-muted-foreground/40 !border-none" />
    </>
  );

  // ── Compact pill (only via toolbar toggle, NOT zoom) ──
  if (isCompact) {
    return (
      <>
        {handles}
        <div
          className={`
            flex items-center gap-2 bg-card border border-border rounded-full px-3 py-1.5
            border-l-4 ${config.colorClass}
            shadow-sm hover:shadow-md hover:border-primary/30
            transition-all duration-200
          `}
        >
          <Icon className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
          <span className="text-[10px] font-medium text-foreground truncate max-w-[120px]">{data.label}</span>
          <div className={`w-2 h-2 rounded-full ${statusDot} shrink-0`} />
        </div>
      </>
    );
  }

  // ── Full card ──
  return (
    <>
      {handles}
      <div
        className={`
          bg-card border border-border rounded-xl px-4 py-3 min-w-[200px] max-w-[240px]
          border-l-4 ${config.colorClass}
          shadow-sm hover:shadow-md hover:border-primary/30
          transition-all duration-200 group
          ${data.isHighlighted ? 'ring-2 ring-primary ring-offset-2 ring-offset-background' : ''}
        `}
        style={data.isDimmed ? { opacity: 0.15, pointerEvents: 'none' } : undefined}
      >
        <div className="absolute -top-1.5 -right-1.5 flex items-center gap-1">
          <div className={`w-3 h-3 rounded-full ${statusDot} border-2 border-card`} />
          {showWarning && <AlertTriangle className="h-3 w-3 text-warning" />}
        </div>

        <div className="flex items-center gap-2.5 mb-1.5">
          <Icon className="h-4 w-4 text-muted-foreground group-hover:text-foreground transition-colors" />
          <span className="text-sm font-semibold text-foreground truncate flex-1">{data.label}</span>
        </div>

        <div className="flex items-center justify-between gap-2 mb-2">
          <span className="text-[10px] text-muted-foreground font-mono truncate">{data.namespace}</span>
          <Badge variant={getStatusVariant(data.status)} className="text-[9px] px-1.5 py-0 h-4">
            {data.status || 'Unknown'}
          </Badge>
        </div>

        {zoom >= 1.2 && data.resource.metadata.labels && (
          <div className="border-t border-border/50 pt-1.5 mt-1 transition-opacity duration-200">
            {Object.entries(data.resource.metadata.labels).slice(0, 2).map(([k, v]) => (
              <div key={k} className="text-[9px] text-muted-foreground truncate">
                <span className="font-mono">{k}</span>: {v}
              </div>
            ))}
          </div>
        )}

        <div className="grid grid-cols-4 gap-0 mt-1.5 border-t border-border/50 pt-1.5">
          {[...config.quickActions.map((qa) => {
            const QAIcon = ICON_MAP[qa.icon];
            return (
              <Tooltip key={qa.tab} delayDuration={600}>
                <TooltipTrigger asChild>
                  <button
                    onClick={(e) => handleQuickAction(qa.tab, e)}
                    className="p-1.5 rounded-lg text-muted-foreground transition-all duration-300 ease-out hover:scale-[2] hover:text-[hsl(180_100%_80%)] hover:bg-[linear-gradient(135deg,hsl(270_80%_60%/0.25),hsl(190_100%_50%/0.25))] hover:shadow-[0_0_12px_hsl(270_80%_60%/0.5),0_0_24px_hsl(190_100%_50%/0.3)] hover:z-10 relative flex items-center justify-center"
                  >
                    <QAIcon className="h-3.5 w-3.5" />
                  </button>
                </TooltipTrigger>
                <TooltipContent side="bottom" className="text-sm px-3 py-1.5 font-medium">{qa.label}</TooltipContent>
              </Tooltip>
            );
          }),
          // Fill empty slots then edit as last column
          ...Array.from({ length: 3 - config.quickActions.length }, (_, i) => (
            <div key={`spacer-${i}`} />
          )),
          <Tooltip key="edit" delayDuration={600}>
            <TooltipTrigger asChild>
              <button
                onClick={handleEdit}
                className="p-1.5 rounded-lg text-muted-foreground transition-all duration-300 ease-out hover:scale-[2] hover:text-[hsl(180_100%_80%)] hover:bg-[linear-gradient(135deg,hsl(270_80%_60%/0.25),hsl(190_100%_50%/0.25))] hover:shadow-[0_0_12px_hsl(270_80%_60%/0.5),0_0_24px_hsl(190_100%_50%/0.3)] hover:z-10 relative flex items-center justify-center"
              >
                <Pencil className="h-3.5 w-3.5" />
              </button>
            </TooltipTrigger>
            <TooltipContent side="bottom" className="text-sm px-3 py-1.5 font-medium">Edit</TooltipContent>
          </Tooltip>]}
        </div>
      </div>
    </>
  );
}
