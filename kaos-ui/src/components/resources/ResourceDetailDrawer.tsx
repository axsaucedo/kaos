import React from 'react';
import { Bot, Box, Server, Link2, Cpu, Package, Code, Zap } from 'lucide-react';
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetDescription,
} from '@/components/ui/sheet';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Separator } from '@/components/ui/separator';
import { ScrollArea } from '@/components/ui/scroll-area';
import type { Agent, MCPServer, ModelAPI } from '@/types/kubernetes';
import { getStatusVariant, isAutonomousAgent } from '@/lib/status-utils';

type ResourceType = 'Agent' | 'MCPServer' | 'ModelAPI';

type ResourceForType<T extends ResourceType> = T extends 'Agent'
  ? Agent
  : T extends 'MCPServer'
    ? MCPServer
    : ModelAPI;

interface ResourceDetailDrawerProps<T extends ResourceType> {
  resourceType: T;
  resource: ResourceForType<T>;
  open: boolean;
  onClose: () => void;
  onEdit?: () => void;
}

const RESOURCE_CONFIG = {
  Agent: { icon: Bot, colorClass: 'agent', label: 'Agent' },
  MCPServer: { icon: Server, colorClass: 'mcpserver', label: 'MCPServer' },
  ModelAPI: { icon: Box, colorClass: 'modelapi', label: 'ModelAPI' },
} as const;

