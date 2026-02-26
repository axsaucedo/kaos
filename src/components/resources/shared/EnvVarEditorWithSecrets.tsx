import React, { useState } from 'react';
import { Plus, Trash2, KeyRound, Lock } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover';
import { Badge } from '@/components/ui/badge';
import { useKubernetesStore } from '@/stores/kubernetesStore';
import { CreateSecretDialog } from '@/components/kubernetes/CreateSecretDialog';
import type { EnvVar, K8sSecret } from '@/types/kubernetes';

export interface EnvVarEntry {
  name: string;
  value: string;
  valueType: 'plain' | 'secret';
  secretName?: string;
  secretKey?: string;
}

interface EnvVarEditorWithSecretsProps {
  fields: EnvVarEntry[];
  onChange: (fields: EnvVarEntry[]) => void;
  label?: string;
}

export function EnvVarEditorWithSecrets({ 
  fields, 
  onChange,
  label = "Environment Variables",
}: EnvVarEditorWithSecretsProps) {
  const { secrets } = useKubernetesStore();
  const [createSecretOpen, setCreateSecretOpen] = useState(false);
  const [pendingSecretIndex, setPendingSecretIndex] = useState<number | null>(null);

  const addEntry = () => {
    onChange([...fields, { name: '', value: '', valueType: 'plain' }]);
  };

  const removeEntry = (index: number) => {
    onChange(fields.filter((_, i) => i !== index));
  };

  const updateEntry = (index: number, updates: Partial<EnvVarEntry>) => {
    onChange(fields.map((entry, i) => 
      i === index ? { ...entry, ...updates } : entry
    ));
  };

  const handleSecretSelect = (index: number, secretName: string, secretKey: string) => {
    updateEntry(index, { 
      valueType: 'secret', 
      secretName, 
      secretKey,
      value: '' // Clear plain value when using secret
    });
  };

  const handleCreateNewSecret = (index: number) => {
    setPendingSecretIndex(index);
    setCreateSecretOpen(true);
  };

  const handleSecretCreated = (secretName: string, keys: string[]) => {
    if (pendingSecretIndex !== null && keys.length > 0) {
      // Auto-select the first key of the newly created secret
      handleSecretSelect(pendingSecretIndex, secretName, keys[0]);
    }
    setPendingSecretIndex(null);
  };

  const getSecretKeys = (secretName: string): string[] => {
    const secret = secrets.find(s => s.metadata.name === secretName);
    return secret?.dataKeys || [];
  };

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <Label>{label}</Label>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={addEntry}
        >
          <Plus className="h-4 w-4 mr-1" />
          Add
        </Button>
      </div>
      
      {fields.length > 0 && (
        <div className="space-y-2">
          {fields.map((field, index) => (
            <div key={index} className="space-y-2 p-3 bg-muted/30 rounded-lg border border-border/50">
              <div className="flex gap-2 items-center">
                <Input
                  value={field.name}
                  onChange={(e) => updateEntry(index, { name: e.target.value })}
                  placeholder="ENV_NAME"
                  className="font-mono text-sm flex-1"
                />
                <Select 
                  value={field.valueType} 
                  onValueChange={(v: 'plain' | 'secret') => updateEntry(index, { valueType: v })}
                >
                  <SelectTrigger className="w-[120px]">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="plain">Plain Value</SelectItem>
                    <SelectItem value="secret">From Secret</SelectItem>
                  </SelectContent>
                </Select>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  onClick={() => removeEntry(index)}
                >
                  <Trash2 className="h-4 w-4 text-destructive" />
                </Button>
              </div>
              
              {field.valueType === 'plain' ? (
                <Input
                  value={field.value}
                  onChange={(e) => updateEntry(index, { value: e.target.value })}
                  placeholder="value"
                  className="font-mono text-sm"
                />
              ) : (
                <div className="flex gap-2">
                  <Popover>
                    <PopoverTrigger asChild>
                      <Button 
                        type="button" 
                        variant="outline" 
                        className="flex-1 justify-start font-mono text-sm"
                      >
                        {field.secretName ? (
                          <div className="flex items-center gap-2">
                            <Lock className="h-3 w-3 text-warning" />
                            <span>{field.secretName}</span>
                            {field.secretKey && (
                              <>
                                <span className="text-muted-foreground">/</span>
                                <Badge variant="secondary" className="font-mono text-xs">
                                  {field.secretKey}
                                </Badge>
                              </>
                            )}
                          </div>
                        ) : (
                          <span className="text-muted-foreground">Select secret...</span>
                        )}
                      </Button>
                    </PopoverTrigger>
                    <PopoverContent className="w-80 p-0" align="start">
                      <div className="p-2 border-b border-border">
                        <p className="text-sm font-medium">Select Secret</p>
                        <p className="text-xs text-muted-foreground">
                          Choose a secret and key to reference
                        </p>
                      </div>
                      <div className="max-h-[200px] overflow-y-auto p-2">
                        {secrets.length === 0 ? (
                          <p className="text-sm text-muted-foreground text-center py-4">
                            No secrets available
                          </p>
                        ) : (
                          <div className="space-y-1">
                            {secrets.map((secret) => {
                              const keys = secret.dataKeys || [];
                              if (keys.length === 0) return null;
                              
                              return (
                                <div key={secret.metadata.name} className="space-y-1">
                                  <p className="text-xs font-medium text-muted-foreground px-2 py-1">
                                    {secret.metadata.name}
                                  </p>
                                  {keys.map((key) => (
                                    <Button
                                      key={`${secret.metadata.name}/${key}`}
                                      type="button"
                                      variant="ghost"
                                      size="sm"
                                      className="w-full justify-start font-mono text-xs"
                                      onClick={() => handleSecretSelect(index, secret.metadata.name, key)}
                                    >
                                      <KeyRound className="h-3 w-3 mr-2 text-warning" />
                                      {key}
                                    </Button>
                                  ))}
                                </div>
                              );
                            })}
                          </div>
                        )}
                      </div>
                      <div className="p-2 border-t border-border">
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          className="w-full"
                          onClick={() => handleCreateNewSecret(index)}
                        >
                          <Plus className="h-4 w-4 mr-1" />
                          Create New Secret
                        </Button>
                      </div>
                    </PopoverContent>
                  </Popover>
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      <CreateSecretDialog
        open={createSecretOpen}
        onOpenChange={setCreateSecretOpen}
        onSecretCreated={handleSecretCreated}
      />
    </div>
  );
}

// Helper to convert EnvVarEntry[] to the Kubernetes EnvVar[] format
export function envVarEntriesToK8sEnvVars(entries: EnvVarEntry[]): EnvVar[] {
  return entries
    .filter(e => e.name.trim())
    .map(e => {
      if (e.valueType === 'secret' && e.secretName && e.secretKey) {
        return {
          name: e.name,
          valueFrom: {
            secretKeyRef: {
              name: e.secretName,
              key: e.secretKey,
            },
          },
        };
      }
      return {
        name: e.name,
        value: e.value,
      };
    });
}

// Helper to convert Kubernetes EnvVar[] to EnvVarEntry[] format
export function k8sEnvVarsToEntries(envVars?: EnvVar[]): EnvVarEntry[] {
  if (!envVars) return [];
  return envVars.map(e => {
    if (e.valueFrom?.secretKeyRef) {
      return {
        name: e.name,
        value: '',
        valueType: 'secret' as const,
        secretName: e.valueFrom.secretKeyRef.name,
        secretKey: e.valueFrom.secretKeyRef.key,
      };
    }
    return {
      name: e.name,
      value: e.value || '',
      valueType: 'plain' as const,
    };
  });
}
