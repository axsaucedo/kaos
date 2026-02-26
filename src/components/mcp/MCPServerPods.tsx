import React from 'react';
import { useNavigate } from 'react-router-dom';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { ScrollArea } from '@/components/ui/scroll-area';
import { useKubernetesStore } from '@/stores/kubernetesStore';
import type { MCPServer, Pod } from '@/types/kubernetes';
import { Box, CheckCircle, AlertCircle, Clock, RefreshCw, XCircle, Server, Eye } from 'lucide-react';
import { cn } from '@/lib/utils';

interface MCPServerPodsProps {
  mcpServer: MCPServer;
}

function getContainerStatus(pod: Pod) {
  const containerStatuses = pod.status?.containerStatuses || [];
  const ready = containerStatuses.filter(c => c.ready).length;
  const total = containerStatuses.length;
  return { ready, total };
}

function getRestartCount(pod: Pod): number {
  const containerStatuses = pod.status?.containerStatuses || [];
  return containerStatuses.reduce((sum, c) => sum + (c.restartCount || 0), 0);
}

function getAge(timestamp?: string): string {
  if (!timestamp) return 'Unknown';
  const created = new Date(timestamp);
  const now = new Date();
  const diffMs = now.getTime() - created.getTime();
  const diffMins = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMins / 60);
  const diffDays = Math.floor(diffHours / 24);

  if (diffDays > 0) return `${diffDays}d`;
  if (diffHours > 0) return `${diffHours}h`;
  if (diffMins > 0) return `${diffMins}m`;
  return '<1m';
}

function getPodCondition(pod: Pod): { status: string; isRolling: boolean; isTerminating: boolean } {
  const phase = pod.status?.phase || 'Unknown';
  const deletionTimestamp = pod.metadata.deletionTimestamp;
  const containerStatuses = pod.status?.containerStatuses || [];
  
  if (deletionTimestamp) {
    return { status: 'Terminating', isRolling: true, isTerminating: true };
  }
  
  const notReady = containerStatuses.some(c => !c.ready);
  if (phase === 'Running' && notReady) {
    return { status: 'ContainerNotReady', isRolling: true, isTerminating: false };
  }
  
  if (phase === 'Pending') {
    const containerWaiting = containerStatuses.find(c => c.state?.waiting);
    const reason = containerWaiting?.state?.waiting?.reason || 'Pending';
    return { status: reason, isRolling: true, isTerminating: false };
  }
  
  return { status: phase, isRolling: false, isTerminating: false };
}

function getPodStatusIcon(phase: string, isRolling: boolean, isTerminating: boolean) {
  if (isTerminating) {
    return <XCircle className="h-4 w-4 text-orange-500" />;
  }
  if (isRolling) {
    return <RefreshCw className="h-4 w-4 text-yellow-500 animate-spin" />;
  }
  switch (phase?.toLowerCase()) {
    case 'running':
      return <CheckCircle className="h-4 w-4 text-green-500" />;
    case 'pending':
      return <Clock className="h-4 w-4 text-yellow-500" />;
    case 'succeeded':
      return <CheckCircle className="h-4 w-4 text-blue-500" />;
    case 'failed':
      return <XCircle className="h-4 w-4 text-red-500" />;
    default:
      return <AlertCircle className="h-4 w-4 text-muted-foreground" />;
  }
}

function getPodStatusColor(phase: string, isRolling: boolean, isTerminating: boolean): string {
  if (isTerminating) return 'text-orange-500';
  if (isRolling) return 'text-yellow-500';
  switch (phase?.toLowerCase()) {
    case 'running':
      return 'text-green-500';
    case 'pending':
      return 'text-yellow-500';
    case 'succeeded':
      return 'text-blue-500';
    case 'failed':
      return 'text-red-500';
    default:
      return 'text-muted-foreground';
  }
}

