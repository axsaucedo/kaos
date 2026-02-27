import React, { useState, useEffect } from 'react';
import { useForm } from 'react-hook-form';
import { Server } from 'lucide-react';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Label } from '@/components/ui/label';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Separator } from '@/components/ui/separator';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { useToast } from '@/hooks/use-toast';
import { useKubernetesConnection } from '@/contexts/KubernetesConnectionContext';
import { 
  EnvVarEditorWithSecrets, 
  EnvVarEntry, 
  envVarEntriesToK8sEnvVars,
  k8sEnvVarsToEntries,
} from './shared/EnvVarEditorWithSecrets';
import { LabelsAnnotationsEditor } from '@/components/shared/LabelsAnnotationsEditor';
import type { MCPServer } from '@/types/kubernetes';

// Runtime options for new CRD format
type MCPServerRuntime = 'python-string' | 'kubernetes' | 'pctx' | 'custom';

interface MCPServerFormData {
  runtime: MCPServerRuntime;
  params: string;
  serviceAccountName: string;
  gatewayTimeout: string;
  gatewayRetries: number | undefined;
  labels: { key: string; value: string }[];
  annotations: { key: string; value: string }[];
}

interface MCPServerEditDialogProps {
  mcpServer: MCPServer;
  open: boolean;
  onClose: () => void;
}

const recordToArray = (record?: Record<string, string>) =>
  record ? Object.entries(record).map(([key, value]) => ({ key, value })) : [];

const arrayToRecord = (arr: { key: string; value: string }[]) =>
  arr.filter(item => item.key).reduce((acc, { key, value }) => ({ ...acc, [key]: value }), {});

