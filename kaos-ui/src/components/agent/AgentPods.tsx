import React from 'react';
import { useNavigate } from 'react-router-dom';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { ScrollArea } from '@/components/ui/scroll-area';
import { useKubernetesStore } from '@/stores/kubernetesStore';
import type { Agent, Pod } from '@/types/kubernetes';
import { Box, CheckCircle, AlertCircle, Clock, RefreshCw, XCircle, Cpu, Server, Eye } from 'lucide-react';
import { cn } from '@/lib/utils';

interface AgentPodsProps {
  agent: Agent;
}

interface ResourcePodGroup {
  resourceType: 'Agent' | 'ModelAPI' | 'MCPServer';
  resourceName: string;
  pods: Pod[];
}

// Helper functions moved below with rolling update support

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

// Check if a pod is being terminated or is part of a rolling update
function getPodCondition(pod: Pod): { status: string; isRolling: boolean; isTerminating: boolean } {
  const phase = pod.status?.phase || 'Unknown';
  const deletionTimestamp = pod.metadata.deletionTimestamp;
  const containerStatuses = pod.status?.containerStatuses || [];
  
  // Pod is terminating
  if (deletionTimestamp) {
    return { status: 'Terminating', isRolling: true, isTerminating: true };
  }
  
  // Check if any container is not ready but pod is in Running phase (rolling update in progress)
  const notReady = containerStatuses.some(c => !c.ready);
  if (phase === 'Running' && notReady) {
    return { status: 'ContainerNotReady', isRolling: true, isTerminating: false };
  }
  
  // Check for pending pods (new pods coming up during rolling update)
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

function getResourceIcon(type: 'Agent' | 'ModelAPI' | 'MCPServer') {
  switch (type) {
    case 'Agent':
      return <Box className="h-4 w-4 text-agent" />;
    case 'ModelAPI':
      return <Cpu className="h-4 w-4 text-modelapi" />;
    case 'MCPServer':
      return <Server className="h-4 w-4 text-mcpserver" />;
  }
}

function getResourceBadgeVariant(type: 'Agent' | 'ModelAPI' | 'MCPServer'): 'default' | 'secondary' | 'outline' {
  return 'secondary';
}

export function AgentPods({ agent }: AgentPodsProps) {
  const navigate = useNavigate();
  const { pods, deployments, services, modelAPIs, mcpServers } = useKubernetesStore();

  // Get the ModelAPI this agent depends on
  const modelAPIName = agent.spec.modelAPI;
  const modelAPI = modelAPIs.find(m => m.metadata.name === modelAPIName);

  // Get the MCPServers this agent depends on
  const mcpServerNames = agent.spec.mcpServers || [];
  const relatedMCPServers = mcpServers.filter(m => mcpServerNames.includes(m.metadata.name));

  // Helper to find pods for a resource
  const findPodsForResource = (resourceType: string, resourceName: string): Pod[] => {
    return pods.filter(pod => {
      const labels = pod.metadata.labels || {};
      const name = pod.metadata.name.toLowerCase();
      const resourceNameLower = resourceName.toLowerCase();
      
      // Check labels first
      if (labels[resourceType.toLowerCase()] === resourceName) return true;
      
      // Check naming patterns
      if (resourceType === 'agent') {
        return name.includes(`agent-${resourceNameLower}`) || labels.agent === resourceName;
      } else if (resourceType === 'modelapi') {
        return name.includes(`modelapi-${resourceNameLower}`) || labels.modelapi === resourceName;
      } else if (resourceType === 'mcpserver') {
        return name.includes(`mcpserver-${resourceNameLower}`) || labels.mcpserver === resourceName;
      }
      return false;
    });
  };

  // Build resource groups
  const resourceGroups: ResourcePodGroup[] = [];

  // Agent pods
  const agentPods = findPodsForResource('agent', agent.metadata.name);
  resourceGroups.push({
    resourceType: 'Agent',
    resourceName: agent.metadata.name,
    pods: agentPods,
  });

  // ModelAPI pods
  if (modelAPIName) {
    const modelAPIPods = findPodsForResource('modelapi', modelAPIName);
    resourceGroups.push({
      resourceType: 'ModelAPI',
      resourceName: modelAPIName,
      pods: modelAPIPods,
    });
  }

  // MCPServer pods
  mcpServerNames.forEach(serverName => {
    const serverPods = findPodsForResource('mcpserver', serverName);
    resourceGroups.push({
      resourceType: 'MCPServer',
      resourceName: serverName,
      pods: serverPods,
    });
  });

  // Calculate totals
  const allPods = resourceGroups.flatMap(g => g.pods);
  const totalPods = allPods.length;
  const runningPods = allPods.filter(p => p.status?.phase === 'Running').length;
  const hasIssues = allPods.some(p => 
    p.status?.phase !== 'Running' || 
    getRestartCount(p) > 0
  );

  // Find related deployment
  const agentDeployment = deployments.find(d => 
    d.metadata.name.includes(`agent-${agent.metadata.name}`) ||
    d.metadata.labels?.agent === agent.metadata.name
  );

  // Find related service
  const agentService = services.find(s => 
    s.metadata.name.includes(`agent-${agent.metadata.name}`) ||
    s.metadata.labels?.agent === agent.metadata.name
  );

  const handlePodClick = (pod: Pod) => {
    // Include return path with tab=pods to return to correct tab
    const agentNs = agent.metadata.namespace || 'default';
    const returnPath = encodeURIComponent(`/agents/${agentNs}/${agent.metadata.name}?tab=pods`);
    navigate(`/pods/${pod.metadata.namespace || 'default'}/${pod.metadata.name}?tab=logs&returnTo=${returnPath}`);
  };

  return (
    <div className="space-y-6">
      {/* Summary Cards */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium flex items-center gap-2">
              <Box className="h-4 w-4 text-agent" />
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
              Resources
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{resourceGroups.length}</div>
            <p className="text-xs text-muted-foreground">
              Agent + {resourceGroups.length - 1} dependencies
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium flex items-center gap-2">
              <RefreshCw className="h-4 w-4 text-modelapi" />
              Deployment
            </CardTitle>
          </CardHeader>
          <CardContent>
            {agentDeployment ? (
              <>
                <div className="text-2xl font-bold">
                  {agentDeployment.status?.readyReplicas || 0}/{agentDeployment.spec?.replicas || 1}
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
      {agentService && (
        <Card>
          <CardHeader>
            <CardTitle className="text-sm font-medium">Service Endpoint</CardTitle>
            <CardDescription>Internal cluster endpoint for this agent</CardDescription>
          </CardHeader>
          <CardContent>
            <code className="text-sm font-mono bg-muted px-2 py-1 rounded">
              {agentService.metadata.name}.{agentService.metadata.namespace}.svc.cluster.local:
              {agentService.spec?.ports?.[0]?.port || 8000}
            </code>
          </CardContent>
        </Card>
      )}

      {/* Pods by Resource */}
      {resourceGroups.map((group) => (
        <Card key={`${group.resourceType}-${group.resourceName}`}>
          <CardHeader>
            <CardTitle className="text-sm font-medium flex items-center gap-2">
              {getResourceIcon(group.resourceType)}
              <span>{group.resourceType}:</span>
              <span className="font-mono">{group.resourceName}</span>
              <Badge variant="outline" className="ml-2">
                {group.pods.length} pod{group.pods.length !== 1 ? 's' : ''}
              </Badge>
            </CardTitle>
            <CardDescription>
              Click on a pod to view its logs
            </CardDescription>
          </CardHeader>
          <CardContent>
            {group.pods.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-8 text-center">
                <AlertCircle className="h-8 w-8 text-muted-foreground mb-2" />
                <p className="text-sm text-muted-foreground">
                  No pods found for this {group.resourceType.toLowerCase()}
                </p>
                <p className="text-xs text-muted-foreground mt-1">
                  The resource may not be deployed or pods are in another namespace
                </p>
              </div>
            ) : (
              <ScrollArea className="max-h-[300px]">
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
                    {group.pods.map((pod) => {
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
      ))}
    </div>
  );
}
