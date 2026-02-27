import React from 'react';
import { useNavigate } from 'react-router-dom';
import { Box, Server, Bot, Boxes, AlertCircle, CheckCircle2, Clock, Activity, ArrowRight } from 'lucide-react';
import { useKubernetesStore } from '@/stores/kubernetesStore';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';

interface StatCardProps {
  title: string;
  count: number;
  icon: React.ElementType;
  color: string;
  running: number;
  pending: number;
  error: number;
  onClick: () => void;
}

function StatCard({ title, count, icon: Icon, color, running, pending, error, onClick }: StatCardProps) {
  return (
    <div 
      className="bg-card rounded-xl border border-border p-5 hover:border-primary/30 transition-all duration-300 group cursor-pointer"
      onClick={onClick}
    >
      <div className="flex items-start justify-between mb-4">
        <div
          className={cn(
            'h-12 w-12 rounded-xl flex items-center justify-center transition-all duration-300',
            `bg-${color}/10 group-hover:bg-${color}/20`
          )}
          style={{ backgroundColor: `hsl(var(--${color}) / 0.1)` }}
        >
          <Icon className="h-6 w-6" style={{ color: `hsl(var(--${color}))` }} />
        </div>
        <Badge variant="secondary" className="text-xs">
          {count} total
        </Badge>
      </div>
      
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-lg font-semibold text-foreground">{title}</h3>
        <ArrowRight className="h-4 w-4 text-muted-foreground group-hover:text-primary transition-colors" />
      </div>
      
      <div className="flex items-center gap-3">
        <div className="flex items-center gap-1.5">
          <CheckCircle2 className="h-3.5 w-3.5 text-success" />
          <span className="text-sm text-muted-foreground">{running}</span>
        </div>
        <div className="flex items-center gap-1.5">
          <Clock className="h-3.5 w-3.5 text-warning" />
          <span className="text-sm text-muted-foreground">{pending}</span>
        </div>
        <div className="flex items-center gap-1.5">
          <AlertCircle className="h-3.5 w-3.5 text-destructive" />
          <span className="text-sm text-muted-foreground">{error}</span>
        </div>
      </div>
    </div>
  );
}

interface ResourceItemProps {
  name: string;
  namespace?: string;
  type: 'modelapi' | 'mcpserver' | 'agent' | 'pod';
  status?: string;
  icon: React.ElementType;
  onClick: () => void;
}

function ResourceItem({ name, namespace, type, status, icon: Icon, onClick }: ResourceItemProps) {
  const colors = {
    modelapi: 'modelapi',
    mcpserver: 'mcpserver',
    agent: 'agent',
    pod: 'pod-color',
  };
  
  const getStatusVariant = (s?: string) => {
    switch (s) {
      case 'Running':
      case 'Ready': return 'success';
      case 'Pending':
      case 'Waiting': return 'warning';
      case 'Error':
      case 'Failed': return 'error';
      default: return 'secondary';
    }
  };

  return (
    <div 
      className="flex items-center justify-between p-3 rounded-lg bg-muted/30 hover:bg-muted/50 cursor-pointer transition-colors"
      onClick={onClick}
    >
      <div className="flex items-center gap-3">
        <div className={`h-8 w-8 rounded-lg bg-${colors[type]}/20 flex items-center justify-center`}
          style={{ backgroundColor: `hsl(var(--${colors[type]}) / 0.2)` }}>
          <Icon className="h-4 w-4" style={{ color: `hsl(var(--${colors[type]}))` }} />
        </div>
        <div>
          <p className="text-sm font-medium text-foreground">{name}</p>
          {namespace && <p className="text-xs text-muted-foreground font-mono">{namespace}</p>}
        </div>
      </div>
      <Badge variant={getStatusVariant(status) as any}>
        {status || 'Unknown'}
      </Badge>
    </div>
  );
}

function ActivityItem({ log }: { log: any }) {
  const levelColors = {
    info: 'text-primary',
    warn: 'text-warning',
    error: 'text-destructive',
    debug: 'text-muted-foreground',
  };

  const levelIcons = {
    info: Activity,
    warn: Clock,
    error: AlertCircle,
    debug: Activity,
  };

  const Icon = levelIcons[log.level as keyof typeof levelIcons] || Activity;
  const colorClass = levelColors[log.level as keyof typeof levelColors] || 'text-muted-foreground';

  return (
    <div className="flex items-start gap-3 p-3 rounded-lg hover:bg-muted/30 transition-colors">
      <div className={cn('mt-0.5', colorClass)}>
        <Icon className="h-4 w-4" />
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-sm text-foreground truncate">{log.message}</p>
        <div className="flex items-center gap-2 mt-1">
          {log.resourceName && (
            <Badge variant="outline" className="text-[10px] px-1.5 py-0">
              {log.resourceKind}/{log.resourceName}
            </Badge>
          )}
          <span className="text-[10px] text-muted-foreground">
            {new Date(log.timestamp).toLocaleTimeString()}
          </span>
        </div>
      </div>
    </div>
  );
}

