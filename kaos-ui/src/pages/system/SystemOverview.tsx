import React from 'react';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import type { Pod, Deployment } from '@/types/kubernetes';

interface SystemOverviewProps {
  operatorDeployments: Deployment[];
  operatorPods: Pod[];
  selectedPod: Pod | null;
  onSelectPod: (pod: Pod) => void;
  kaosNamespace: string;
}

export default function SystemOverview({
  operatorDeployments,
  operatorPods,
  selectedPod,
  onSelectPod,
  kaosNamespace,
}: SystemOverviewProps) {
  return (
    <>
      {/* Operator Status */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Operator Status</CardTitle>
          <CardDescription>KAOS controller manager health</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {operatorDeployments.map((deployment) => (
            <div key={deployment.metadata.name} className="p-3 bg-muted/50 rounded-lg">
              <div className="flex items-center justify-between mb-2">
                <span className="font-medium">{deployment.metadata.name}</span>
                <Badge variant={
                  deployment.status?.readyReplicas === deployment.status?.replicas ? 'success' : 'warning'
                }>
                  {deployment.status?.readyReplicas || 0}/{deployment.status?.replicas || 0} Ready
                </Badge>
              </div>
              <p className="text-xs text-muted-foreground">
                Replicas: {deployment.spec.replicas}
              </p>
            </div>
          ))}
          {operatorDeployments.length === 0 && (
            <p className="text-sm text-muted-foreground italic">No deployments found</p>
          )}
        </CardContent>
      </Card>

      {/* Pods Summary */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Running Pods</CardTitle>
          <CardDescription>KAOS system pods in {kaosNamespace}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-2">
          {operatorPods.map((pod) => (
            <div
              key={pod.metadata.name}
              className={`p-3 rounded-lg cursor-pointer transition-colors ${
                selectedPod?.metadata.name === pod.metadata.name
                  ? 'bg-primary/10 border border-primary/20'
                  : 'bg-muted/50 hover:bg-muted'
              }`}
              onClick={() => onSelectPod(pod)}
            >
              <div className="flex items-center justify-between">
                <span className="font-mono text-sm">{pod.metadata.name}</span>
                <Badge variant={pod.status?.phase === 'Running' ? 'success' : 'warning'}>
                  {pod.status?.phase}
                </Badge>
              </div>
            </div>
          ))}
        </CardContent>
      </Card>
    </>
  );
}
