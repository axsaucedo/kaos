import React from 'react';
import { Bot, Link2, Server, Cpu, X, ExternalLink } from 'lucide-react';
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
import type { Agent } from '@/types/kubernetes';

interface AgentDetailDrawerProps {
  agent: Agent;
  open: boolean;
  onClose: () => void;
  onEdit?: () => void;
}

export function AgentDetailDrawer({ agent, open, onClose, onEdit }: AgentDetailDrawerProps) {
  const getStatusVariant = (phase?: string) => {
    switch (phase) {
      case 'Running': return 'success';
      case 'Pending': return 'warning';
      case 'Error': return 'destructive';
      default: return 'secondary';
    }
  };

  return (
    <Sheet open={open} onOpenChange={(isOpen) => !isOpen && onClose()}>
      <SheetContent className="w-full sm:max-w-lg">
        <SheetHeader className="pb-4">
          <div className="flex items-center gap-3">
            <div className="h-10 w-10 rounded-lg bg-agent/20 flex items-center justify-center">
              <Bot className="h-5 w-5 text-agent" />
            </div>
            <div className="flex-1">
              <SheetTitle className="text-lg">{agent.metadata.name}</SheetTitle>
              <SheetDescription className="font-mono text-xs">
                {agent.metadata.namespace}
              </SheetDescription>
            </div>
            <Badge variant={getStatusVariant(agent.status?.phase)}>
              {agent.status?.phase || 'Unknown'}
            </Badge>
          </div>
        </SheetHeader>

        <ScrollArea className="h-[calc(100vh-180px)] pr-4">
          <div className="space-y-6">
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

            {/* Environment Variables - prefer new container.env, fallback to legacy config.env */}
            {(() => {
              const envVars = agent.spec.container?.env || agent.spec.config?.env || [];
              return envVars.length > 0 && (
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
            })()}

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

            {/* Metadata */}
            <section>
              <h3 className="text-sm font-semibold text-foreground mb-2">Metadata</h3>
              <div className="space-y-1 text-sm">
                {agent.metadata.uid && (
                  <div>
                    <span className="text-muted-foreground">UID: </span>
                    <span className="font-mono text-xs text-foreground">{agent.metadata.uid}</span>
                  </div>
                )}
                {agent.metadata.creationTimestamp && (
                  <div>
                    <span className="text-muted-foreground">Created: </span>
                    <span className="text-foreground">
                      {new Date(agent.metadata.creationTimestamp).toLocaleString()}
                    </span>
                  </div>
                )}
                {agent.metadata.resourceVersion && (
                  <div>
                    <span className="text-muted-foreground">Resource Version: </span>
                    <span className="font-mono text-xs text-foreground">{agent.metadata.resourceVersion}</span>
                  </div>
                )}
              </div>
            </section>
          </div>
        </ScrollArea>

        <div className="flex gap-2 pt-4 border-t mt-4">
          <Button variant="outline" className="flex-1" onClick={onClose}>
            Close
          </Button>
          {onEdit && (
            <Button className="flex-1" onClick={onEdit}>
              Edit Agent
            </Button>
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}
