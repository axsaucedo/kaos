import React from 'react';
import { useNavigate } from 'react-router-dom';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { ScrollArea } from '@/components/ui/scroll-area';
import { useKubernetesStore } from '@/stores/kubernetesStore';
import { getPodStatusInfo } from '@/lib/status-utils';
import type { Agent, MCPServer, ModelAPI, Pod } from '@/types/kubernetes';
import { Box, CheckCircle, AlertCircle, Clock, RefreshCw, XCircle, Cpu, Server, Eye } from 'lucide-react';
import { cn } from '@/lib/utils';

type ResourceType = 'Agent' | 'MCPServer' | 'ModelAPI';

interface ResourcePodsProps {
  resourceType: ResourceType;
  resource: Agent | MCPServer | ModelAPI;
  namespace: string;
  name: string;
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

const RESOURCE_CONFIG: Record<ResourceType, {
  labelKey: string;
  prefix: string;
  routePrefix: string;
  colorClass: string;
  icon: React.ReactNode;
  tableIcon: React.ReactNode;
  serviceLabel: string;
}> = {
  Agent: {
    labelKey: 'agent',
    prefix: 'agent-',
    routePrefix: 'agents',
    colorClass: 'text-agent',
    icon: <Box className="h-4 w-4 text-agent" />,
    tableIcon: <Box className="h-4 w-4 text-agent" />,
    serviceLabel: 'agent',
  },
  MCPServer: {
    labelKey: 'mcpserver',
    prefix: 'mcpserver-',
    routePrefix: 'mcpservers',
    colorClass: 'text-mcpserver',
    icon: <Box className="h-4 w-4 text-mcpserver" />,
    tableIcon: <Server className="h-4 w-4 text-mcpserver" />,
    serviceLabel: 'MCP server',
  },
  ModelAPI: {
    labelKey: 'modelapi',
    prefix: 'modelapi-',
    routePrefix: 'modelapis',
    colorClass: 'text-modelapi',
    icon: <Box className="h-4 w-4 text-modelapi" />,
    tableIcon: <Cpu className="h-4 w-4 text-modelapi" />,
    serviceLabel: 'Model API',
  },
};

function getSecondaryCardContent(resourceType: ResourceType, resource: Agent | MCPServer | ModelAPI) {
  switch (resourceType) {
    case 'Agent': {
      const agent = resource as Agent;
      return {
        icon: <Server className="h-4 w-4 text-primary" />,
        title: 'Model',
        value: agent.spec.model || 'Unknown',
        description: 'Model used by agent',
      };
    }
    case 'MCPServer': {
      const mcp = resource as MCPServer;
      return {
        icon: <Server className="h-4 w-4 text-primary" />,
        title: 'Type/Runtime',
        value: mcp.spec.runtime || mcp.spec.type || 'Unknown',
        description: 'MCP Server Type',
      };
    }
    case 'ModelAPI': {
      const api = resource as ModelAPI;
      return {
        icon: <Cpu className="h-4 w-4 text-primary" />,
        title: 'Mode',
        value: api.spec.mode,
        description: 'Model API Mode',
      };
    }
  }
}

export function ResourcePods({ resourceType, resource, namespace, name }: ResourcePodsProps) {
  const navigate = useNavigate();
  const { pods, deployments, services } = useKubernetesStore();
  const config = RESOURCE_CONFIG[resourceType];

  // Find pods for this resource
  const resourcePods = pods.filter(pod => {
    const labels = pod.metadata.labels || {};
    const podName = pod.metadata.name.toLowerCase();
    const resourceNameLower = name.toLowerCase();

    return (
      podName.includes(`${config.prefix}${resourceNameLower}`) ||
      labels[config.labelKey] === name ||
      labels['app.kubernetes.io/name'] === `${config.prefix}${name}`
    );
  });

  // Calculate stats
  const totalPods = resourcePods.length;
  const runningPods = resourcePods.filter(p => p.status?.phase === 'Running').length;
  const hasIssues = resourcePods.some(p =>
    p.status?.phase !== 'Running' ||
    getRestartCount(p) > 0
  );

  // Find related deployment
  const resourceDeployment = deployments.find(d =>
    d.metadata.name.includes(`${config.prefix}${name}`) ||
    d.metadata.labels?.[config.labelKey] === name
  );

  // Find related service
  const resourceService = services.find(s =>
    s.metadata.name.includes(`${config.prefix}${name}`) ||
    s.metadata.labels?.[config.labelKey] === name
  );

  const handlePodClick = (pod: Pod) => {
    const returnPath = encodeURIComponent(`/${config.routePrefix}/${namespace}/${name}?tab=pods`);
    navigate(`/pods/${pod.metadata.namespace || 'default'}/${pod.metadata.name}?tab=logs&returnTo=${returnPath}`);
  };

  const secondaryCard = getSecondaryCardContent(resourceType, resource);

  return (
    <div className="space-y-6">
      {/* Summary Cards */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium flex items-center gap-2">
              {config.icon}
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
              {secondaryCard.icon}
              {secondaryCard.title}
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{secondaryCard.value}</div>
            <p className="text-xs text-muted-foreground">{secondaryCard.description}</p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium flex items-center gap-2">
              <RefreshCw className={cn("h-4 w-4", config.colorClass)} />
              Deployment
            </CardTitle>
          </CardHeader>
          <CardContent>
            {resourceDeployment ? (
              <>
                <div className="text-2xl font-bold">
                  {resourceDeployment.status?.readyReplicas || 0}/{resourceDeployment.spec?.replicas || 1}
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
      {resourceService && (
        <Card>
          <CardHeader>
            <CardTitle className="text-sm font-medium">Service Endpoint</CardTitle>
            <CardDescription>Internal cluster endpoint for this {config.serviceLabel}</CardDescription>
          </CardHeader>
          <CardContent>
            <code className="text-sm font-mono bg-muted px-2 py-1 rounded">
              {resourceService.metadata.name}.{resourceService.metadata.namespace}.svc.cluster.local:
              {resourceService.spec?.ports?.[0]?.port || 8000}
            </code>
          </CardContent>
        </Card>
      )}

      {/* Pods Table */}
      <Card>
        <CardHeader>
          <CardTitle className="text-sm font-medium flex items-center gap-2">
            {config.tableIcon}
            <span>{resourceType}:</span>
            <span className="font-mono">{name}</span>
            <Badge variant="outline" className="ml-2">
              {resourcePods.length} pod{resourcePods.length !== 1 ? 's' : ''}
            </Badge>
          </CardTitle>
          <CardDescription>
            Click on a pod to view its logs
          </CardDescription>
        </CardHeader>
        <CardContent>
          {resourcePods.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-8 text-center">
              <AlertCircle className="h-8 w-8 text-muted-foreground mb-2" />
              <p className="text-sm text-muted-foreground">
                No pods found for this {config.serviceLabel}
              </p>
              <p className="text-xs text-muted-foreground mt-1">
                The resource may not be deployed or pods are in another namespace
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
                  {resourcePods.map((pod) => {
                    const { ready, total } = getContainerStatus(pod);
                    const restarts = getRestartCount(pod);
                    const podCondition = getPodStatusInfo(pod);
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
