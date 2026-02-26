import React from 'react';
import { Bot, Server, Network, Clock, Tag, FileCode, Settings, Activity, Globe, Brain } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Separator } from '@/components/ui/separator';
import { DeploymentStatusCard } from '@/components/shared/DeploymentStatusCard';
import type { Agent } from '@/types/kubernetes';

interface AgentOverviewProps {
  agent: Agent;
}

export function AgentOverview({ agent }: AgentOverviewProps) {
  const { metadata, spec, status } = agent;

  const getStatusVariant = (phase?: string) => {
    switch (phase) {
      case 'Running':
      case 'Ready': return 'success';
      case 'Pending':
      case 'Waiting': return 'warning';
      case 'Error':
      case 'Failed': return 'destructive';
      default: return 'secondary';
    }
  };

  return (
    <div className="grid gap-6 md:grid-cols-2">
      {/* General Info */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2 text-base">
            <Bot className="h-4 w-4 text-agent" />
            General Information
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <InfoRow label="Name" value={<span className="font-mono">{metadata.name}</span>} />
          <InfoRow label="Namespace" value={<span className="font-mono">{metadata.namespace || 'default'}</span>} />
          <InfoRow
            label="Created"
            value={
              <span className="flex items-center gap-1">
                <Clock className="h-3 w-3" />
                {metadata.creationTimestamp
                  ? new Date(metadata.creationTimestamp).toLocaleString()
                  : 'Unknown'}
              </span>
            }
          />
          <InfoRow
            label="Status"
            value={
              <Badge variant={getStatusVariant(status?.phase)}>
                {status?.phase || 'Unknown'}
              </Badge>
            }
          />
          <InfoRow
            label="Ready"
            value={
              <Badge variant={status?.ready ? 'success' : 'secondary'}>
                {status?.ready ? 'Yes' : 'No'}
              </Badge>
            }
          />
          {spec.config?.description && (
            <InfoRow label="Description" value={spec.config.description} />
          )}
          {metadata.uid && (
            <InfoRow 
              label="UID" 
              value={<span className="font-mono text-xs text-muted-foreground truncate block max-w-[200px]">{metadata.uid}</span>} 
            />
          )}
          {metadata.resourceVersion && (
            <InfoRow 
              label="Resource Version" 
              value={<span className="font-mono text-xs">{metadata.resourceVersion}</span>} 
            />
          )}
        </CardContent>
      </Card>

      {/* Status Details */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2 text-base">
            <Activity className="h-4 w-4 text-agent" />
            Status Details
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          {status?.endpoint && (
            <div>
              <span className="text-sm text-muted-foreground flex items-center gap-1">
                <Globe className="h-3 w-3" />
                Endpoint
              </span>
              <code className="font-mono text-xs bg-muted px-2 py-1 rounded mt-1 block overflow-auto">
                {status.endpoint}
              </code>
            </div>
          )}
          {status?.message && (
            <div>
              <span className="text-sm text-muted-foreground">Message</span>
              <p className="text-sm mt-1">{status.message}</p>
            </div>
          )}
          {status?.linkedResources && Object.keys(status.linkedResources).length > 0 && (
            <div>
              <span className="text-sm text-muted-foreground mb-2 block">Linked Resources</span>
              <div className="flex flex-wrap gap-1">
                {Object.entries(status.linkedResources).map(([key, value]) => (
                  <Badge key={key} variant="outline" className="text-xs font-mono">
                    {key}: {value}
                  </Badge>
                ))}
              </div>
            </div>
          )}
          {!status?.endpoint && !status?.message && !status?.linkedResources && (
            <p className="text-sm text-muted-foreground">No additional status information</p>
          )}
        </CardContent>
      </Card>

      {/* Deployment Status */}
      {status?.deployment && (
        <DeploymentStatusCard 
          deployment={status.deployment} 
          className="md:col-span-2"
        />
      )}

      {/* Model Configuration */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2 text-base">
            <Server className="h-4 w-4 text-modelapi" />
            Model Configuration
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <InfoRow
            label="Model API"
            value={<Badge variant="modelapi">{spec.modelAPI}</Badge>}
          />
          <InfoRow
            label="Model"
            value={
              <code className="font-mono text-xs bg-muted px-2 py-1 rounded">
                {spec.model || status?.model || 'Not specified'}
              </code>
            }
          />
          {spec.config?.reasoningLoopMaxSteps && (
            <InfoRow
              label="Max Reasoning Steps"
              value={<span className="font-mono">{spec.config.reasoningLoopMaxSteps}</span>}
            />
          )}
          <InfoRow
            label="Tool Call Mode"
            value={
              <Badge variant="toolmode">
                {spec.config?.toolCallMode || 'auto'}
              </Badge>
            }
          />
          {spec.waitForDependencies !== undefined && (
            <InfoRow
              label="Wait for Dependencies"
              value={
                <Badge variant={spec.waitForDependencies ? 'success' : 'secondary'}>
                  {spec.waitForDependencies ? 'Yes' : 'No'}
                </Badge>
              }
            />
          )}
          <Separator />
          <div>
            <span className="text-sm text-muted-foreground">Instructions</span>
            {spec.config?.instructions ? (
              <pre className="text-xs font-mono bg-muted/50 px-2 py-1 rounded block mt-1 whitespace-pre-wrap max-h-32 overflow-auto">
                {spec.config.instructions}
              </pre>
            ) : (
              <p className="text-sm text-muted-foreground mt-1">Not configured</p>
            )}
          </div>
        </CardContent>
      </Card>

      {/* MCP Servers */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2 text-base">
            <FileCode className="h-4 w-4 text-mcpserver" />
            MCP Servers
          </CardTitle>
        </CardHeader>
        <CardContent>
          {spec.mcpServers && spec.mcpServers.length > 0 ? (
            <div className="flex flex-wrap gap-2">
              {spec.mcpServers.map((mcp) => (
                <Badge key={mcp} variant="mcpserver">
                  {mcp}
                </Badge>
              ))}
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">No MCP servers connected</p>
          )}
        </CardContent>
      </Card>

      {/* Memory Configuration */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2 text-base">
            <Brain className="h-4 w-4 text-agent" />
            Memory Configuration
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <InfoRow
            label="Memory"
            value={
              spec.config?.memory?.enabled !== false ? (
                <Badge variant="success">Enabled</Badge>
              ) : (
                <Badge variant="secondary">Disabled</Badge>
              )
            }
          />
          {spec.config?.memory?.enabled !== false && (
            <>
              <InfoRow
                label="Context Limit"
                value={<span className="font-mono">{spec.config?.memory?.contextLimit || 6}</span>}
              />
              <InfoRow
                label="Max Sessions"
                value={<span className="font-mono">{spec.config?.memory?.maxSessions || 1000}</span>}
              />
              <InfoRow
                label="Max Events/Session"
                value={<span className="font-mono">{spec.config?.memory?.maxSessionEvents || 500}</span>}
              />
              {spec.config?.memory?.type && (
                <InfoRow
                  label="Type"
                  value={<Badge variant="outline">{spec.config.memory.type}</Badge>}
                />
              )}
            </>
          )}
        </CardContent>
      </Card>

      {/* Network Settings */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2 text-base">
            <Network className="h-4 w-4 text-primary" />
            Network Settings
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <InfoRow
            label="Expose Agent"
            value={
              spec.agentNetwork?.expose ? (
                <Badge variant="success">Exposed</Badge>
              ) : (
                <Badge variant="secondary">Private</Badge>
              )
            }
          />
          {spec.agentNetwork?.access && spec.agentNetwork.access.length > 0 && (
            <div>
              <span className="text-sm text-muted-foreground">Access List</span>
              <div className="flex flex-wrap gap-1 mt-1">
                {spec.agentNetwork.access.map((peer) => (
                  <Badge key={peer} variant="outline" className="text-xs">
                    {peer}
                  </Badge>
                ))}
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Gateway Route */}
      {spec.gatewayRoute && (
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="flex items-center gap-2 text-base">
              <Settings className="h-4 w-4 text-muted-foreground" />
              Gateway Route
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {spec.gatewayRoute.timeout && (
              <InfoRow
                label="Timeout"
                value={<code className="font-mono">{spec.gatewayRoute.timeout}</code>}
              />
            )}
            {spec.gatewayRoute.retries !== undefined && (
              <InfoRow
                label="Retries"
                value={<code className="font-mono">{spec.gatewayRoute.retries}</code>}
              />
            )}
          </CardContent>
        </Card>
      )}

      {/* Environment Variables - prefer new container.env, fallback to legacy config.env */}
      {(() => {
        const envVars = spec.container?.env || spec.config?.env || [];
        return envVars.length > 0 && (
          <Card className="md:col-span-2">
            <CardHeader className="pb-3">
              <CardTitle className="text-base">
                Environment Variables ({envVars.length})
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="bg-muted/50 rounded-lg overflow-hidden">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-border">
                      <th className="text-left p-3 font-medium text-muted-foreground">Name</th>
                      <th className="text-left p-3 font-medium text-muted-foreground">Value</th>
                    </tr>
                  </thead>
                  <tbody>
                    {envVars.map((envVar, idx) => (
                      <tr key={idx} className="border-b border-border last:border-0">
                        <td className="p-3 font-mono text-xs">{envVar.name}</td>
                        <td className="p-3 font-mono text-xs text-muted-foreground truncate max-w-[300px]">
                          {envVar.value || (envVar.valueFrom ? '<from secret/configmap>' : '-')}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </CardContent>
          </Card>
        );
      })()}

      {/* Labels & Annotations */}
      {(metadata.labels || metadata.annotations) && (
        <Card className="md:col-span-2">
          <CardHeader className="pb-3">
            <CardTitle className="flex items-center gap-2 text-base">
              <Tag className="h-4 w-4 text-muted-foreground" />
              Labels & Annotations
            </CardTitle>
          </CardHeader>
          <CardContent className="grid gap-4 md:grid-cols-2">
            {metadata.labels && Object.keys(metadata.labels).length > 0 && (
              <div>
                <h4 className="text-sm font-medium mb-2">Labels</h4>
                <div className="flex flex-wrap gap-1">
                  {Object.entries(metadata.labels).map(([key, value]) => (
                    <Badge key={key} variant="outline" className="text-xs font-mono">
                      {key}: {value}
                    </Badge>
                  ))}
                </div>
              </div>
            )}
            {metadata.annotations && Object.keys(metadata.annotations).length > 0 && (
              <div>
                <h4 className="text-sm font-medium mb-2">Annotations</h4>
                <div className="flex flex-wrap gap-1">
                  {Object.entries(metadata.annotations).map(([key, value]) => (
                    <Badge key={key} variant="outline" className="text-xs font-mono">
                      {key}: {value.length > 30 ? `${value.substring(0, 30)}...` : value}
                    </Badge>
                  ))}
                </div>
              </div>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}

function InfoRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-4">
      <span className="text-sm text-muted-foreground shrink-0">{label}</span>
      <span className="text-sm font-medium text-right">{value}</span>
    </div>
  );
}
