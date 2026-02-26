import React, { useState } from 'react';
import { useForm } from 'react-hook-form';
import { Bot, Info } from 'lucide-react';
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
import { 
  EnvVarEditorWithSecrets, 
  EnvVarEntry, 
  envVarEntriesToK8sEnvVars 
} from './shared/EnvVarEditorWithSecrets';
import { validateKubernetesName } from './shared/EnvVarEditor';
import type { Agent } from '@/types/kubernetes';

interface AgentFormData {
  name: string;
  description: string;
  instructions: string;
  modelAPI: string;
  model: string;
  mcpServers: string[];
  networkExpose: boolean;
  networkAccess: string[];
  // Memory configuration
  memoryEnabled: boolean;
  memoryContextLimit: number | undefined;
  memoryMaxSessions: number | undefined;
  memoryMaxSessionEvents: number | undefined;
  toolCallMode: 'auto' | 'native' | 'string';
}

interface AgentCreateDialogProps {
  open: boolean;
  onClose: () => void;
}

export function AgentCreateDialog({ open, onClose }: AgentCreateDialogProps) {
  const { toast } = useToast();
  const { modelAPIs, mcpServers, agents } = useKubernetesStore();
  const { namespace, createAgent } = useKubernetesConnection();
  const [envVars, setEnvVars] = useState<EnvVarEntry[]>([]);

  const {
    register,
    handleSubmit,
    watch,
    setValue,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<AgentFormData>({
    defaultValues: {
      name: '',
      description: '',
      instructions: '',
      modelAPI: '',
      model: '',
      mcpServers: [],
      networkExpose: false,
      networkAccess: [],
      memoryEnabled: true,
      memoryContextLimit: undefined,
      memoryMaxSessions: undefined,
      memoryMaxSessionEvents: undefined,
      toolCallMode: 'auto',
    },
  });

  const watchedModelAPI = watch('modelAPI');
  const watchedMcpServers = watch('mcpServers');
  const watchedNetworkExpose = watch('networkExpose');
  const watchedNetworkAccess = watch('networkAccess');
  const watchedMemoryEnabled = watch('memoryEnabled');
  const watchedToolCallMode = watch('toolCallMode');

  const validateUniqueName = (name: string) => {
    if (agents.some((agent) => agent.metadata.name === name)) {
      return 'An Agent with this name already exists';
    }
    return true;
  };

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

  const onSubmit = async (data: AgentFormData) => {
    try {
      const k8sEnvVars = envVarEntriesToK8sEnvVars(envVars);
      
      // Build memory config if not using defaults
      const memoryConfig = data.memoryEnabled !== true || 
        data.memoryContextLimit || data.memoryMaxSessions || data.memoryMaxSessionEvents
        ? {
            enabled: data.memoryEnabled,
            type: 'local' as const,
            contextLimit: data.memoryContextLimit || undefined,
            maxSessions: data.memoryMaxSessions || undefined,
            maxSessionEvents: data.memoryMaxSessionEvents || undefined,
          }
        : undefined;
      
      const newAgent: Agent = {
        apiVersion: 'kaos.tools/v1alpha1',
        kind: 'Agent',
        metadata: {
          name: data.name,
          namespace: namespace || 'default',
        },
        spec: {
          modelAPI: data.modelAPI,
          model: data.model,
          mcpServers: data.mcpServers.length > 0 ? data.mcpServers : undefined,
          agentNetwork: {
            expose: data.networkExpose,
            access: data.networkAccess.length > 0 ? data.networkAccess : undefined,
          },
          config: {
            description: data.description,
            instructions: data.instructions,
            toolCallMode: data.toolCallMode !== 'auto' ? data.toolCallMode : undefined,
            memory: memoryConfig,
          },
          container: k8sEnvVars.length > 0 ? { env: k8sEnvVars } : undefined,
        },
      };

      await createAgent(newAgent);
      
      toast({
        title: 'Agent created',
        description: `Successfully created Agent "${data.name}"`,
      });
      
      reset();
      setEnvVars([]);
      onClose();
    } catch (error) {
      toast({
        title: 'Creation failed',
        description: error instanceof Error ? error.message : 'Failed to create Agent',
        variant: 'destructive',
      });
    }
  };

  const handleClose = () => {
    reset();
    setEnvVars([]);
    onClose();
  };

  return (
    <Dialog open={open} onOpenChange={(isOpen) => !isOpen && handleClose()}>
      <DialogContent className="max-w-2xl max-h-[90vh]">
        <DialogHeader>
          <div className="flex items-center gap-3">
            <div className="h-10 w-10 rounded-lg bg-agent/20 flex items-center justify-center">
              <Bot className="h-5 w-5 text-agent" />
            </div>
            <div>
              <DialogTitle>Create Agent</DialogTitle>
              <DialogDescription>
                Create a new AI Agent with LLM and tool access
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
                  placeholder="my-agent"
                  className="font-mono"
                />
                {errors.name && (
                  <p className="text-sm text-destructive">{errors.name.message}</p>
                )}
              </div>

              {/* Description */}
              <div className="space-y-2">
                <Label htmlFor="description">Description</Label>
                <Input
                  id="description"
                  {...register('description', { required: 'Description is required' })}
                  placeholder="Agent description"
                />
                {errors.description && (
                  <p className="text-sm text-destructive">{errors.description.message}</p>
                )}
              </div>

              {/* Instructions */}
              <div className="space-y-2">
                <Label htmlFor="instructions">Instructions</Label>
                <Textarea
                  id="instructions"
                  {...register('instructions', { required: 'Instructions are required' })}
                  placeholder="Agent instructions and behavior..."
                  rows={4}
                />
                {errors.instructions && (
                  <p className="text-sm text-destructive">{errors.instructions.message}</p>
                )}
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
                {modelAPIs.length === 0 && (
                  <p className="text-xs text-muted-foreground">
                    No Model APIs available. Create one first.
                  </p>
                )}
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

              {/* Agent Network */}
              <div className="space-y-4">
                <Label>Agent Network</Label>
                <div className="flex items-center justify-between">
                  <span className="text-sm text-muted-foreground">Expose Agent</span>
                  <Switch
                    checked={watchedNetworkExpose}
                    onCheckedChange={(checked) => setValue('networkExpose', checked)}
                  />
                </div>
                
                {agents.length > 0 && (
                  <div className="space-y-2">
                    <span className="text-sm text-muted-foreground">Peer Access</span>
                    <div className="flex flex-wrap gap-2">
                      {agents.map((a) => (
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
            </div>
          </ScrollArea>

          <DialogFooter className="pt-4 border-t mt-4">
            <Button type="button" variant="outline" onClick={handleClose}>
              Cancel
            </Button>
            <Button type="submit" disabled={isSubmitting}>
              {isSubmitting ? 'Creating...' : 'Create Agent'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
