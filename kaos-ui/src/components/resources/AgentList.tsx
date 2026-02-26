import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Bot, Link2 } from 'lucide-react';
import { ResourceList, DeploymentAwareStatus } from '@/components/resources/ResourceList';
import { useKubernetesStore } from '@/stores/kubernetesStore';
import { useKubernetesConnection } from '@/contexts/KubernetesConnectionContext';
import { Badge } from '@/components/ui/badge';
import { AgentCreateDialog } from '@/components/resources/AgentCreateDialog';
import type { Agent } from '@/types/kubernetes';

const getDeploymentAwareStatus = (item: Agent): DeploymentAwareStatus => {
  const deployment = item.status?.deployment;
  const phase = item.status?.phase || 'Unknown';
  
  // If we have deployment info, use it to determine the real status
  if (deployment) {
    const { replicas = 0, readyReplicas = 0, updatedReplicas = 0 } = deployment;
    
    // Check if a rolling update is in progress
    if (replicas > 0 && updatedReplicas < replicas) {
      return {
        label: 'Updating',
        variant: 'warning',
        isRolling: true,
        progress: `${updatedReplicas}/${replicas}`,
      };
    }
    
    // Check if pods are not ready
    if (replicas > 0 && readyReplicas < replicas) {
      return {
        label: 'Pending',
        variant: 'warning',
        progress: `${readyReplicas}/${replicas}`,
      };
    }
    
    // All pods ready
    if (replicas > 0 && readyReplicas === replicas) {
      return {
        label: 'Ready',
        variant: 'success',
        progress: `${readyReplicas}/${replicas}`,
      };
    }
  }
  
  // Fall back to phase-based status
  const normalizedPhase = phase.toLowerCase();
  if (normalizedPhase === 'ready' || normalizedPhase === 'running') {
    return { label: phase, variant: 'success' };
  } else if (normalizedPhase === 'pending' || normalizedPhase === 'creating') {
    return { label: phase, variant: 'warning' };
  } else if (normalizedPhase === 'error' || normalizedPhase === 'failed') {
    return { label: phase, variant: 'error' };
  }
  
  return { label: phase, variant: 'secondary' };
};

export function AgentList() {
  const navigate = useNavigate();
  const { agents, setSelectedResource, setSelectedResourceMode } = useKubernetesStore();
  const { deleteAgent } = useKubernetesConnection();
  const [createDialogOpen, setCreateDialogOpen] = useState(false);

  const columns = [
    {
      key: 'name',
      header: 'Name',
      render: (item: Agent) => (
        <div className="flex items-center gap-3">
          <div className="h-8 w-8 rounded-lg bg-agent/20 flex items-center justify-center">
            <Bot className="h-4 w-4 text-agent" />
          </div>
          <div>
            <p className="text-sm font-medium text-foreground">{item.metadata.name}</p>
            <p className="text-xs text-muted-foreground font-mono">{item.metadata.namespace}</p>
          </div>
        </div>
      ),
    },
    {
      key: 'modelAPI',
      header: 'Model API',
      render: (item: Agent) => (
        <Badge variant="modelapi">{item.spec.modelAPI}</Badge>
      ),
    },
    {
      key: 'mcpServers',
      header: 'MCP Servers',
      render: (item: Agent) => (
        <div className="flex flex-wrap gap-1">
          {item.spec.mcpServers?.slice(0, 2).map((mcp) => (
            <Badge key={mcp} variant="mcpserver" className="text-[10px]">
              {mcp}
            </Badge>
          ))}
          {(item.spec.mcpServers?.length || 0) > 2 && (
            <Badge variant="secondary" className="text-[10px]">
              +{(item.spec.mcpServers?.length || 0) - 2}
            </Badge>
          )}
        </div>
      ),
    },
    {
      key: 'network',
      header: 'Network',
      render: (item: Agent) => (
        <div className="flex items-center gap-2">
          {item.spec.agentNetwork?.expose ? (
            <Badge variant="success" className="gap-1">
              <Link2 className="h-3 w-3" />
              Exposed
            </Badge>
          ) : (
            <Badge variant="secondary">Private</Badge>
          )}
          {item.spec.agentNetwork?.access && item.spec.agentNetwork.access.length > 0 && (
            <span className="text-xs text-muted-foreground">
              {item.spec.agentNetwork.access.length} peers
            </span>
          )}
        </div>
      ),
    },
  ];

  const handleView = (item: Agent) => {
    navigate(`/agents/${item.metadata.namespace || 'default'}/${item.metadata.name}`);
  };

  const handleEdit = (item: Agent) => {
    setSelectedResource(item);
    setSelectedResourceMode('edit');
  };

  return (
    <>
      <ResourceList
        title="Agents"
        description="ADK-based agents with multi-agent communication support"
        items={agents}
        columns={columns}
        icon={Bot}
        iconColor="agent-color"
        onAdd={() => setCreateDialogOpen(true)}
        onView={handleView}
        onEdit={handleEdit}
        onDelete={async (item) => {
          await deleteAgent(item.metadata.name, item.metadata.namespace);
        }}
        getStatus={getDeploymentAwareStatus}
        getItemId={(item) => item.metadata.name}
      />
      
      <AgentCreateDialog 
        open={createDialogOpen} 
        onClose={() => setCreateDialogOpen(false)} 
      />
    </>
  );
}

