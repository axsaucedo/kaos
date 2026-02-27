import React, { useState, useEffect } from 'react';
import { useForm, useFieldArray } from 'react-hook-form';
import { Bot, Plus, Trash2, Info } from 'lucide-react';
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
import { Switch } from '@/components/ui/switch';
import { Separator } from '@/components/ui/separator';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { ScrollArea } from '@/components/ui/scroll-area';
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import { useToast } from '@/hooks/use-toast';
import { useKubernetesStore } from '@/stores/kubernetesStore';
import { useKubernetesConnection } from '@/contexts/KubernetesConnectionContext';
import { LabelsAnnotationsEditor } from '@/components/shared/LabelsAnnotationsEditor';
import { 
  EnvVarEditorWithSecrets, 
  EnvVarEntry, 
  envVarEntriesToK8sEnvVars,
  k8sEnvVarsToEntries,
} from './shared/EnvVarEditorWithSecrets';
import type { Agent } from '@/types/kubernetes';

interface AgentFormData {
  description: string;
  instructions: string;
  modelAPI: string;
  model: string;
  mcpServers: string[];
  networkExpose: boolean;
  networkAccess: string[];
  reasoningLoopMaxSteps: number | undefined;
  waitForDependencies: boolean;
  gatewayTimeout: string;
  gatewayRetries: number | undefined;
  // Memory configuration
  memoryEnabled: boolean;
  memoryContextLimit: number | undefined;
  memoryMaxSessions: number | undefined;
  memoryMaxSessionEvents: number | undefined;
  toolCallMode: 'auto' | 'native' | 'string';
  // Labels and annotations
  labels: { key: string; value: string }[];
  annotations: { key: string; value: string }[];
}

interface AgentEditDialogProps {
  agent: Agent;
  open: boolean;
  onClose: () => void;
}

const recordToArray = (record?: Record<string, string>) =>
  record ? Object.entries(record).map(([key, value]) => ({ key, value })) : [];

const arrayToRecord = (arr: { key: string; value: string }[]) =>
  arr.filter(item => item.key).reduce((acc, { key, value }) => ({ ...acc, [key]: value }), {});

