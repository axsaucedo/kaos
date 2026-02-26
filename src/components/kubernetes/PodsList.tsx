import React from 'react';
import { useNavigate } from 'react-router-dom';
import { Boxes, Network, RefreshCw, Eye } from 'lucide-react';
import { useKubernetesStore } from '@/stores/kubernetesStore';
import { useKubernetesConnection } from '@/contexts/KubernetesConnectionContext';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import type { Pod } from '@/types/kubernetes';

export function PodsList() {
  const navigate = useNavigate();
  const { pods } = useKubernetesStore();
  const { refreshAll } = useKubernetesConnection();

  const handleViewDetails = (pod: Pod, e: React.MouseEvent) => {
    e.stopPropagation();
    const ns = pod.metadata.namespace || 'default';
    navigate(`/pods/${ns}/${pod.metadata.name}?tab=logs`);
  };

  const handlePodClick = (pod: Pod) => {
    const ns = pod.metadata.namespace || 'default';
    navigate(`/pods/${ns}/${pod.metadata.name}`);
  };

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <div className="h-12 w-12 rounded-xl bg-pod/10 flex items-center justify-center">
            <Boxes className="h-6 w-6 text-pod" />
          </div>
          <div>
            <h1 className="text-2xl font-bold text-foreground">Pods</h1>
            <p className="text-muted-foreground">View and manage Kubernetes pods</p>
          </div>
        </div>
        <Button variant="outline" className="gap-2" onClick={() => refreshAll()}>
          <RefreshCw className="h-4 w-4" />
          Refresh
        </Button>
      </div>

      {/* Pods Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {pods.map((pod) => (
          <div
            key={pod.metadata.name}
            className="bg-card rounded-xl border border-border p-4 hover:border-primary/30 transition-all cursor-pointer group"
            onClick={() => handlePodClick(pod)}
          >
            <div className="flex items-start justify-between mb-3">
              <div className="flex items-center gap-3">
                <div className="h-10 w-10 rounded-lg bg-pod/20 flex items-center justify-center">
                  <Boxes className="h-5 w-5 text-pod" />
                </div>
                <div>
                  <p className="text-sm font-semibold text-foreground truncate max-w-[150px]">
                    {pod.metadata.name}
                  </p>
                  <p className="text-xs text-muted-foreground font-mono">{pod.metadata.namespace}</p>
                </div>
              </div>
              <Badge
                variant={
                  pod.status?.phase === 'Running' ? 'success' : 
                  pod.status?.phase === 'Pending' ? 'warning' : 'destructive'
                }
              >
                {pod.status?.phase}
              </Badge>
            </div>

            <div className="space-y-2 text-xs">
              <div className="flex items-center justify-between text-muted-foreground">
                <span className="flex items-center gap-1">
                  <Network className="h-3 w-3" />
                  Pod IP
                </span>
                <span className="font-mono">{pod.status?.podIP || '-'}</span>
              </div>
              <div className="flex items-center justify-between text-muted-foreground">
                <span>Host IP</span>
                <span className="font-mono">{pod.status?.hostIP || '-'}</span>
              </div>
              <div className="flex items-center justify-between text-muted-foreground">
                <span>Containers</span>
                <span>{pod.spec.containers.length}</span>
              </div>
            </div>

            <div className="mt-3 pt-3 border-t border-border flex gap-2">
              {pod.spec.containers.map((container) => (
                <Badge key={container.name} variant="outline" className="text-[10px]">
                  {container.name}
                </Badge>
              ))}
            </div>

            <div className="mt-3 opacity-0 group-hover:opacity-100 transition-opacity">
              <Button 
                variant="outline" 
                size="sm" 
                className="w-full gap-1"
                onClick={(e) => handleViewDetails(pod, e)}
                title="View pod details and logs"
              >
                <Eye className="h-3 w-3" />
                View Details
              </Button>
            </div>
          </div>
        ))}
      </div>

      {pods.length === 0 && (
        <div className="text-center py-12">
          <Boxes className="h-12 w-12 mx-auto text-muted-foreground/50 mb-4" />
          <p className="text-muted-foreground">No pods found</p>
        </div>
      )}
    </div>
  );
}
