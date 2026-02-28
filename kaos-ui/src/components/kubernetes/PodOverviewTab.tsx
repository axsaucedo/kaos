import React from 'react';
import { Copy, Check } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import type { Pod } from '@/types/kubernetes';

interface PodOverviewTabProps {
  pod: Pod;
  containers: string[];
  namespace: string | undefined;
  name: string | undefined;
  selectedContainer: string;
  copiedCommand: boolean;
  onCopyExecCommand: () => void;
}

export function PodOverviewTab({ pod, containers, namespace, name, selectedContainer, copiedCommand, onCopyExecCommand }: PodOverviewTabProps) {
  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
      {/* Pod Info */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Pod Information</CardTitle>
        </CardHeader>
        <CardContent className="grid grid-cols-2 gap-4 text-sm">
          <div>
            <span className="text-muted-foreground">Name</span>
            <p className="font-mono font-medium">{pod.metadata.name}</p>
          </div>
          <div>
            <span className="text-muted-foreground">Namespace</span>
            <p className="font-mono font-medium">{pod.metadata.namespace || 'default'}</p>
          </div>
          <div>
            <span className="text-muted-foreground">Status</span>
            <p className="font-medium">
              <Badge variant={pod.status?.phase === 'Running' ? 'success' : pod.status?.phase === 'Pending' ? 'warning' : 'destructive'}>
                {pod.status?.phase || 'Unknown'}
              </Badge>
            </p>
          </div>
          <div>
            <span className="text-muted-foreground">Pod IP</span>
            <p className="font-mono font-medium">{pod.status?.podIP || 'N/A'}</p>
          </div>
          <div>
            <span className="text-muted-foreground">Host IP</span>
            <p className="font-mono font-medium">{pod.status?.hostIP || 'N/A'}</p>
          </div>
          <div>
            <span className="text-muted-foreground">Node</span>
            <p className="font-mono font-medium">{pod.spec.nodeName || 'N/A'}</p>
          </div>
          {pod.metadata.creationTimestamp && (
            <div className="col-span-2">
              <span className="text-muted-foreground">Created</span>
              <p className="font-medium">{new Date(pod.metadata.creationTimestamp).toLocaleString()}</p>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Container Command & Args */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Container Command & Args</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          {pod.spec.containers.map((container) => (
            <div key={container.name} className="space-y-2">
              {containers.length > 1 && (
                <p className="text-sm font-medium text-muted-foreground">{container.name}</p>
              )}
              <div className="space-y-2">
                {container.command && container.command.length > 0 && (
                  <div>
                    <span className="text-xs text-muted-foreground">Command:</span>
                    <code className="block bg-muted p-2 rounded-md font-mono text-xs break-all mt-1">
                      {container.command.join(' ')}
                    </code>
                  </div>
                )}
                {container.args && container.args.length > 0 && (
                  <div>
                    <span className="text-xs text-muted-foreground">Args:</span>
                    <code className="block bg-muted p-2 rounded-md font-mono text-xs break-all mt-1">
                      {container.args.join(' ')}
                    </code>
                  </div>
                )}
                {(!container.command || container.command.length === 0) && (!container.args || container.args.length === 0) && (
                  <p className="text-xs text-muted-foreground italic">Using image default entrypoint</p>
                )}
              </div>
            </div>
          ))}
          <div className="pt-2 border-t border-border">
            <p className="text-xs text-muted-foreground mb-2">Exec into pod:</p>
            <div className="flex items-center gap-2">
              <code className="flex-1 bg-muted p-2 rounded-md font-mono text-xs break-all">
                kubectl exec -it -n {namespace} {name} {selectedContainer ? `-c ${selectedContainer}` : ''} -- /bin/sh
              </code>
              <Button variant="outline" size="icon" onClick={onCopyExecCommand}>
                {copiedCommand ? <Check className="h-4 w-4 text-success" /> : <Copy className="h-4 w-4" />}
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Containers */}
      <Card className="lg:col-span-2">
        <CardHeader>
          <CardTitle className="text-base">Containers ({containers.length})</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-4">
            {pod.spec.containers.map((container) => (
              <div key={container.name} className="p-4 bg-muted/50 rounded-lg">
                <div className="flex items-start justify-between mb-3">
                  <div>
                    <p className="font-semibold">{container.name}</p>
                    <p className="text-xs text-muted-foreground font-mono mt-1">{container.image}</p>
                  </div>
                  <Badge variant="outline">
                    {container.ports?.length || 0} ports
                  </Badge>
                </div>
                
                {container.ports && container.ports.length > 0 && (
                  <div className="mt-2">
                    <span className="text-xs text-muted-foreground">Ports:</span>
                    <div className="flex flex-wrap gap-1 mt-1">
                      {container.ports.map((port, idx) => (
                        <Badge key={idx} variant="secondary" className="text-xs">
                          {port.containerPort}
                        </Badge>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      {/* Environment Variables */}
      <Card className="lg:col-span-2">
        <CardHeader>
          <CardTitle className="text-base">Environment Variables</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-4">
            {pod.spec.containers.map((container) => {
              const envVars = container.env || [];
              if (envVars.length === 0) return null;
              
              return (
                <div key={container.name} className="space-y-2">
                  {containers.length > 1 && (
                    <p className="text-sm font-medium text-muted-foreground">{container.name}</p>
                  )}
                  <div className="bg-muted/30 rounded-lg overflow-hidden">
                    <table className="w-full text-xs">
                      <thead>
                        <tr className="border-b border-border">
                          <th className="text-left p-2 font-medium text-muted-foreground w-1/3">Name</th>
                          <th className="text-left p-2 font-medium text-muted-foreground">Value / Source</th>
                        </tr>
                      </thead>
                      <tbody>
                        {envVars.map((env, idx) => (
                          <tr key={idx} className="border-b border-border/50 last:border-0">
                            <td className="p-2 font-mono font-medium">{env.name}</td>
                            <td className="p-2 font-mono text-muted-foreground break-all">
                              {env.value ? (
                                <span className="text-foreground">{env.value.length > 100 ? env.value.substring(0, 100) + '...' : env.value}</span>
                              ) : env.valueFrom?.secretKeyRef ? (
                                <Badge variant="outline" className="text-xs">
                                  Secret: {env.valueFrom.secretKeyRef.name}/{env.valueFrom.secretKeyRef.key}
                                </Badge>
                              ) : env.valueFrom?.configMapKeyRef ? (
                                <Badge variant="secondary" className="text-xs">
                                  ConfigMap: {env.valueFrom.configMapKeyRef.name}/{env.valueFrom.configMapKeyRef.key}
                                </Badge>
                              ) : (
                                <span className="italic text-muted-foreground">-</span>
                              )}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              );
            })}
            {pod.spec.containers.every(c => !c.env || c.env.length === 0) && (
              <p className="text-sm text-muted-foreground italic">No environment variables configured</p>
            )}
          </div>
        </CardContent>
      </Card>

      {/* Labels & Annotations */}
      {(pod.metadata.labels || pod.metadata.annotations) && (
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle className="text-base">Labels & Annotations</CardTitle>
          </CardHeader>
          <CardContent className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {pod.metadata.labels && Object.keys(pod.metadata.labels).length > 0 && (
              <div>
                <h4 className="text-sm font-medium mb-2">Labels</h4>
                <div className="flex flex-wrap gap-1">
                  {Object.entries(pod.metadata.labels).map(([key, value]) => (
                    <Badge key={key} variant="secondary" className="text-xs font-mono">
                      {key}={value}
                    </Badge>
                  ))}
                </div>
              </div>
            )}
            {pod.metadata.annotations && Object.keys(pod.metadata.annotations).length > 0 && (
              <div>
                <h4 className="text-sm font-medium mb-2">Annotations</h4>
                <div className="space-y-1 text-xs">
                  {Object.entries(pod.metadata.annotations).slice(0, 5).map(([key, value]) => (
                    <div key={key} className="font-mono bg-muted/50 p-2 rounded">
                      <span className="text-muted-foreground">{key}:</span> {String(value).substring(0, 100)}
                    </div>
                  ))}
                  {Object.keys(pod.metadata.annotations).length > 5 && (
                    <p className="text-muted-foreground">+{Object.keys(pod.metadata.annotations).length - 5} more</p>
                  )}
                </div>
              </div>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}
