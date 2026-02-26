import React from 'react';
import { Box, X } from 'lucide-react';
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
import type { ModelAPI } from '@/types/kubernetes';

interface ModelAPIDetailDrawerProps {
  modelAPI: ModelAPI;
  open: boolean;
  onClose: () => void;
  onEdit?: () => void;
}

export function ModelAPIDetailDrawer({ modelAPI, open, onClose, onEdit }: ModelAPIDetailDrawerProps) {
  const getStatusVariant = (phase?: string) => {
    switch (phase) {
      case 'Running':
      case 'Ready': return 'success';
      case 'Pending': return 'warning';
      case 'Error':
      case 'Failed': return 'destructive';
      default: return 'secondary';
    }
  };

  const envVars = modelAPI.spec.mode === 'Proxy' 
    ? modelAPI.spec.proxyConfig?.env 
    : modelAPI.spec.hostedConfig?.env;

  return (
    <Sheet open={open} onOpenChange={(isOpen) => !isOpen && onClose()}>
      <SheetContent className="w-full sm:max-w-lg">
        <SheetHeader className="pb-4">
          <div className="flex items-center gap-3">
            <div className="h-10 w-10 rounded-lg bg-modelapi/20 flex items-center justify-center">
              <Box className="h-5 w-5 text-modelapi" />
            </div>
            <div className="flex-1">
              <SheetTitle className="text-lg">{modelAPI.metadata.name}</SheetTitle>
              <SheetDescription className="font-mono text-xs">
                {modelAPI.metadata.namespace}
              </SheetDescription>
            </div>
            <Badge variant={getStatusVariant(modelAPI.status?.phase)}>
              {modelAPI.status?.phase || 'Unknown'}
            </Badge>
          </div>
        </SheetHeader>

        <ScrollArea className="h-[calc(100vh-180px)] pr-4">
          <div className="space-y-6">
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

            {/* Environment Variables */}
            {envVars && envVars.length > 0 && (
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
            )}

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

            {/* Metadata */}
            <section>
              <h3 className="text-sm font-semibold text-foreground mb-2">Metadata</h3>
              <div className="space-y-1 text-sm">
                {modelAPI.metadata.uid && (
                  <div>
                    <span className="text-muted-foreground">UID: </span>
                    <span className="font-mono text-xs text-foreground">{modelAPI.metadata.uid}</span>
                  </div>
                )}
                {modelAPI.metadata.creationTimestamp && (
                  <div>
                    <span className="text-muted-foreground">Created: </span>
                    <span className="text-foreground">
                      {new Date(modelAPI.metadata.creationTimestamp).toLocaleString()}
                    </span>
                  </div>
                )}
                {modelAPI.metadata.resourceVersion && (
                  <div>
                    <span className="text-muted-foreground">Resource Version: </span>
                    <span className="font-mono text-xs text-foreground">{modelAPI.metadata.resourceVersion}</span>
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
              Edit ModelAPI
            </Button>
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}