export function AgentEditDialog({ agent, open, onClose }: AgentEditDialogProps) {
  const { toast } = useToast();
  const { modelAPIs, mcpServers, agents } = useKubernetesStore();
  const { updateAgent } = useKubernetesConnection();
  const [envVars, setEnvVars] = useState<EnvVarEntry[]>([]);

  const {
    register,
    handleSubmit,
    control,
    setValue,
    watch,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<AgentFormData>({
    defaultValues: {
      description: agent.spec.config?.description || '',
      instructions: agent.spec.config?.instructions || '',
      modelAPI: agent.spec.modelAPI || '',
      model: agent.spec.model || '',
      mcpServers: agent.spec.mcpServers || [],
      networkExpose: agent.spec.agentNetwork?.expose || false,
      networkAccess: agent.spec.agentNetwork?.access || [],
      reasoningLoopMaxSteps: agent.spec.config?.reasoningLoopMaxSteps,
      waitForDependencies: agent.spec.waitForDependencies || false,
      gatewayTimeout: agent.spec.gatewayRoute?.timeout || '',
      gatewayRetries: agent.spec.gatewayRoute?.retries,
      memoryEnabled: agent.spec.config?.memory?.enabled !== false,
      memoryContextLimit: agent.spec.config?.memory?.contextLimit,
      memoryMaxSessions: agent.spec.config?.memory?.maxSessions,
      memoryMaxSessionEvents: agent.spec.config?.memory?.maxSessionEvents,
      toolCallMode: agent.spec.config?.toolCallMode || 'auto',
      labels: recordToArray(agent.metadata.labels),
      annotations: recordToArray(agent.metadata.annotations),
    },
  });

  const watchedModelAPI = watch('modelAPI');
  const watchedMcpServers = watch('mcpServers');
  const watchedNetworkExpose = watch('networkExpose');
  const watchedNetworkAccess = watch('networkAccess');
  const watchedWaitForDependencies = watch('waitForDependencies');
  const watchedMemoryEnabled = watch('memoryEnabled');
  const watchedToolCallMode = watch('toolCallMode');

  useEffect(() => {
    reset({
      description: agent.spec.config?.description || '',
      instructions: agent.spec.config?.instructions || '',
      modelAPI: agent.spec.modelAPI || '',
      model: agent.spec.model || '',
      mcpServers: agent.spec.mcpServers || [],
      networkExpose: agent.spec.agentNetwork?.expose || false,
      networkAccess: agent.spec.agentNetwork?.access || [],
      reasoningLoopMaxSteps: agent.spec.config?.reasoningLoopMaxSteps,
      waitForDependencies: agent.spec.waitForDependencies || false,
      gatewayTimeout: agent.spec.gatewayRoute?.timeout || '',
      gatewayRetries: agent.spec.gatewayRoute?.retries,
      memoryEnabled: agent.spec.config?.memory?.enabled !== false,
      memoryContextLimit: agent.spec.config?.memory?.contextLimit,
      memoryMaxSessions: agent.spec.config?.memory?.maxSessions,
      memoryMaxSessionEvents: agent.spec.config?.memory?.maxSessionEvents,
      toolCallMode: agent.spec.config?.toolCallMode || 'auto',
      labels: recordToArray(agent.metadata.labels),
      annotations: recordToArray(agent.metadata.annotations),
    });
    setEnvVars(k8sEnvVarsToEntries(agent.spec.container?.env || agent.spec.config?.env));
  }, [agent, reset]);

  const onSubmit = async (data: AgentFormData) => {
    try {
      const labels = arrayToRecord(data.labels);
      const annotations = arrayToRecord(data.annotations);
      const k8sEnvVars = envVarEntriesToK8sEnvVars(envVars);
      
      // Build memory config
      const memoryConfig = {
        enabled: data.memoryEnabled,
        type: 'local' as const,
        contextLimit: data.memoryContextLimit || undefined,
        maxSessions: data.memoryMaxSessions || undefined,
        maxSessionEvents: data.memoryMaxSessionEvents || undefined,
      };
      
      const updatedAgent: Agent = {
        ...agent,
        metadata: {
          ...agent.metadata,
          labels: Object.keys(labels).length > 0 ? labels : undefined,
          annotations: Object.keys(annotations).length > 0 ? annotations : undefined,
        },
        spec: {
          modelAPI: data.modelAPI,
          model: data.model,
          mcpServers: data.mcpServers.length > 0 ? data.mcpServers : undefined,
          agentNetwork: {
            expose: data.networkExpose,
            access: data.networkAccess.length > 0 ? data.networkAccess : undefined,
          },
          waitForDependencies: data.waitForDependencies || undefined,
          gatewayRoute: (data.gatewayTimeout || data.gatewayRetries)
            ? {
                timeout: data.gatewayTimeout || undefined,
                retries: data.gatewayRetries || undefined,
              }
            : undefined,
          config: {
            description: data.description || undefined,
            instructions: data.instructions || undefined,
            reasoningLoopMaxSteps: data.reasoningLoopMaxSteps || undefined,
            toolCallMode: data.toolCallMode !== 'auto' ? data.toolCallMode : undefined,
            memory: memoryConfig,
          },
          container: k8sEnvVars.length > 0 ? { env: k8sEnvVars } : undefined,
        },
      };

      await updateAgent(updatedAgent);
      
      toast({
        title: 'Agent updated',
        description: `Successfully updated agent "${agent.metadata.name}"`,
      });
      
      onClose();
    } catch (error) {
      toast({
        title: 'Update failed',
        description: error instanceof Error ? error.message : 'Failed to update agent',
        variant: 'destructive',
      });
    }
  };

  const otherAgents = agents.filter((a) => a.metadata.name !== agent.metadata.name);

  const toggleMcpServer = (serverName: string) => {
    const current = watchedMcpServers || [];
    if (current.includes(serverName)) {
      setValue('mcpServers', current.filter((s) => s !== serverName));
    } else {
      setValue('mcpServers', [...current, serverName]);
    }
  };

  const toggleNetworkAccess = (agentName: string) => {
    const current = watchedNetworkAccess || [];
    if (current.includes(agentName)) {
      setValue('networkAccess', current.filter((a) => a !== agentName));
    } else {
      setValue('networkAccess', [...current, agentName]);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(isOpen) => !isOpen && onClose()}>
      <DialogContent className="max-w-2xl max-h-[90vh]">
        <DialogHeader>
          <div className="flex items-center gap-3">
            <div className="h-10 w-10 rounded-lg bg-agent/20 flex items-center justify-center">
              <Bot className="h-5 w-5 text-agent" />
            </div>
            <div>
              <DialogTitle>Edit Agent: {agent.metadata.name}</DialogTitle>
              <DialogDescription className="font-mono text-xs">
                {agent.metadata.namespace}
              </DialogDescription>
            </div>
          </div>
        </DialogHeader>

        <form onSubmit={handleSubmit(onSubmit)}>
          <ScrollArea className="h-[calc(90vh-220px)] pr-4">
            <div className="space-y-6 py-4">
              {/* Description */}
              <div className="space-y-2">
                <Label htmlFor="description">Description</Label>
                <Input
                  id="description"
                  {...register('description')}
                  placeholder="Agent description"
                />
              </div>

              {/* Instructions */}
              <div className="space-y-2">
                <Label htmlFor="instructions">Instructions</Label>
                <Textarea
                  id="instructions"
                  {...register('instructions')}
                  placeholder="Agent instructions and behavior..."
                  rows={4}
                />
              </div>

              {/* Model API */}
              <div className="space-y-2">
                <Label>Model API</Label>
                <Select
                  value={watchedModelAPI}
                  onValueChange={(value) => setValue('modelAPI', value)}
                >
                  <SelectTrigger>
                    <SelectValue placeholder="Select a Model API" />
                  </SelectTrigger>
                  <SelectContent>
                    {modelAPIs.map((api) => (
                      <SelectItem key={api.metadata.name} value={api.metadata.name}>
                        {api.metadata.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              {/* Model */}
              <div className="space-y-2">
                <Label htmlFor="model">Model <span className="text-destructive">*</span></Label>
                <Input
                  id="model"
                  {...register('model', { required: 'Model is required' })}
                  placeholder="e.g., openai/gpt-4o, ollama/smollm2:135m"
                  className="font-mono"
                />
                {errors.model && (
                  <p className="text-sm text-destructive">{errors.model.message}</p>
                )}
                <p className="text-xs text-muted-foreground">
                  Must be supported by the selected ModelAPI
                </p>
              </div>

              {/* MCP Servers */}
              {mcpServers.length > 0 && (
                <div className="space-y-2">
                  <Label>MCP Servers</Label>
                  <div className="flex flex-wrap gap-2">
                    {mcpServers.map((server) => (
                      <Button
                        key={server.metadata.name}
                        type="button"
                        variant={watchedMcpServers?.includes(server.metadata.name) ? 'default' : 'outline'}
                        size="sm"
                        onClick={() => toggleMcpServer(server.metadata.name)}
                      >
                        {server.metadata.name}
                      </Button>
                    ))}
                  </div>
                </div>
              )}

              <Separator />

              {/* Reasoning Loop Settings */}
              <div className="space-y-4">
                <Label className="text-sm font-medium">Reasoning Settings</Label>
                <div className="grid grid-cols-2 gap-4">
                  <div className="space-y-2">
                    <Label htmlFor="reasoningLoopMaxSteps" className="text-xs text-muted-foreground">
                      Max Reasoning Steps
                    </Label>
                    <Input
                      id="reasoningLoopMaxSteps"
                      type="number"
                      min={1}
                      max={20}
                      {...register('reasoningLoopMaxSteps', { valueAsNumber: true })}
                      placeholder="Default: 5"
                      className="font-mono text-sm"
                    />
                    <p className="text-[10px] text-muted-foreground">
                      Max iterations before stopping (1-20)
                    </p>
                  </div>
                  <div className="space-y-2">
                    <Label className="text-xs text-muted-foreground">Wait for Dependencies</Label>
                    <div className="flex items-center gap-2 pt-2">
                      <Switch
                        checked={watchedWaitForDependencies}
                        onCheckedChange={(checked) => setValue('waitForDependencies', checked)}
                      />
                      <span className="text-sm text-muted-foreground">
                        {watchedWaitForDependencies ? 'Enabled' : 'Disabled'}
                      </span>
                    </div>
                    <p className="text-[10px] text-muted-foreground">
                      Wait for ModelAPI and MCPServers to be ready
                    </p>
                  </div>
                </div>
              </div>

              <Separator />

              {/* Agent Network */}
              <div className="space-y-4">
                <Label className="text-sm font-medium">Agent Network</Label>
                <div className="flex items-center justify-between">
                  <span className="text-sm text-muted-foreground">Expose Agent</span>
                  <Switch
                    checked={watchedNetworkExpose}
                    onCheckedChange={(checked) => setValue('networkExpose', checked)}
                  />
                </div>
                
                {otherAgents.length > 0 && (
                  <div className="space-y-2">
                    <span className="text-sm text-muted-foreground">Peer Access</span>
                    <div className="flex flex-wrap gap-2">
                      {otherAgents.map((a) => (
                        <Button
                          key={a.metadata.name}
                          type="button"
                          variant={watchedNetworkAccess?.includes(a.metadata.name) ? 'default' : 'outline'}
                          size="sm"
                          onClick={() => toggleNetworkAccess(a.metadata.name)}
                        >
                          {a.metadata.name}
                        </Button>
                      ))}
                    </div>
                  </div>
                )}
              </div>

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

              {/* Memory Configuration */}
              <div className="space-y-4">
                <Label className="text-sm font-medium">Memory Configuration</Label>
                <div className="flex items-center justify-between">
                  <div>
                    <span className="text-sm text-muted-foreground">Enable Memory</span>
                    <p className="text-[10px] text-muted-foreground">
                      Store conversation history and events
                    </p>
                  </div>
                  <Switch
                    checked={watchedMemoryEnabled}
                    onCheckedChange={(checked) => setValue('memoryEnabled', checked)}
                  />
                </div>
                
                {watchedMemoryEnabled && (
                  <div className="grid grid-cols-3 gap-4">
                    <div className="space-y-2">
                      <Label htmlFor="memoryContextLimit" className="text-xs text-muted-foreground">
                        Context Limit
                      </Label>
                      <Input
                        id="memoryContextLimit"
                        type="number"
                        min={1}
                        max={100}
                        {...register('memoryContextLimit', { valueAsNumber: true })}
                        placeholder="6"
                        className="font-mono text-sm"
                      />
                      <p className="text-[10px] text-muted-foreground">
                        Messages for delegation
                      </p>
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="memoryMaxSessions" className="text-xs text-muted-foreground">
                        Max Sessions
                      </Label>
                      <Input
                        id="memoryMaxSessions"
                        type="number"
                        min={1}
                        {...register('memoryMaxSessions', { valueAsNumber: true })}
                        placeholder="1000"
                        className="font-mono text-sm"
                      />
                      <p className="text-[10px] text-muted-foreground">
                        Sessions to keep
                      </p>
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="memoryMaxSessionEvents" className="text-xs text-muted-foreground">
                        Max Events
                      </Label>
                      <Input
                        id="memoryMaxSessionEvents"
                        type="number"
                        min={1}
                        {...register('memoryMaxSessionEvents', { valueAsNumber: true })}
                        placeholder="500"
                        className="font-mono text-sm"
                      />
                      <p className="text-[10px] text-muted-foreground">
                        Events per session
                      </p>
                    </div>
                  </div>
                )}
              </div>

              <Separator />

              {/* Environment Variables with Secrets */}
              <EnvVarEditorWithSecrets
                fields={envVars}
                onChange={setEnvVars}
              />

              <Separator />

              {/* Tool Call Mode */}
              <div className="space-y-2">
                <div className="flex items-center gap-2">
                  <Label className="text-sm font-medium">Tool Call Mode</Label>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <Info className="h-3.5 w-3.5 text-muted-foreground cursor-help" />
                    </TooltipTrigger>
                    <TooltipContent side="right" className="max-w-[280px]">
                      <p className="text-xs"><strong>Auto</strong> (default): Detects whether the model supports native function calling, falling back to string-based tool calls.</p>
                      <p className="text-xs mt-1"><strong>Native</strong>: Forces OpenAI-compatible structured tool calling.</p>
                      <p className="text-xs mt-1"><strong>String</strong>: Forces text-based JSON tool calls for models without native support.</p>
                    </TooltipContent>
                  </Tooltip>
                </div>
                <Select
                  value={watchedToolCallMode}
                  onValueChange={(value: 'auto' | 'native' | 'string') => setValue('toolCallMode', value)}
                >
                  <SelectTrigger className="font-mono text-sm">
                    <SelectValue placeholder="auto" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="auto">auto</SelectItem>
                    <SelectItem value="native">native</SelectItem>
                    <SelectItem value="string">string</SelectItem>
                  </SelectContent>
                </Select>
                <p className="text-[10px] text-muted-foreground">
                  How the agent invokes tools and delegates to sub-agents
                </p>
              </div>

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
