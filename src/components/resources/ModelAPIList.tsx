import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Box } from 'lucide-react';
import { ResourceList, DeploymentAwareStatus } from '@/components/resources/ResourceList';
import { ModelAPICreateDialog } from '@/components/resources/ModelAPICreateDialog';
import { useKubernetesStore } from '@/stores/kubernetesStore';
import { useKubernetesConnection } from '@/contexts/KubernetesConnectionContext';
import { Badge } from '@/components/ui/badge';
import type { ModelAPI } from '@/types/kubernetes';

const getDeploymentAwareStatus = (item: ModelAPI): DeploymentAwareStatus => {
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

export function ModelAPIList() {
  const navigate = useNavigate();
  const { modelAPIs, setSelectedResource, setSelectedResourceMode } = useKubernetesStore();
  const { deleteModelAPI } = useKubernetesConnection();
  const [createDialogOpen, setCreateDialogOpen] = useState(false);

  const columns = [
    {
      key: 'name',
      header: 'Name',
      render: (item: ModelAPI) => (
        <div className="flex items-center gap-3">
          <div className="h-8 w-8 rounded-lg bg-modelapi/20 flex items-center justify-center">
            <Box className="h-4 w-4 text-modelapi" />
          </div>
          <div>
            <p className="text-sm font-medium text-foreground">{item.metadata.name}</p>
            <p className="text-xs text-muted-foreground font-mono">{item.metadata.namespace}</p>
          </div>
        </div>
      ),
    },
    {
      key: 'mode',
      header: 'Mode',
      render: (item: ModelAPI) => (
        <Badge variant={item.spec.mode === 'Proxy' ? 'secondary' : 'outline'}>
          {item.spec.mode}
        </Badge>
      ),
    },
    {
      key: 'created',
      header: 'Created',
      render: (item: ModelAPI) => (
        <span className="text-sm text-muted-foreground">
          {item.metadata.creationTimestamp
            ? new Date(item.metadata.creationTimestamp).toLocaleDateString()
            : '-'}
        </span>
      ),
    },
  ];

  const handleView = (item: ModelAPI) => {
    const ns = item.metadata.namespace || 'default';
    navigate(`/modelapis/${ns}/${item.metadata.name}`);
  };

  const handleEdit = (item: ModelAPI) => {
    setSelectedResource(item);
    setSelectedResourceMode('edit');
  };

  return (
    <>
      <ResourceList
        title="Model APIs"
        description="Manage LiteLLM proxy and vLLM hosted model endpoints"
        items={modelAPIs}
        columns={columns}
        icon={Box}
        iconColor="modelapi-color"
        onAdd={() => setCreateDialogOpen(true)}
        onView={handleView}
        onEdit={handleEdit}
        onDelete={(item) => deleteModelAPI(item.metadata.name)}
        getStatus={getDeploymentAwareStatus}
        getItemId={(item) => item.metadata.name}
      />
      <ModelAPICreateDialog 
        open={createDialogOpen} 
        onClose={() => setCreateDialogOpen(false)} 
      />
    </>
  );
}
