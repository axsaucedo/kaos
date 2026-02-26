import React from 'react';
import { Box, Globe, Settings, Activity, Clock, Tag } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Separator } from '@/components/ui/separator';
import { DeploymentStatusCard } from '@/components/shared/DeploymentStatusCard';
import type { ModelAPI } from '@/types/kubernetes';

interface ModelAPIOverviewProps {
  modelAPI: ModelAPI;
}

export function ModelAPIOverview({ modelAPI }: ModelAPIOverviewProps) {
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

  // NEW: prefer container.env, fall back to legacy proxyConfig.env/hostedConfig.env
  const envVars = modelAPI.spec.container?.env 
    || (modelAPI.spec.mode === 'Proxy' 
      ? modelAPI.spec.proxyConfig?.env 
      : modelAPI.spec.hostedConfig?.env);

  return (
    <div className="grid gap-6 md:grid-cols-2">
      {/* General Info */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base flex items-center gap-2">
            <Box className="h-4 w-4 text-modelapi" />
            General Information
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-2 gap-4 text-sm">
            <div>
              <span className="text-muted-foreground">Name</span>
              <p className="font-mono font-medium">{modelAPI.metadata.name}</p>
            </div>
            <div>
              <span className="text-muted-foreground">Namespace</span>
              <p className="font-mono font-medium">{modelAPI.metadata.namespace || 'default'}</p>
            </div>
            <div>
              <span className="text-muted-foreground">Mode</span>
              <p>
                <Badge variant={modelAPI.spec.mode === 'Proxy' ? 'secondary' : 'outline'}>
                  {modelAPI.spec.mode}
                </Badge>
              </p>
            </div>
            <div>
              <span className="text-muted-foreground">Status</span>
              <p>
                <Badge variant={getStatusVariant(modelAPI.status?.phase)}>
                  {modelAPI.status?.phase || 'Unknown'}
                </Badge>
              </p>
            </div>
            <div className="col-span-2">
              <span className="text-muted-foreground">Models</span>
              <p className="font-mono font-medium">
                {modelAPI.spec.mode === 'Proxy' 
                  ? (modelAPI.spec.proxyConfig?.models?.join(', ') || 'Not specified')
                  : modelAPI.spec.hostedConfig?.model || 'Not specified'}
              </p>
            </div>
          </div>
          
          {modelAPI.metadata.creationTimestamp && (
            <>
              <Separator />
              <div className="text-sm">
                <span className="text-muted-foreground flex items-center gap-1">
                  <Clock className="h-3 w-3" />
                  Created
                </span>
                <p className="font-medium">
                  {new Date(modelAPI.metadata.creationTimestamp).toLocaleString()}
                </p>
              </div>
            </>
          )}

          {modelAPI.metadata.uid && (
            <div className="text-sm">
              <span className="text-muted-foreground">UID</span>
              <p className="font-mono text-xs text-muted-foreground truncate">
                {modelAPI.metadata.uid}
              </p>
            </div>
          )}

          {modelAPI.metadata.resourceVersion && (
            <div className="text-sm">
              <span className="text-muted-foreground">Resource Version</span>
              <p className="font-mono text-xs">{modelAPI.metadata.resourceVersion}</p>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Status Info */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base flex items-center gap-2">
            <Activity className="h-4 w-4 text-modelapi" />
            Status Details
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-2 gap-4 text-sm">
            <div>
              <span className="text-muted-foreground">Ready</span>
              <p>
                <Badge variant={modelAPI.status?.ready ? 'success' : 'secondary'}>
                  {modelAPI.status?.ready ? 'Yes' : 'No'}
                </Badge>
              </p>
            </div>
            <div>
              <span className="text-muted-foreground">Phase</span>
              <p>
                <Badge variant={getStatusVariant(modelAPI.status?.phase)}>
                  {modelAPI.status?.phase || 'Unknown'}
                </Badge>
              </p>
            </div>
          </div>
          
          {modelAPI.status?.endpoint && (
            <>
              <Separator />
              <div className="text-sm">
                <span className="text-muted-foreground flex items-center gap-1">
                  <Globe className="h-3 w-3" />
                  Endpoint
                </span>
                <code className="font-mono text-xs bg-muted px-2 py-1 rounded mt-1 block overflow-auto">
                  {modelAPI.status.endpoint}
                </code>
              </div>
            </>
          )}

          {modelAPI.status?.message && (
            <>
              <Separator />
              <div className="text-sm">
                <span className="text-muted-foreground">Message</span>
                <p className="text-muted-foreground">{modelAPI.status.message}</p>
              </div>
            </>
          )}
        </CardContent>
      </Card>

      {/* Deployment Status */}
      {modelAPI.status?.deployment && (
        <DeploymentStatusCard 
          deployment={modelAPI.status.deployment} 
          className="md:col-span-2"
        />
      )}

      {/* Configuration */}
      <Card className="md:col-span-2">
        <CardHeader className="pb-3">
          <CardTitle className="text-base flex items-center gap-2">
            <Settings className="h-4 w-4 text-modelapi" />
            Configuration
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          {modelAPI.spec.mode === 'Hosted' && modelAPI.spec.hostedConfig && (
            <div className="space-y-3">
              <div>
                <span className="text-sm text-muted-foreground">Model</span>
                <code className="font-mono text-sm block bg-muted px-2 py-1 rounded mt-1">
                  {modelAPI.spec.hostedConfig.model || 'Not specified'}
                </code>
              </div>
            </div>
          )}
          
          {modelAPI.spec.mode === 'Proxy' && modelAPI.spec.proxyConfig && (
            <div className="space-y-3">
              {modelAPI.spec.proxyConfig.provider && (
                <div>
                  <span className="text-sm text-muted-foreground">Provider</span>
                  <code className="font-mono text-sm block bg-muted px-2 py-1 rounded mt-1">
                    {modelAPI.spec.proxyConfig.provider}
                  </code>
                </div>
              )}
              {modelAPI.spec.proxyConfig.apiBase && (
                <div>
                  <span className="text-sm text-muted-foreground">API Base</span>
                  <code className="font-mono text-sm block bg-muted px-2 py-1 rounded mt-1">
                    {modelAPI.spec.proxyConfig.apiBase}
                  </code>
                </div>
              )}
              {modelAPI.spec.proxyConfig?.models && modelAPI.spec.proxyConfig.models.length > 0 && (
                <div>
                  <span className="text-sm text-muted-foreground">Models</span>
                  <div className="flex flex-wrap gap-1 mt-1">
                    {modelAPI.spec.proxyConfig.models.map((model, idx) => (
                      <code key={idx} className="font-mono text-sm bg-muted px-2 py-1 rounded">
                        {model}
                      </code>
                    ))}
                  </div>
                </div>
              )}
              {modelAPI.spec.proxyConfig?.apiKey && (
                <div>
                  <span className="text-sm text-muted-foreground">API Key</span>
                  <code className="font-mono text-sm block bg-muted px-2 py-1 rounded mt-1">
                    {modelAPI.spec.proxyConfig.apiKey.value 
                      ? '••••••••' 
                      : modelAPI.spec.proxyConfig.apiKey.valueFrom?.secretKeyRef 
                        ? `From Secret: ${modelAPI.spec.proxyConfig.apiKey.valueFrom.secretKeyRef.name}/${modelAPI.spec.proxyConfig.apiKey.valueFrom.secretKeyRef.key}`
                        : modelAPI.spec.proxyConfig.apiKey.valueFrom?.configMapKeyRef
                          ? `From ConfigMap: ${modelAPI.spec.proxyConfig.apiKey.valueFrom.configMapKeyRef.name}/${modelAPI.spec.proxyConfig.apiKey.valueFrom.configMapKeyRef.key}`
                          : 'Not configured'}
                  </code>
                </div>
              )}
              {modelAPI.spec.proxyConfig.configYaml?.fromString && (
                <div>
                  <span className="text-sm text-muted-foreground">LiteLLM Config YAML</span>
                  <pre className="font-mono text-xs bg-muted p-3 rounded mt-1 overflow-auto max-h-[150px]">
                    {modelAPI.spec.proxyConfig.configYaml.fromString}
                  </pre>
                </div>
              )}
              {modelAPI.spec.proxyConfig.configYaml?.fromSecretKeyRef && (
                <div>
                  <span className="text-sm text-muted-foreground">Config from Secret</span>
                  <code className="font-mono text-xs block bg-muted px-2 py-1 rounded mt-1">
                    {modelAPI.spec.proxyConfig.configYaml.fromSecretKeyRef.name}:{modelAPI.spec.proxyConfig.configYaml.fromSecretKeyRef.key}
                  </code>
                </div>
              )}
              {!modelAPI.spec.proxyConfig.apiBase && (!modelAPI.spec.proxyConfig.models || modelAPI.spec.proxyConfig.models.length === 0) && !modelAPI.spec.proxyConfig.configYaml && (
                <p className="text-sm text-muted-foreground">
                  Proxies requests to external LLM providers via LiteLLM
                </p>
              )}
            </div>
          )}

          {/* Gateway Route */}
          {modelAPI.spec.gatewayRoute && (
            <>
              <Separator />
              <div>
                <span className="text-sm text-muted-foreground mb-2 block">Gateway Route</span>
                <div className="flex gap-4 text-sm">
                  {modelAPI.spec.gatewayRoute.timeout && (
                    <div>
                      <span className="text-muted-foreground">Timeout:</span>{' '}
                      <code className="font-mono">{modelAPI.spec.gatewayRoute.timeout}</code>
                    </div>
                  )}
                  {modelAPI.spec.gatewayRoute.retries !== undefined && (
                    <div>
                      <span className="text-muted-foreground">Retries:</span>{' '}
                      <code className="font-mono">{modelAPI.spec.gatewayRoute.retries}</code>
                    </div>
                  )}
                </div>
              </div>
            </>
          )}
        </CardContent>
      </Card>

      {/* Environment Variables */}
      {envVars && envVars.length > 0 && (
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
      )}

      {/* Labels & Annotations */}
      {(modelAPI.metadata.labels || modelAPI.metadata.annotations) && (
        <Card className="md:col-span-2">
          <CardHeader className="pb-3">
            <CardTitle className="text-base flex items-center gap-2">
              <Tag className="h-4 w-4 text-muted-foreground" />
              Labels & Annotations
            </CardTitle>
          </CardHeader>
          <CardContent className="grid gap-4 md:grid-cols-2">
            {modelAPI.metadata.labels && Object.keys(modelAPI.metadata.labels).length > 0 && (
              <div>
                <h4 className="text-sm font-medium mb-2">Labels</h4>
                <div className="flex flex-wrap gap-1">
                  {Object.entries(modelAPI.metadata.labels).map(([key, value]) => (
                    <Badge key={key} variant="outline" className="text-xs font-mono">
                      {key}: {value}
                    </Badge>
                  ))}
                </div>
              </div>
            )}
            {modelAPI.metadata.annotations && Object.keys(modelAPI.metadata.annotations).length > 0 && (
              <div>
                <h4 className="text-sm font-medium mb-2">Annotations</h4>
                <div className="flex flex-wrap gap-1">
                  {Object.entries(modelAPI.metadata.annotations).map(([key, value]) => (
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