export function OverviewDashboard() {
  const navigate = useNavigate();
  const { modelAPIs, mcpServers, agents, pods, logs, setActiveTab } = useKubernetesStore();

  const getStatusCounts = (resources: any[], statusField = 'status.phase') => {
    const running = resources.filter(r => {
      const phase = r.status?.phase;
      return phase === 'Running' || phase === 'Ready';
    }).length;
    const pending = resources.filter(r => {
      const phase = r.status?.phase;
      return phase === 'Pending' || phase === 'Waiting';
    }).length;
    const error = resources.filter(r => {
      const phase = r.status?.phase;
      return phase === 'Error' || phase === 'Failed';
    }).length;
    return { running, pending, error };
  };

  const modelAPIStats = getStatusCounts(modelAPIs);
  const mcpServerStats = getStatusCounts(mcpServers);
  const agentStats = getStatusCounts(agents);
  const podStats = getStatusCounts(pods);

  const handleNavigation = (tab: string) => {
    setActiveTab(tab);
  };

  const handleResourceClick = (type: string, ns: string, name: string) => {
    switch (type) {
      case 'modelapi':
        navigate(`/modelapis/${ns}/${name}`);
        break;
      case 'mcpserver':
        navigate(`/mcpservers/${ns}/${name}`);
        break;
      case 'agent':
        navigate(`/agents/${ns}/${name}`);
        break;
      default:
        break;
    }
  };

  // Combine all resources for the summary
  const allResources = [
    ...modelAPIs.map(r => ({ ...r, resourceType: 'modelapi' as const, icon: Box })),
    ...mcpServers.map(r => ({ ...r, resourceType: 'mcpserver' as const, icon: Server })),
    ...agents.map(r => ({ ...r, resourceType: 'agent' as const, icon: Bot })),
  ].sort((a, b) => {
    const dateA = new Date(a.metadata.creationTimestamp || 0).getTime();
    const dateB = new Date(b.metadata.creationTimestamp || 0).getTime();
    return dateB - dateA;
  }).slice(0, 6);

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-foreground">Dashboard Overview</h1>
        <p className="text-muted-foreground mt-1">Monitor and manage your agentic system resources</p>
      </div>

      {/* Stats Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard
          title="Model APIs"
          count={modelAPIs.length}
          icon={Box}
          color="modelapi-color"
          {...modelAPIStats}
          onClick={() => handleNavigation('model-apis')}
        />
        <StatCard
          title="MCP Servers"
          count={mcpServers.length}
          icon={Server}
          color="mcpserver-color"
          {...mcpServerStats}
          onClick={() => handleNavigation('mcp-servers')}
        />
        <StatCard
          title="Agents"
          count={agents.length}
          icon={Bot}
          color="agent-color"
          {...agentStats}
          onClick={() => handleNavigation('agents')}
        />
        <StatCard
          title="Pods"
          count={pods.length}
          icon={Boxes}
          color="pod-color"
          {...podStats}
          onClick={() => handleNavigation('pods')}
        />
      </div>

      {/* Resource List & Activity */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Recent Resources */}
        <div className="bg-card rounded-xl border border-border p-5">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-lg font-semibold text-foreground">Recent Resources</h2>
            <Badge variant="secondary">{modelAPIs.length + mcpServers.length + agents.length} total</Badge>
          </div>
          <div className="space-y-2">
            {allResources.length > 0 ? (
              allResources.map((resource) => (
                <ResourceItem
                  key={`${resource.resourceType}-${resource.metadata.name}`}
                  name={resource.metadata.name}
                  namespace={resource.metadata.namespace}
                  type={resource.resourceType}
                  status={resource.status?.phase}
                  icon={resource.icon}
                  onClick={() => handleResourceClick(
                    resource.resourceType,
                    resource.metadata.namespace || 'default',
                    resource.metadata.name
                  )}
                />
              ))
            ) : (
              <div className="text-center py-8">
                <p className="text-muted-foreground text-sm">No resources found</p>
                <Button 
                  variant="outline" 
                  size="sm" 
                  className="mt-2"
                  onClick={() => handleNavigation('visual-editor')}
                >
                  Create Resource
                </Button>
              </div>
            )}
          </div>
        </div>

        {/* Activity Log */}
        <div className="bg-card rounded-xl border border-border p-5">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-lg font-semibold text-foreground">Recent Activity</h2>
            <Badge variant="secondary">{logs.length} events</Badge>
          </div>
          <div className="space-y-1 max-h-[300px] overflow-y-auto">
            {logs.length > 0 ? (
              logs.slice(0, 10).map((log, index) => (
                <ActivityItem key={index} log={log} />
              ))
            ) : (
              <div className="text-center py-8">
                <Activity className="h-8 w-8 mx-auto text-muted-foreground/50 mb-2" />
                <p className="text-muted-foreground text-sm">No activity yet</p>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}