export function MCPServerPods({ mcpServer }: MCPServerPodsProps) {
  const navigate = useNavigate();
  const { pods, deployments, services } = useKubernetesStore();

  // Find pods for the MCPServer
  const serverPods = pods.filter(pod => {
    const labels = pod.metadata.labels || {};
    const name = pod.metadata.name.toLowerCase();
    const resourceNameLower = mcpServer.metadata.name.toLowerCase();
    
    return (
      name.includes(`mcpserver-${resourceNameLower}`) ||
      labels.mcpserver === mcpServer.metadata.name ||
      labels['app.kubernetes.io/name'] === `mcpserver-${mcpServer.metadata.name}`
    );
  });

  // Calculate stats
  const totalPods = serverPods.length;
  const runningPods = serverPods.filter(p => p.status?.phase === 'Running').length;
  const hasIssues = serverPods.some(p => 
    p.status?.phase !== 'Running' || 
    getRestartCount(p) > 0
  );

  // Find related deployment
  const serverDeployment = deployments.find(d => 
    d.metadata.name.includes(`mcpserver-${mcpServer.metadata.name}`) ||
    d.metadata.labels?.mcpserver === mcpServer.metadata.name
  );

  // Find related service
  const serverService = services.find(s => 
    s.metadata.name.includes(`mcpserver-${mcpServer.metadata.name}`) ||
    s.metadata.labels?.mcpserver === mcpServer.metadata.name
  );

  const handlePodClick = (pod: Pod) => {
    const ns = mcpServer.metadata.namespace || 'default';
    const returnPath = encodeURIComponent(`/mcpservers/${ns}/${mcpServer.metadata.name}?tab=pods`);
    navigate(`/pods/${pod.metadata.namespace || 'default'}/${pod.metadata.name}?tab=logs&returnTo=${returnPath}`);
  };

  return (
    <div className="space-y-6">
      {/* Summary Cards */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium flex items-center gap-2">
              <Box className="h-4 w-4 text-mcpserver" />
              Total Pods
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{totalPods}</div>
            <p className="text-xs text-muted-foreground">
              {runningPods} running
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium flex items-center gap-2">
              <Server className="h-4 w-4 text-primary" />
              Type/Runtime
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{mcpServer.spec.runtime || mcpServer.spec.type || 'Unknown'}</div>
            <p className="text-xs text-muted-foreground">MCP Server Type</p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium flex items-center gap-2">
              <RefreshCw className="h-4 w-4 text-mcpserver" />
              Deployment
            </CardTitle>
          </CardHeader>
          <CardContent>
            {serverDeployment ? (
              <>
                <div className="text-2xl font-bold">
                  {serverDeployment.status?.readyReplicas || 0}/{serverDeployment.spec?.replicas || 1}
                </div>
                <p className="text-xs text-muted-foreground">replicas ready</p>
              </>
            ) : (
              <div className="text-sm text-muted-foreground">Not found</div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium flex items-center gap-2">
              {hasIssues ? (
                <AlertCircle className="h-4 w-4 text-yellow-500" />
              ) : (
                <CheckCircle className="h-4 w-4 text-green-500" />
              )}
              Health
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className={cn(
              "text-2xl font-bold",
              hasIssues ? "text-yellow-500" : "text-green-500"
            )}>
              {hasIssues ? 'Warning' : 'Healthy'}
            </div>
            <p className="text-xs text-muted-foreground">
              {hasIssues ? 'Check pod status below' : 'All systems operational'}
            </p>
          </CardContent>
        </Card>
      </div>

      {/* Service Info */}
      {serverService && (
        <Card>
          <CardHeader>
            <CardTitle className="text-sm font-medium">Service Endpoint</CardTitle>
            <CardDescription>Internal cluster endpoint for this MCP server</CardDescription>
          </CardHeader>
          <CardContent>
            <code className="text-sm font-mono bg-muted px-2 py-1 rounded">
              {serverService.metadata.name}.{serverService.metadata.namespace}.svc.cluster.local:
              {serverService.spec?.ports?.[0]?.port || 8000}
            </code>
          </CardContent>
        </Card>
      )}

      {/* Pods Table */}
      <Card>
        <CardHeader>
          <CardTitle className="text-sm font-medium flex items-center gap-2">
            <Server className="h-4 w-4 text-mcpserver" />
            <span>MCPServer:</span>
            <span className="font-mono">{mcpServer.metadata.name}</span>
            <Badge variant="outline" className="ml-2">
              {serverPods.length} pod{serverPods.length !== 1 ? 's' : ''}
            </Badge>
          </CardTitle>
          <CardDescription>Click on a pod to view its logs</CardDescription>
        </CardHeader>
        <CardContent>
          {serverPods.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-8 text-center">
              <AlertCircle className="h-8 w-8 text-muted-foreground mb-2" />
              <p className="text-sm text-muted-foreground">
                No pods found for this MCP server
              </p>
              <p className="text-xs text-muted-foreground mt-1">
                The server may not be deployed or pods are in another namespace
              </p>
            </div>
          ) : (
            <ScrollArea className="max-h-[400px]">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Name</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Ready</TableHead>
                    <TableHead>Restarts</TableHead>
                    <TableHead>Age</TableHead>
                    <TableHead>Host IP</TableHead>
                    <TableHead className="w-10"></TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {serverPods.map((pod) => {
                    const { ready, total } = getContainerStatus(pod);
                    const restarts = getRestartCount(pod);
                    const podCondition = getPodCondition(pod);
                    return (
                      <TableRow 
                        key={pod.metadata.uid} 
                        className="cursor-pointer hover:bg-muted/50 transition-colors"
                        onClick={() => handlePodClick(pod)}
                      >
                        <TableCell className="font-mono text-xs">
                          {pod.metadata.name}
                        </TableCell>
                        <TableCell>
                          <div className="flex items-center gap-2">
                            {getPodStatusIcon(podCondition.status, podCondition.isRolling, podCondition.isTerminating)}
                            <span className={cn(
                              "text-sm",
                              getPodStatusColor(podCondition.status, podCondition.isRolling, podCondition.isTerminating)
                            )}>
                              {podCondition.status}
                            </span>
                            {podCondition.isRolling && !podCondition.isTerminating && (
                              <Badge variant="outline" className="text-xs text-yellow-600 border-yellow-600">
                                Rolling
                              </Badge>
                            )}
                            {podCondition.isTerminating && (
                              <Badge variant="outline" className="text-xs text-orange-600 border-orange-600">
                                Terminating
                              </Badge>
                            )}
                          </div>
                        </TableCell>
                        <TableCell>
                          <Badge variant={ready === total && total > 0 ? "success" : "secondary"}>
                            {ready}/{total}
                          </Badge>
                        </TableCell>
                        <TableCell>
                          <span className={cn(
                            restarts > 0 ? "text-yellow-500" : "text-muted-foreground"
                          )}>
                            {restarts}
                          </span>
                        </TableCell>
                        <TableCell className="text-muted-foreground">
                          {getAge(pod.metadata.creationTimestamp)}
                        </TableCell>
                        <TableCell className="text-xs text-muted-foreground">
                          {pod.status?.hostIP || '-'}
                        </TableCell>
                        <TableCell title="View pod details">
                          <Eye className="h-4 w-4 text-muted-foreground" />
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </ScrollArea>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
