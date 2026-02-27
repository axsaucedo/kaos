import React, { useState } from 'react';
import { useForm } from 'react-hook-form';
import { Box } from 'lucide-react';
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
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Separator } from '@/components/ui/separator';
import { useToast } from '@/hooks/use-toast';
import { useKubernetesStore } from '@/stores/kubernetesStore';
import { useKubernetesConnection } from '@/contexts/KubernetesConnectionContext';
import { 
  EnvVarEditorWithSecrets, 
  EnvVarEntry, 
  envVarEntriesToK8sEnvVars 
} from './shared/EnvVarEditorWithSecrets';
import { 
  ApiKeySecretPicker, 
  pickerValueToApiKeySource,
  ApiKeyType 
} from './shared/ApiKeySecretPicker';
import { validateKubernetesName } from './shared/EnvVarEditor';
import type { ModelAPI, ModelAPIMode } from '@/types/kubernetes';

interface ModelAPIFormData {
  name: string;
  mode: ModelAPIMode;
  // Proxy mode fields
  models: string;
  provider: string;
  apiBase: string;
  configYamlString: string;
  // Hosted mode fields
  hostedModel: string;
}

interface ModelAPICreateDialogProps {
  open: boolean;
  onClose: () => void;
}

export function ModelAPICreateDialog({ open, onClose }: ModelAPICreateDialogProps) {
  const { toast } = useToast();
  const { modelAPIs } = useKubernetesStore();
  const { namespace, createModelAPI } = useKubernetesConnection();
  const [envVars, setEnvVars] = useState<EnvVarEntry[]>([]);
  const [apiKeyValue, setApiKeyValue] = useState<{
    type: ApiKeyType;
    directValue?: string;
    secretName?: string;
    secretKey?: string;
  }>({ type: 'none' });

  const {
    register,
    handleSubmit,
    watch,
    setValue,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<ModelAPIFormData>({
    defaultValues: {
      name: '',
      mode: 'Proxy',
      models: '*',
      provider: '',
      apiBase: '',
      configYamlString: '',
      hostedModel: '',
    },
  });

  const watchedMode = watch('mode');

  const validateUniqueName = (name: string) => {
    if (modelAPIs.some((api) => api.metadata.name === name)) {
      return 'A ModelAPI with this name already exists';
    }
    return true;
  };

  const parseModels = (modelsStr: string): string[] => {
    return modelsStr
      .split(/[,\n]/)
      .map(m => m.trim())
      .filter(m => m.length > 0);
  };

  const onSubmit = async (data: ModelAPIFormData) => {
    try {
      const k8sEnvVars = envVarEntriesToK8sEnvVars(envVars);
      const models = parseModels(data.models);
      
      if (data.mode === 'Proxy' && models.length === 0) {
        toast({
          title: 'Validation error',
          description: 'At least one model is required for Proxy mode',
          variant: 'destructive',
        });
        return;
      }
      
      const newModelAPI: ModelAPI = {
        apiVersion: 'kaos.tools/v1alpha1',
        kind: 'ModelAPI',
        metadata: {
          name: data.name,
          namespace: namespace || 'default',
        },
        spec: {
          mode: data.mode,
          proxyConfig: data.mode === 'Proxy' 
            ? { 
                models,
                provider: data.provider || undefined,
                apiBase: data.apiBase || undefined,
                apiKey: pickerValueToApiKeySource(apiKeyValue),
                configYaml: data.configYamlString ? { fromString: data.configYamlString } : undefined,
              }
            : undefined,
          hostedConfig: data.mode === 'Hosted'
            ? { 
                model: data.hostedModel, 
              }
            : undefined,
          // env vars now go in container.env
          container: k8sEnvVars.length > 0 ? { env: k8sEnvVars } : undefined,
        },
      };

      await createModelAPI(newModelAPI);
      
      toast({
        title: 'ModelAPI created',
        description: `Successfully created ModelAPI "${data.name}"`,
      });
      
      reset();
      setEnvVars([]);
      setApiKeyValue({ type: 'none' });
      onClose();
    } catch (error) {
      toast({
        title: 'Creation failed',
        description: error instanceof Error ? error.message : 'Failed to create ModelAPI',
        variant: 'destructive',
      });
    }
  };

  const handleClose = () => {
    reset();
    setEnvVars([]);
    setApiKeyValue({ type: 'none' });
    onClose();
  };

  return (
    <Dialog open={open} onOpenChange={(isOpen) => !isOpen && handleClose()}>
      <DialogContent className="max-w-2xl max-h-[90vh]">
        <DialogHeader>
          <div className="flex items-center gap-3">
            <div className="h-10 w-10 rounded-lg bg-modelapi/20 flex items-center justify-center">
              <Box className="h-5 w-5 text-modelapi" />
            </div>
            <div>
              <DialogTitle>Create ModelAPI</DialogTitle>
              <DialogDescription>
                Create a new Model API endpoint for LLM access
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
                  placeholder="my-model-api"
                  className="font-mono"
                />
                {errors.name && (
                  <p className="text-sm text-destructive">{errors.name.message}</p>
                )}
              </div>

              {/* Mode */}
              <div className="space-y-2">
                <Label>Mode</Label>
                <Select
                  value={watchedMode}
                  onValueChange={(value: ModelAPIMode) => setValue('mode', value)}
                >
                  <SelectTrigger>
                    <SelectValue placeholder="Select mode" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="Proxy">
                      Proxy (LiteLLM)
                    </SelectItem>
                    <SelectItem value="Hosted">
                      Hosted (Ollama)
                    </SelectItem>
                  </SelectContent>
                </Select>
                <p className="text-xs text-muted-foreground">
                  {watchedMode === 'Proxy' 
                    ? 'Proxy mode forwards requests to external LLM providers via LiteLLM'
                    : 'Hosted mode runs an Ollama server with the specified model in-cluster'
                  }
                </p>
              </div>

              {/* Proxy Mode Fields */}
              {watchedMode === 'Proxy' && (
                <>
                  <div className="space-y-2">
                    <Label htmlFor="models">
                      Models <span className="text-destructive">*</span>
                    </Label>
                    <Textarea
                      id="models"
                      {...register('models', { required: 'At least one model is required' })}
                      placeholder="openai/gpt-4o&#10;anthropic/claude-3-sonnet&#10;* (wildcard for all)"
                      className="font-mono text-sm min-h-[80px]"
                    />
                    {errors.models && (
                      <p className="text-sm text-destructive">{errors.models.message}</p>
                    )}
                    <p className="text-xs text-muted-foreground">
                      One model per line or comma-separated. Supports wildcards: <code className="bg-muted px-1 rounded">*</code>, <code className="bg-muted px-1 rounded">openai/*</code>
                    </p>
                  </div>

                  <div className="space-y-2">
                    <Label htmlFor="provider">Provider (optional)</Label>
                    <Input
                      id="provider"
                      {...register('provider')}
                      placeholder="e.g., openai, anthropic, ollama"
                      className="font-mono"
                    />
                    <p className="text-xs text-muted-foreground">
                      LiteLLM provider prefix. When set, model names are prefixed with this provider.
                    </p>
                  </div>

                  <div className="space-y-2">
                    <Label htmlFor="apiBase">API Base URL</Label>
                    <Input
                      id="apiBase"
                      {...register('apiBase')}
                      placeholder="e.g., http://host.docker.internal:11434"
                      className="font-mono"
                    />
                    <p className="text-xs text-muted-foreground">
                      Base URL of the backend LLM API. Set as <code className="bg-muted px-1 rounded">PROXY_API_BASE</code> env var.
                    </p>
                  </div>

                  <Separator />

                  {/* API Key Configuration with Secret Picker */}
                  <ApiKeySecretPicker
                    value={apiKeyValue}
                    onChange={setApiKeyValue}
                  />

                  <Separator />

                  <div className="space-y-2">
                    <Label htmlFor="configYamlString">Advanced: LiteLLM Config YAML</Label>
                    <Textarea
                      id="configYamlString"
                      {...register('configYamlString')}
                      placeholder="# Optional: Full LiteLLM config YAML for advanced multi-model routing"
                      className="font-mono text-xs min-h-[100px]"
                    />
                    <p className="text-xs text-muted-foreground">
                      When provided, this config is used directly. Models list is still required for Agent validation.
                    </p>
                  </div>
                </>
              )}

              {/* Hosted Mode Fields */}
              {watchedMode === 'Hosted' && (
                <div className="space-y-2">
                  <Label htmlFor="hostedModel">Model</Label>
                  <Input
                    id="hostedModel"
                    {...register('hostedModel', { 
                      required: watchedMode === 'Hosted' ? 'Model is required for Hosted mode' : false 
                    })}
                    placeholder="e.g., smollm2:135m"
                    className="font-mono"
                  />
                  {errors.hostedModel && (
                    <p className="text-sm text-destructive">{errors.hostedModel.message}</p>
                  )}
                  <p className="text-xs text-muted-foreground">
                    Ollama model to run in the cluster
                  </p>
                </div>
              )}

              <Separator />

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
              {isSubmitting ? 'Creating...' : 'Create ModelAPI'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
