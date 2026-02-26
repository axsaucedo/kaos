import React from 'react';
import { HardDrive, RefreshCw, Scale, CheckCircle2, AlertCircle } from 'lucide-react';
import { useKubernetesStore } from '@/stores/kubernetesStore';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import type { Deployment } from '@/types/kubernetes';

export function DeploymentsList() {
  const { deployments, setSelectedResource } = useKubernetesStore();

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <div className="h-12 w-12 rounded-xl bg-deployment/10 flex items-center justify-center">
            <HardDrive className="h-6 w-6 text-deployment" />
          </div>
          <div>
            <h1 className="text-2xl font-bold text-foreground">Deployments</h1>
            <p className="text-muted-foreground">View and manage Kubernetes deployments</p>
          </div>
        </div>
        <Button variant="outline" className="gap-2">
          <RefreshCw className="h-4 w-4" />
          Refresh
        </Button>
      </div>

      {/* Deployments List */}
      <div className="space-y-4">
        {deployments.map((deployment) => {
          const isHealthy = deployment.status?.readyReplicas === deployment.status?.replicas;
          
          return (
            <div
              key={deployment.metadata.name}
              className="bg-card rounded-xl border border-border p-5 hover:border-primary/30 transition-all cursor-pointer"
              onClick={() => setSelectedResource(deployment)}
            >
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-4">
                  <div className="h-12 w-12 rounded-xl bg-deployment/20 flex items-center justify-center">
                    <HardDrive className="h-6 w-6 text-deployment" />
                  </div>
                  <div>
                    <p className="text-lg font-semibold text-foreground">{deployment.metadata.name}</p>
                    <p className="text-sm text-muted-foreground font-mono">{deployment.metadata.namespace}</p>
                  </div>
                </div>

                <div className="flex items-center gap-6">
                  {/* Replicas */}
                  <div className="text-center">
                    <div className="flex items-center gap-2">
                      <Scale className="h-4 w-4 text-muted-foreground" />
                      <span className="text-2xl font-bold text-foreground">
                        {deployment.status?.readyReplicas || 0}/{deployment.status?.replicas || 0}
                      </span>
                    </div>
                    <p className="text-xs text-muted-foreground">Replicas</p>
                  </div>

                  {/* Status */}
                  <div className="flex items-center gap-2">
                    {isHealthy ? (
                      <CheckCircle2 className="h-5 w-5 text-success" />
                    ) : (
                      <AlertCircle className="h-5 w-5 text-warning" />
                    )}
                    <Badge variant={isHealthy ? 'success' : 'warning'}>
                      {isHealthy ? 'Healthy' : 'Degraded'}
                    </Badge>
                  </div>
                </div>
              </div>

              {/* Labels */}
              <div className="mt-4 pt-4 border-t border-border">
                <p className="text-xs text-muted-foreground mb-2">Selector</p>
                <div className="flex flex-wrap gap-2">
                  {Object.entries(deployment.spec.selector.matchLabels).map(([key, value]) => (
                    <Badge key={key} variant="outline" className="font-mono text-[10px]">
                      {key}={value}
                    </Badge>
                  ))}
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {deployments.length === 0 && (
        <div className="text-center py-12">
          <HardDrive className="h-12 w-12 mx-auto text-muted-foreground/50 mb-4" />
          <p className="text-muted-foreground">No deployments found</p>
        </div>
      )}
    </div>
  );
}