export function MCPServerEditDialog({ mcpServer, open, onClose }: MCPServerEditDialogProps) {
  const { toast } = useToast();
  const { updateMCPServer } = useKubernetesConnection();
  const [envVars, setEnvVars] = useState<EnvVarEntry[]>([]);

  // Determine runtime from spec (support both legacy and new format)
  const getRuntime = (): MCPServerRuntime => {
    if (mcpServer.spec.runtime) return mcpServer.spec.runtime as MCPServerRuntime;
    // Legacy type mapping
    if (mcpServer.spec.type === 'python-runtime') return 'python-string';
    if (mcpServer.spec.type === 'node-runtime') return 'custom';
    return 'python-string';
  };

  // Get params from spec (support both legacy and new format)
  const getParams = (): string => {
    if (mcpServer.spec.params) return mcpServer.spec.params;
    if (mcpServer.spec.config?.tools?.fromString) return mcpServer.spec.config.tools.fromString;
    if (mcpServer.spec.config?.tools?.fromPackage) return mcpServer.spec.config.tools.fromPackage;
    return '';
  };

  const {
    register,
    handleSubmit,
    control,
    watch,
    setValue,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<MCPServerFormData>({
    defaultValues: {
      runtime: getRuntime(),
      params: getParams(),
      serviceAccountName: mcpServer.spec.serviceAccountName || '',
      gatewayTimeout: mcpServer.spec.gatewayRoute?.timeout || '',
      gatewayRetries: mcpServer.spec.gatewayRoute?.retries,
      labels: recordToArray(mcpServer.metadata.labels),
      annotations: recordToArray(mcpServer.metadata.annotations),
    },
  });

  const watchedRuntime = watch('runtime');

  useEffect(() => {
    reset({
      runtime: getRuntime(),
      params: getParams(),
      serviceAccountName: mcpServer.spec.serviceAccountName || '',
      gatewayTimeout: mcpServer.spec.gatewayRoute?.timeout || '',
      gatewayRetries: mcpServer.spec.gatewayRoute?.retries,
      labels: recordToArray(mcpServer.metadata.labels),
      annotations: recordToArray(mcpServer.metadata.annotations),
    });
    setEnvVars(k8sEnvVarsToEntries(mcpServer.spec.container?.env || mcpServer.spec.config?.env));
  }, [mcpServer, reset]);

  const onSubmit = async (data: MCPServerFormData) => {
    try {
      const k8sEnvVars = envVarEntriesToK8sEnvVars(envVars);
      const labels = arrayToRecord(data.labels);
      const annotations = arrayToRecord(data.annotations);
      
      const updatedMCPServer: MCPServer = {
        ...mcpServer,
        metadata: {
          ...mcpServer.metadata,
          labels: Object.keys(labels).length > 0 ? labels : undefined,
          annotations: Object.keys(annotations).length > 0 ? annotations : undefined,
        },
        spec: {
          runtime: data.runtime,
          params: data.params || undefined,
          serviceAccountName: data.serviceAccountName || undefined,
          container: k8sEnvVars.length > 0 ? { env: k8sEnvVars } : undefined,
          gatewayRoute: (data.gatewayTimeout || data.gatewayRetries)
            ? {
                timeout: data.gatewayTimeout || undefined,
                retries: data.gatewayRetries || undefined,
              }
            : undefined,
        },
      };

      await updateMCPServer(updatedMCPServer);
      
      toast({
        title: 'MCPServer updated',
        description: `Successfully updated MCPServer "${mcpServer.metadata.name}"`,
      });
      
      onClose();
    } catch (error) {
      toast({
        title: 'Update failed',
        description: error instanceof Error ? error.message : 'Failed to update MCPServer',
        variant: 'destructive',
      });
    }
  };

  return (
    <Dialog open={open} onOpenChange={(isOpen) => !isOpen && onClose()}>
      <DialogContent className="max-w-2xl max-h-[90vh]">
        <DialogHeader>
          <div className="flex items-center gap-3">
            <div className="h-10 w-10 rounded-lg bg-mcpserver/20 flex items-center justify-center">
              <Server className="h-5 w-5 text-mcpserver" />
            </div>
            <div>
              <DialogTitle>Edit MCPServer: {mcpServer.metadata.name}</DialogTitle>
              <DialogDescription className="font-mono text-xs">
                {mcpServer.metadata.namespace}
              </DialogDescription>
            </div>
          </div>
        </DialogHeader>

        <form onSubmit={handleSubmit(onSubmit)}>
          <ScrollArea className="h-[calc(90vh-220px)] pr-4">
            <div className="space-y-6 py-4">
              {/* Runtime */}
              <div className="space-y-2">
                <Label>Runtime</Label>
                <Select
                  value={watchedRuntime}
                  onValueChange={(value: MCPServerRuntime) => setValue('runtime', value)}
                >
                  <SelectTrigger>
                    <SelectValue placeholder="Select runtime" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="python-string">Python String</SelectItem>
                    <SelectItem value="kubernetes">Kubernetes</SelectItem>
                    <SelectItem value="pctx">pctx (Aggregator)</SelectItem>
                    <SelectItem value="custom">Custom</SelectItem>
                  </SelectContent>
                </Select>
                <p className="text-xs text-muted-foreground">
                  {watchedRuntime === 'python-string' && 'Runs Python MCP tools from a string definition'}
                  {watchedRuntime === 'kubernetes' && 'Provides Kubernetes API tools (requires RBAC)'}
                  {watchedRuntime === 'pctx' && 'Aggregates multiple MCP servers into a unified endpoint'}
                  {watchedRuntime === 'custom' && 'Custom runtime configuration'}
                </p>
              </div>

              {/* Params */}
              <div className="space-y-2">
                <Label htmlFor="params">Parameters</Label>
                <Textarea
                  id="params"
                  {...register('params')}
                  placeholder={
                    watchedRuntime === 'python-string' 
                      ? '# Python tool definitions...'
                      : watchedRuntime === 'kubernetes'
                      ? 'namespaces: default,kaos-system'
                      : watchedRuntime === 'pctx'
                      ? '{"name": "unified-mcp", "version": "1.0.0", "servers": [...]}'
                      : 'Runtime-specific parameters...'
                  }
                  className="font-mono text-xs min-h-[120px]"
                />
                <p className="text-xs text-muted-foreground">
                  {watchedRuntime === 'python-string' && 'Python code defining MCP tools'}
                  {watchedRuntime === 'kubernetes' && 'Kubernetes runtime parameters (e.g., namespaces)'}
                  {watchedRuntime === 'pctx' && 'JSON config with name, version, and servers array'}
                  {watchedRuntime === 'custom' && 'Parameters passed to the custom runtime'}
                </p>
              </div>

              {/* Service Account (for kubernetes runtime) */}
              {watchedRuntime === 'kubernetes' && (
                <div className="space-y-2">
                  <Label htmlFor="serviceAccountName">Service Account Name</Label>
                  <Input
                    id="serviceAccountName"
                    {...register('serviceAccountName')}
                    placeholder="e.g., mcp-kubernetes-sa"
                    className="font-mono"
                  />
                  <p className="text-xs text-muted-foreground">
                    Kubernetes service account for RBAC permissions
                  </p>
                </div>
              )}

              <Separator />

              {/* Gateway Route */}
              <div className="space-y-4">
                <Label className="text-sm font-medium">Gateway Route Settings</Label>
                <div className="grid grid-cols-2 gap-4">
                  <div className="space-y-2">
                    <Label htmlFor="gatewayTimeout" className="text-xs text-muted-foreground">
                      Timeout
                    </Label>
                    <Input
                      id="gatewayTimeout"
                      {...register('gatewayTimeout')}
                      placeholder="e.g., 30s, 5m"
                      className="font-mono text-sm"
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="gatewayRetries" className="text-xs text-muted-foreground">
                      Retries
                    </Label>
                    <Input
                      id="gatewayRetries"
                      type="number"
                      min={0}
                      max={10}
                      {...register('gatewayRetries', { valueAsNumber: true })}
                      placeholder="e.g., 3"
                      className="font-mono text-sm"
                    />
                  </div>
                </div>
              </div>

              <Separator />

              {/* Environment Variables with Secrets */}
              <EnvVarEditorWithSecrets
                fields={envVars}
                onChange={setEnvVars}
              />

              <Separator />

              {/* Labels & Annotations */}
              <LabelsAnnotationsEditor
                control={control}
                register={register}
                labelsFieldName="labels"
                annotationsFieldName="annotations"
              />
            </div>
          </ScrollArea>

          <DialogFooter className="pt-4 border-t mt-4">
            <Button type="button" variant="outline" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" disabled={isSubmitting}>
              {isSubmitting ? 'Saving...' : 'Save Changes'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
