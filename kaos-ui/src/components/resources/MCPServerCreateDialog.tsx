import React, { useState } from 'react';
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { ScrollArea } from '@/components/ui/scroll-area';
import { useToast } from '@/hooks/use-toast';
import { useKubernetesStore } from '@/stores/kubernetesStore';
import { useKubernetesConnection } from '@/contexts/KubernetesConnectionContext';
import { 
  EnvVarEditorWithSecrets, 
  EnvVarEntry, 
  envVarEntriesToK8sEnvVars 
} from './shared/EnvVarEditorWithSecrets';
import { validateKubernetesName } from './shared/EnvVarEditor';
import type { MCPServer } from '@/types/kubernetes';

// Runtime options based on KAOS registry
type MCPServerRuntime = 'python-string' | 'kubernetes' | 'pctx' | 'custom';

interface MCPServerFormData {
  name: string;
  runtime: MCPServerRuntime;
  params: string;
  serviceAccountName: string;
}

interface MCPServerCreateDialogProps {
  open: boolean;
  onClose: () => void;
}

export function MCPServerCreateDialog({ open, onClose }: MCPServerCreateDialogProps) {
  const { toast } = useToast();
  const { mcpServers } = useKubernetesStore();
  const { namespace, createMCPServer } = useKubernetesConnection();
  const [envVars, setEnvVars] = useState<EnvVarEntry[]>([]);

  const {
    register,
    handleSubmit,
    watch,
    setValue,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<MCPServerFormData>({
    defaultValues: {
      name: '',
      runtime: 'python-string',
      params: '',
      serviceAccountName: '',
    },
  });

  const watchedRuntime = watch('runtime');

  const validateUniqueName = (name: string) => {
    if (mcpServers.some((server) => server.metadata.name === name)) {
      return 'An MCPServer with this name already exists';
    }
    return true;
  };

  const onSubmit = async (data: MCPServerFormData) => {
    try {
      const k8sEnvVars = envVarEntriesToK8sEnvVars(envVars);
      
      const newMCPServer: MCPServer = {
        apiVersion: 'kaos.tools/v1alpha1',
        kind: 'MCPServer',
        metadata: {
          name: data.name,
          namespace: namespace || 'default',
        },
        spec: {
          runtime: data.runtime,
          params: data.params || undefined,
          serviceAccountName: data.serviceAccountName || undefined,
          container: k8sEnvVars.length > 0 ? { env: k8sEnvVars } : undefined,
        },
      };

      await createMCPServer(newMCPServer);
      
      toast({
        title: 'MCPServer created',
        description: `Successfully created MCPServer "${data.name}"`,
      });
      
      reset();
      setEnvVars([]);
      onClose();
    } catch (error) {
      toast({
        title: 'Creation failed',
        description: error instanceof Error ? error.message : 'Failed to create MCPServer',
        variant: 'destructive',
      });
    }
  };

  const handleClose = () => {
    reset();
    setEnvVars([]);
    onClose();
  };

  const getRuntimeDescription = (runtime: MCPServerRuntime) => {
    switch (runtime) {
      case 'python-string':
        return 'Define Python tools inline. Params are passed via MCP_TOOLS_STRING env var.';
      case 'kubernetes':
        return 'Access Kubernetes API. Requires serviceAccountName with proper RBAC.';
      case 'pctx':
        return 'Aggregate multiple MCP servers into a unified endpoint using pctx (Port of Context).';
      case 'custom':
        return 'Use a custom container image. Specify image in environment settings.';
      default:
        return '';
    }
  };

  const getParamsPlaceholder = (runtime: MCPServerRuntime) => {
    switch (runtime) {
      case 'python-string':
        return `def greet(name: str) -> str:
    """Greet someone by name."""
    return f"Hello, {name}!"`;
      case 'kubernetes':
        return `# YAML configuration for kubernetes runtime
namespaces:
  - default
  - kaos-hierarchy`;
      case 'pctx':
        return `{
  "name": "unified-mcp",
  "version": "1.0.0",
  "servers": [
    {"name": "calculator", "url": "http://mcpserver-calc.ns.svc:8000/mcp"},
    {"name": "external", "url": "https://external-mcp.example.com/mcp"}
  ]
}`;
      case 'custom':
        return '# Custom runtime configuration';
      default:
        return '';
    }
  };

  return (
    <Dialog open={open} onOpenChange={(isOpen) => !isOpen && handleClose()}>
      <DialogContent className="max-w-2xl max-h-[90vh]">
        <DialogHeader>
          <div className="flex items-center gap-3">
            <div className="h-10 w-10 rounded-lg bg-mcpserver/20 flex items-center justify-center">
              <Server className="h-5 w-5 text-mcpserver" />
            </div>
            <div>
              <DialogTitle>Create MCPServer</DialogTitle>
              <DialogDescription>
                Create a new MCP Server for tool integration
              </DialogDescription>
            </div>
          </div>
        </DialogHeader>

        <form onSubmit={handleSubmit(onSubmit)}>
          <ScrollArea className="h-[calc(90vh-220px)] pr-4">
            <div className="space-y-6 py-4">
              {/* Name */}
              <div className="space-y-2">
                <Label htmlFor="name">Name</Label>
                <Input
                  id="name"
                  {...register('name', { 
                    required: 'Name is required',
                    validate: (value) => {
                      const k8sValidation = validateKubernetesName(value);
                      if (k8sValidation !== true) return k8sValidation;
                      return validateUniqueName(value);
                    },
                  })}
                  placeholder="my-mcp-server"
                  className="font-mono"
                />
                {errors.name && (
                  <p className="text-sm text-destructive">{errors.name.message}</p>
                )}
              </div>

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
                    <SelectItem value="python-string">
                      Python String
                    </SelectItem>
                    <SelectItem value="kubernetes">
                      Kubernetes
                    </SelectItem>
                    <SelectItem value="pctx">
                      pctx (Aggregator)
                    </SelectItem>
                    <SelectItem value="custom">
                      Custom
                    </SelectItem>
                  </SelectContent>
                </Select>
                <p className="text-xs text-muted-foreground">
                  {getRuntimeDescription(watchedRuntime)}
                </p>
              </div>

              {/* Service Account Name (for kubernetes runtime) */}
              {watchedRuntime === 'kubernetes' && (
                <div className="space-y-2">
                  <Label htmlFor="serviceAccountName">Service Account Name</Label>
                  <Input
                    id="serviceAccountName"
                    {...register('serviceAccountName')}
                    placeholder="kaos-mcp-kubernetes"
                    className="font-mono"
                  />
                  <p className="text-xs text-muted-foreground">
                    Create with: kaos system create-rbac --namespace {namespace || 'default'}
                  </p>
                </div>
              )}

              {/* Params */}
              <div className="space-y-2">
                <Label htmlFor="params">
                  {watchedRuntime === 'python-string' ? 'Tool Definition (Python)' : watchedRuntime === 'pctx' ? 'pctx Configuration (JSON)' : 'Configuration (Params)'}
                </Label>
                <Textarea
                  id="params"
                  {...register('params', {
                    required: watchedRuntime === 'python-string' ? 'Tool definition is required' : false
                  })}
                  placeholder={getParamsPlaceholder(watchedRuntime)}
                  className="font-mono text-xs min-h-[150px]"
                />
                {errors.params && (
                  <p className="text-sm text-destructive">{errors.params.message}</p>
                )}
              </div>

              {/* Environment Variables with Secrets */}
              <EnvVarEditorWithSecrets
                fields={envVars}
                onChange={setEnvVars}
              />
            </div>
          </ScrollArea>

          <DialogFooter className="pt-4 border-t mt-4">
            <Button type="button" variant="outline" onClick={handleClose}>
              Cancel
            </Button>
            <Button type="submit" disabled={isSubmitting}>
              {isSubmitting ? 'Creating...' : 'Create MCPServer'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
