import React from 'react';
import { FileText } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { ScrollArea } from '@/components/ui/scroll-area';
import type { Pod, ConfigMap } from '@/types/kubernetes';

interface OperatorConfigProps {
  operatorConfig: ConfigMap | null;
  mcpRuntimes: ConfigMap | null;
  selectedPod: Pod | null;
}

export default function OperatorConfig({
  operatorConfig,
  mcpRuntimes,
  selectedPod,
}: OperatorConfigProps) {
  return (
    <>
      {/* Operator Configuration ConfigMap */}
      <Card className="lg:col-span-2">
        <CardHeader>
          <CardTitle className="text-base flex items-center gap-2">
            <FileText className="h-4 w-4 text-muted-foreground" />
            Operator Configuration
          </CardTitle>
          <CardDescription>kaos-operator-config ConfigMap</CardDescription>
        </CardHeader>
        <CardContent>
          {operatorConfig && operatorConfig.data ? (
            <div className="bg-muted/30 rounded-lg overflow-hidden">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-border">
                    <th className="text-left p-2 font-medium text-muted-foreground w-1/3">Key</th>
                    <th className="text-left p-2 font-medium text-muted-foreground">Value</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(operatorConfig.data).map(([key, value]) => (
                    <tr key={key} className="border-b border-border/50 last:border-0">
                      <td className="p-2 font-mono font-medium">{key}</td>
                      <td className="p-2 font-mono text-muted-foreground break-all">
                        <span className="text-foreground">
                          {value.length > 100 ? value.substring(0, 100) + '...' : value}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="text-sm text-muted-foreground italic">
              ConfigMap kaos-operator-config not found
            </p>
          )}
        </CardContent>
      </Card>

      {/* MCP Runtimes ConfigMap */}
      <Card className="lg:col-span-2">
        <CardHeader>
          <CardTitle className="text-base flex items-center gap-2">
            <FileText className="h-4 w-4 text-muted-foreground" />
            MCP Runtimes
          </CardTitle>
          <CardDescription>kaos-mcp-runtimes ConfigMap - Available runtime configurations</CardDescription>
        </CardHeader>
        <CardContent>
          {mcpRuntimes && mcpRuntimes.data && Object.keys(mcpRuntimes.data).length > 0 ? (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              {Object.entries(mcpRuntimes.data).map(([runtimeName, runtimeConfig]) => {
                let parsed: Record<string, unknown> = {};
                try {
                  parsed = JSON.parse(runtimeConfig);
                } catch {
                  // Not JSON, display raw
                }
                
                return (
                  <Card key={runtimeName} className="bg-muted/30 border-muted">
                    <CardHeader className="pb-2">
                      <CardTitle className="text-sm font-mono">{runtimeName}</CardTitle>
                    </CardHeader>
                    <CardContent className="text-xs space-y-2">
                      {parsed.image && (
                        <div>
                          <span className="text-muted-foreground">Image: </span>
                          <span className="font-mono text-foreground break-all">{String(parsed.image)}</span>
                        </div>
                      )}
                      {parsed.command && Array.isArray(parsed.command) && (
                        <div>
                          <span className="text-muted-foreground">Command: </span>
                          <span className="font-mono text-foreground">{parsed.command.join(' ')}</span>
                        </div>
                      )}
                      {parsed.args && Array.isArray(parsed.args) && (
                        <div>
                          <span className="text-muted-foreground">Args: </span>
                          <span className="font-mono text-foreground">{parsed.args.join(' ')}</span>
                        </div>
                      )}
                      {parsed.ports && Array.isArray(parsed.ports) && parsed.ports.length > 0 && (
                        <div>
                          <span className="text-muted-foreground">Ports: </span>
                          <span className="font-mono text-foreground">
                            {(parsed.ports as Array<{ containerPort?: number }>).map(p => p.containerPort).join(', ')}
                          </span>
                        </div>
                      )}
                      {!parsed.image && !parsed.command && (
                        <ScrollArea className="h-24">
                          <pre className="font-mono text-foreground whitespace-pre-wrap break-all">
                            {runtimeConfig.length > 200 ? runtimeConfig.substring(0, 200) + '...' : runtimeConfig}
                          </pre>
                        </ScrollArea>
                      )}
                    </CardContent>
                  </Card>
                );
              })}
            </div>
          ) : (
            <p className="text-sm text-muted-foreground italic">
              ConfigMap kaos-mcp-runtimes not found or empty
            </p>
          )}
        </CardContent>
      </Card>

      {/* Environment Variables */}
      {selectedPod && (
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle className="text-base">Environment Variables</CardTitle>
            <CardDescription>Configuration for {selectedPod.metadata.name}</CardDescription>
          </CardHeader>
          <CardContent>
            <ScrollArea className="h-[400px]">
              <div className="space-y-4">
                {selectedPod.spec.containers.map((container) => {
                  const envVars = container.env || [];
                  
                  return (
                    <div key={container.name} className="space-y-2">
                      <p className="text-sm font-medium text-muted-foreground">{container.name}</p>
                      {envVars.length > 0 ? (
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
                                      <span className="text-foreground">
                                        {env.value.length > 80 ? env.value.substring(0, 80) + '...' : env.value}
                                      </span>
                                    ) : env.valueFrom?.secretKeyRef ? (
                                      <Badge variant="outline" className="text-xs">
                                        Secret: {env.valueFrom.secretKeyRef.name}/{env.valueFrom.secretKeyRef.key}
                                      </Badge>
                                    ) : (
                                      <span className="italic">-</span>
                                    )}
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      ) : (
                        <p className="text-sm text-muted-foreground italic">No environment variables</p>
                      )}
                    </div>
                  );
                })}
              </div>
            </ScrollArea>
          </CardContent>
        </Card>
      )}
    </>
  );
}
