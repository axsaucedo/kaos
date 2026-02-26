import React, { useMemo } from 'react';
import type { ModelAPI, MCPServer, Agent, DeploymentStatusInfo } from '@/types/kubernetes';

interface ResourceStatusLegendProps {
  modelAPIs: ModelAPI[];
  mcpServers: MCPServer[];
  agents: Agent[];
}

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

function countStatuses(resources: (ModelAPI | MCPServer | Agent)[]) {
  let ready = 0, pending = 0, failed = 0;
  resources.forEach((r) => {
    const s = computeEffectiveStatus(r).toLowerCase();
    if (s === 'ready' || s === 'running') ready++;
    else if (s === 'failed' || s === 'error') failed++;
    else pending++;
  });
  return { ready, pending, failed };
}

function StatusBubble({ count, variant }: { count: number; variant: 'success' | 'warning' | 'destructive' }) {
  const styles: Record<string, React.CSSProperties> = {
    success: { backgroundColor: 'hsl(152 70% 32%)', color: 'hsl(152 80% 80%)' },
    warning: { backgroundColor: 'hsl(35 65% 30%)', color: 'hsl(38 90% 72%)' },
    destructive: { backgroundColor: 'hsl(0 55% 32%)', color: 'hsl(0 80% 78%)' },
  };
  return (
    <span
      className="inline-flex items-center justify-center min-w-[18px] h-[18px] px-1 rounded-full text-[9px] font-bold"
      style={styles[variant]}
    >
      {count}
    </span>
  );
}

export function ResourceStatusLegend({ modelAPIs, mcpServers, agents }: ResourceStatusLegendProps) {
  const rows = useMemo(() => [
    { label: 'Agents', colorVar: '--agent-color', ...countStatuses(agents) },
    { label: 'MCP Servers', colorVar: '--mcpserver-color', ...countStatuses(mcpServers) },
    { label: 'Model APIs', colorVar: '--modelapi-color', ...countStatuses(modelAPIs) },
  ], [modelAPIs, mcpServers, agents]);

  return (
    <div className="absolute bottom-3 left-14 z-10 opacity-40 hover:opacity-100 transition-opacity duration-300">
      <div className="bg-card/90 backdrop-blur-sm border border-border rounded-lg px-3 py-2 shadow-sm">
        <div className="flex flex-col gap-1.5">
          {rows.map((row) => (
            <div key={row.label} className="flex items-center gap-2">
              <span
                className="w-2 h-2 rounded-full shrink-0"
                style={{ backgroundColor: `hsl(var(${row.colorVar}))` }}
              />
              <span className="text-[10px] text-muted-foreground w-[70px] truncate">{row.label}</span>
              <div className="flex items-center gap-1">
                <StatusBubble count={row.ready} variant="success" />
                <StatusBubble count={row.pending} variant="warning" />
                <StatusBubble count={row.failed} variant="destructive" />
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