function EnvVarsSection({ envVars }: { envVars: { name: string; value?: string; valueFrom?: unknown }[] }) {
  if (!envVars || envVars.length === 0) return null;
  return (
    <>
      <section>
        <h3 className="text-sm font-semibold text-foreground mb-2">
          Environment Variables ({envVars.length})
        </h3>
        <div className="bg-muted/50 rounded-lg overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border">
                <th className="text-left p-2 font-medium text-muted-foreground">Name</th>
                <th className="text-left p-2 font-medium text-muted-foreground">Value</th>
              </tr>
            </thead>
            <tbody>
              {envVars.map((envVar, idx) => (
                <tr key={idx} className="border-b border-border last:border-0">
                  <td className="p-2 font-mono text-xs text-foreground">{envVar.name}</td>
                  <td className="p-2 font-mono text-xs text-muted-foreground truncate max-w-[200px]">
                    {envVar.value || (envVar.valueFrom ? '<from secret/configmap>' : '-')}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
      <Separator />
    </>
  );
}

function MetadataSection({ metadata }: { metadata: { uid?: string; creationTimestamp?: string; resourceVersion?: string } }) {
  return (
    <section>
      <h3 className="text-sm font-semibold text-foreground mb-2">Metadata</h3>
      <div className="space-y-1 text-sm">
        {metadata.uid && (
          <div>
            <span className="text-muted-foreground">UID: </span>
            <span className="font-mono text-xs text-foreground">{metadata.uid}</span>
          </div>
        )}
        {metadata.creationTimestamp && (
          <div>
            <span className="text-muted-foreground">Created: </span>
            <span className="text-foreground">
              {new Date(metadata.creationTimestamp).toLocaleString()}
            </span>
          </div>
        )}
        {metadata.resourceVersion && (
          <div>
            <span className="text-muted-foreground">Resource Version: </span>
            <span className="font-mono text-xs text-foreground">{metadata.resourceVersion}</span>
          </div>
        )}
      </div>
    </section>
  );
}

function AgentSections({ agent }: { agent: Agent }) {
  const envVars = agent.spec.container?.env || agent.spec.config?.env || [];
  return (
    <>
      {/* Description */}
      <section>
        <h3 className="text-sm font-semibold text-foreground mb-2">Description</h3>
        <p className="text-sm text-muted-foreground">
          {agent.spec.config.description || 'No description provided'}
        </p>
      </section>

      <Separator />

      {/* Instructions */}
      <section>
        <h3 className="text-sm font-semibold text-foreground mb-2">Instructions</h3>
        <div className="bg-muted/50 rounded-lg p-3">
          <p className="text-sm text-foreground whitespace-pre-wrap">
            {agent.spec.config.instructions || 'No instructions provided'}
          </p>
        </div>
      </section>

      <Separator />

      {/* Model API */}
      <section>
        <h3 className="text-sm font-semibold text-foreground mb-2 flex items-center gap-2">
          <Cpu className="h-4 w-4" />
          Model API
        </h3>
        <Badge variant="modelapi" className="text-sm">
          {agent.spec.modelAPI}
        </Badge>
      </section>

      <Separator />

      {/* MCP Servers */}
      {agent.spec.mcpServers && agent.spec.mcpServers.length > 0 && (
        <>
          <section>
            <h3 className="text-sm font-semibold text-foreground mb-2 flex items-center gap-2">
              <Server className="h-4 w-4" />
              MCP Servers ({agent.spec.mcpServers.length})
            </h3>
            <div className="flex flex-wrap gap-2">
              {agent.spec.mcpServers.map((server) => (
                <Badge key={server} variant="mcpserver">
                  {server}
                </Badge>
              ))}
            </div>
          </section>
          <Separator />
        </>
      )}

      {/* Agent Network */}
      <section>
        <h3 className="text-sm font-semibold text-foreground mb-2 flex items-center gap-2">
          <Link2 className="h-4 w-4" />
          Agent Network
        </h3>
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-sm text-muted-foreground">Exposed</span>
            <Badge variant={agent.spec.agentNetwork?.expose ? 'success' : 'secondary'}>
              {agent.spec.agentNetwork?.expose ? 'Yes' : 'No'}
            </Badge>
          </div>
          {agent.spec.agentNetwork?.access && agent.spec.agentNetwork.access.length > 0 && (
            <div>
              <span className="text-sm text-muted-foreground block mb-1">Peer Access</span>
              <div className="flex flex-wrap gap-1">
                {agent.spec.agentNetwork.access.map((peer) => (
                  <Badge key={peer} variant="outline" className="text-xs">
                    {peer}
                  </Badge>
                ))}
              </div>
            </div>
          )}
        </div>
      </section>

      <Separator />

      {/* Autonomous Execution */}
      {isAutonomousAgent(agent) && (
        <>
          <section>
            <h3 className="text-sm font-semibold text-foreground mb-2 flex items-center gap-2">
              <Zap className="h-4 w-4 text-yellow-500" />
              Autonomous Execution
            </h3>
            <div className="space-y-2 text-sm">
              <div>
                <span className="text-muted-foreground block mb-1">Goal</span>
                <p className="text-foreground bg-muted/50 rounded-lg p-2 text-xs">
                  {agent.spec.config?.autonomous?.goal}
                </p>
              </div>
              {agent.spec.config?.autonomous?.intervalSeconds !== undefined && (
                <div className="flex items-center justify-between">
                  <span className="text-muted-foreground">Interval</span>
                  <span className="font-mono">{agent.spec.config.autonomous.intervalSeconds}s</span>
                </div>
              )}
              {agent.spec.config?.autonomous?.maxIterRuntimeSeconds !== undefined && (
                <div className="flex items-center justify-between">
                  <span className="text-muted-foreground">Max Iter Runtime</span>
                  <span className="font-mono">{agent.spec.config.autonomous.maxIterRuntimeSeconds}s</span>
                </div>
              )}
            </div>
          </section>
          <Separator />
        </>
      )}

      {/* Task Budgets */}
      {agent.spec.config?.taskConfig && (
        <>
          <section>
            <h3 className="text-sm font-semibold text-foreground mb-2">Task Budgets</h3>
            <div className="space-y-2 text-sm">
              {agent.spec.config.taskConfig.maxIterations !== undefined && (
                <div className="flex items-center justify-between">
                  <span className="text-muted-foreground">Max Iterations</span>
                  <span className="font-mono">{agent.spec.config.taskConfig.maxIterations}</span>
                </div>
              )}
              {agent.spec.config.taskConfig.maxRuntimeSeconds !== undefined && (
                <div className="flex items-center justify-between">
                  <span className="text-muted-foreground">Max Runtime</span>
                  <span className="font-mono">{agent.spec.config.taskConfig.maxRuntimeSeconds}s</span>
                </div>
              )}
              {agent.spec.config.taskConfig.maxToolCalls !== undefined && (
                <div className="flex items-center justify-between">
                  <span className="text-muted-foreground">Max Tool Calls</span>
                  <span className="font-mono">{agent.spec.config.taskConfig.maxToolCalls}</span>
                </div>
              )}
            </div>
          </section>
          <Separator />
        </>
      )}

      <EnvVarsSection envVars={envVars} />

      {/* Status Details */}
      {agent.status && (
        <section>
          <h3 className="text-sm font-semibold text-foreground mb-2">Status Details</h3>
          <div className="space-y-2 text-sm">
            {agent.status.message && (
              <div>
                <span className="text-muted-foreground">Message: </span>
                <span className="text-foreground">{agent.status.message}</span>
              </div>
            )}
            {agent.status.linkedResources && Object.keys(agent.status.linkedResources).length > 0 && (
              <div>
                <span className="text-muted-foreground block mb-1">Linked Resources:</span>
                <div className="flex flex-wrap gap-1">
                  {Object.entries(agent.status.linkedResources).map(([key, value]) => (
                    <Badge key={key} variant="outline" className="text-xs">
                      {key}: {value}
                    </Badge>
                  ))}
                </div>
              </div>
            )}
          </div>
        </section>
      )}
    </>
  );
}

function MCPServerSections({ mcpServer }: { mcpServer: MCPServer }) {
  const toolsConfig = mcpServer.spec.config?.tools;
  const hasPackage = toolsConfig?.fromPackage;
  const hasString = toolsConfig?.fromString;
  const runtime = mcpServer.spec.runtime || mcpServer.spec.type;
  const hasParams = mcpServer.spec.params;
  const envVars = mcpServer.spec.container?.env || mcpServer.spec.config?.env;

  return (
    <>
      {/* Type/Runtime */}
      <section>
        <h3 className="text-sm font-semibold text-foreground mb-2">Runtime</h3>
        <Badge variant="secondary">{runtime || 'Unknown'}</Badge>
      </section>

      <Separator />

      {/* Tools Configuration / Params */}
      <section>
        <h3 className="text-sm font-semibold text-foreground mb-2">
          {hasParams ? 'Parameters' : 'Tools Configuration'}
        </h3>
        <div className="space-y-3">
          {hasParams && (
            <div className="flex items-start gap-2">
              <Code className="h-4 w-4 text-muted-foreground mt-0.5" />
              <div className="flex-1">
                <pre className="text-xs font-mono text-foreground bg-muted/50 p-2 rounded overflow-auto max-h-[150px]">
                  {mcpServer.spec.params}
                </pre>
              </div>
            </div>
          )}
          {hasPackage && (
            <div className="flex items-start gap-2">
              <Package className="h-4 w-4 text-muted-foreground mt-0.5" />
              <div>
                <span className="text-sm text-muted-foreground">From Package: </span>
                <code className="text-sm font-mono text-foreground bg-muted/50 px-2 py-0.5 rounded">
                  {toolsConfig?.fromPackage}
                </code>
              </div>
            </div>
          )}
          {hasString && !hasParams && (
            <div className="flex items-start gap-2">
              <Code className="h-4 w-4 text-muted-foreground mt-0.5" />
              <div className="flex-1">
                <span className="text-sm text-muted-foreground block mb-1">From Code:</span>
                <pre className="text-xs font-mono text-foreground bg-muted/50 p-2 rounded overflow-auto max-h-[150px]">
                  {toolsConfig?.fromString}
                </pre>
              </div>
            </div>
          )}
          {!hasPackage && !hasString && !hasParams && (
            <p className="text-sm text-muted-foreground">No configuration</p>
          )}
        </div>
      </section>

      <Separator />

      {/* Endpoint */}
      {mcpServer.status?.endpoint && (
        <>
          <section>
            <h3 className="text-sm font-semibold text-foreground mb-2">Endpoint</h3>
            <code className="text-sm font-mono text-muted-foreground bg-muted/50 px-2 py-1 rounded">
              {mcpServer.status.endpoint}
            </code>
          </section>
          <Separator />
        </>
      )}

      {/* Available Tools */}
      {mcpServer.status?.availableTools && mcpServer.status.availableTools.length > 0 && (
        <>
          <section>
            <h3 className="text-sm font-semibold text-foreground mb-2">
              Available Tools ({mcpServer.status.availableTools.length})
            </h3>
            <div className="flex flex-wrap gap-1">
              {mcpServer.status.availableTools.map((tool) => (
                <Badge key={tool} variant="outline" className="text-xs">
                  {tool}
                </Badge>
              ))}
            </div>
          </section>
          <Separator />
        </>
      )}

      <EnvVarsSection envVars={envVars || []} />

      {/* Status Details */}
      {mcpServer.status && (
        <section>
          <h3 className="text-sm font-semibold text-foreground mb-2">Status Details</h3>
          <div className="space-y-2 text-sm">
            <div className="flex items-center justify-between">
              <span className="text-muted-foreground">Ready</span>
              <Badge variant={mcpServer.status.ready ? 'success' : 'secondary'}>
                {mcpServer.status.ready ? 'Yes' : 'No'}
              </Badge>
            </div>
            {mcpServer.status.message && (
              <div>
                <span className="text-muted-foreground">Message: </span>
                <span className="text-foreground">{mcpServer.status.message}</span>
              </div>
            )}
          </div>
        </section>
      )}
    </>
  );
}

function ModelAPISections({ modelAPI }: { modelAPI: ModelAPI }) {
  const envVars = modelAPI.spec.mode === 'Proxy'
    ? modelAPI.spec.proxyConfig?.env
    : modelAPI.spec.hostedConfig?.env;

  return (
    <>
      {/* Mode */}
      <section>
        <h3 className="text-sm font-semibold text-foreground mb-2">Mode</h3>
        <Badge variant={modelAPI.spec.mode === 'Proxy' ? 'secondary' : 'outline'}>
          {modelAPI.spec.mode}
        </Badge>
      </section>

      <Separator />

      {/* Configuration */}
      <section>
        <h3 className="text-sm font-semibold text-foreground mb-2">Configuration</h3>
        <div className="space-y-2">
          {modelAPI.spec.mode === 'Hosted' && modelAPI.spec.hostedConfig?.model && (
            <div>
              <span className="text-sm text-muted-foreground">Model: </span>
              <span className="text-sm font-mono text-foreground">
                {modelAPI.spec.hostedConfig.model}
              </span>
            </div>
          )}
          {modelAPI.spec.mode === 'Proxy' && (
            <>
              {modelAPI.spec.proxyConfig?.apiBase && (
                <div>
                  <span className="text-sm text-muted-foreground">API Base: </span>
                  <span className="text-sm font-mono text-foreground">
                    {modelAPI.spec.proxyConfig.apiBase}
                  </span>
                </div>
              )}
              {modelAPI.spec.proxyConfig?.models && modelAPI.spec.proxyConfig.models.length > 0 && (
                <div>
                  <span className="text-sm text-muted-foreground">Models: </span>
                  <span className="text-sm font-mono text-foreground">
                    {modelAPI.spec.proxyConfig.models.join(', ')}
                  </span>
                </div>
              )}
              {!modelAPI.spec.proxyConfig?.apiBase && (!modelAPI.spec.proxyConfig?.models || modelAPI.spec.proxyConfig.models.length === 0) && (
                <p className="text-sm text-muted-foreground">
                  Proxies requests to external LLM providers via LiteLLM
                </p>
              )}
            </>
          )}
        </div>
      </section>

      <Separator />

      {/* Endpoint */}
      {modelAPI.status?.endpoint && (
        <>
          <section>
            <h3 className="text-sm font-semibold text-foreground mb-2">Endpoint</h3>
            <code className="text-sm font-mono text-muted-foreground bg-muted/50 px-2 py-1 rounded">
              {modelAPI.status.endpoint}
            </code>
          </section>
          <Separator />
        </>
      )}

      <EnvVarsSection envVars={envVars || []} />

      {/* Status Details */}
      {modelAPI.status && (
        <section>
          <h3 className="text-sm font-semibold text-foreground mb-2">Status Details</h3>
          <div className="space-y-2 text-sm">
            <div className="flex items-center justify-between">
              <span className="text-muted-foreground">Ready</span>
              <Badge variant={modelAPI.status.ready ? 'success' : 'secondary'}>
                {modelAPI.status.ready ? 'Yes' : 'No'}
              </Badge>
            </div>
            {modelAPI.status.message && (
              <div>
                <span className="text-muted-foreground">Message: </span>
                <span className="text-foreground">{modelAPI.status.message}</span>
              </div>
            )}
          </div>
        </section>
      )}
    </>
  );
}

export function ResourceDetailDrawer<T extends ResourceType>({
  resourceType,
  resource,
  open,
  onClose,
  onEdit,
}: ResourceDetailDrawerProps<T>) {
  const config = RESOURCE_CONFIG[resourceType];
  const Icon = config.icon;

  return (
    <Sheet open={open} onOpenChange={(isOpen) => !isOpen && onClose()}>
      <SheetContent className="w-full sm:max-w-lg">
        <SheetHeader className="pb-4">
          <div className="flex items-center gap-3">
            <div className={`h-10 w-10 rounded-lg bg-${config.colorClass}/20 flex items-center justify-center`}>
              <Icon className={`h-5 w-5 text-${config.colorClass}`} />
            </div>
            <div className="flex-1">
              <SheetTitle className="text-lg">{resource.metadata.name}</SheetTitle>
              <SheetDescription className="font-mono text-xs">
                {resource.metadata.namespace}
              </SheetDescription>
            </div>
            <Badge variant={getStatusVariant(resource.status?.phase)}>
              {resource.status?.phase || 'Unknown'}
            </Badge>
          </div>
        </SheetHeader>

        <ScrollArea className="h-[calc(100vh-180px)] pr-4">
          <div className="space-y-6">
            {resourceType === 'Agent' && <AgentSections agent={resource as Agent} />}
            {resourceType === 'MCPServer' && <MCPServerSections mcpServer={resource as MCPServer} />}
            {resourceType === 'ModelAPI' && <ModelAPISections modelAPI={resource as ModelAPI} />}

            <MetadataSection metadata={resource.metadata} />
          </div>
        </ScrollArea>

        <div className="flex gap-2 pt-4 border-t mt-4">
          <Button variant="outline" className="flex-1" onClick={onClose}>
            Close
          </Button>
          {onEdit && (
            <Button className="flex-1" onClick={onEdit}>
              Edit {config.label}
            </Button>
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}
