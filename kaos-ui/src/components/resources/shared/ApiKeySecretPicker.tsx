import React, { useState } from 'react';
import { Plus, KeyRound, Lock, Eye, EyeOff } from 'lucide-react';
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
import type { ApiKeySource } from '@/types/kubernetes';

export type ApiKeyType = 'none' | 'value' | 'secretKeyRef';

interface ApiKeySecretPickerProps {
  value: {
    type: ApiKeyType;
    directValue?: string;
    secretName?: string;
    secretKey?: string;
  };
  onChange: (value: ApiKeySecretPickerProps['value']) => void;
  label?: string;
}

export function ApiKeySecretPicker({ 
  value, 
  onChange,
  label = "API Key",
}: ApiKeySecretPickerProps) {
  const { secrets } = useKubernetesStore();
  const [createSecretOpen, setCreateSecretOpen] = useState(false);
  const [showPassword, setShowPassword] = useState(false);

  const handleTypeChange = (type: ApiKeyType) => {
    onChange({ 
      ...value, 
      type,
      // Clear other fields when switching types
      directValue: type === 'value' ? value.directValue : undefined,
      secretName: type === 'secretKeyRef' ? value.secretName : undefined,
      secretKey: type === 'secretKeyRef' ? value.secretKey : undefined,
    });
  };

  const handleSecretSelect = (secretName: string, secretKey: string) => {
    onChange({ 
      type: 'secretKeyRef', 
      secretName, 
      secretKey,
    });
  };

  const handleSecretCreated = (secretName: string, keys: string[]) => {
    if (keys.length > 0) {
      handleSecretSelect(secretName, keys[0]);
    }
  };

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <Label className="flex items-center gap-2">
          <KeyRound className="h-4 w-4" />
          {label}
        </Label>
      </div>
      
      <Select value={value.type} onValueChange={handleTypeChange}>
        <SelectTrigger>
          <SelectValue placeholder="Select API key source" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="none">No API Key</SelectItem>
          <SelectItem value="value">Direct Value</SelectItem>
          <SelectItem value="secretKeyRef">From Secret</SelectItem>
        </SelectContent>
      </Select>

      {value.type === 'value' && (
        <div className="space-y-2">
          <div className="relative">
            <Input
              type={showPassword ? 'text' : 'password'}
              value={value.directValue || ''}
              onChange={(e) => onChange({ ...value, directValue: e.target.value })}
              placeholder="sk-..."
              className="font-mono pr-10"
            />
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => setShowPassword(!showPassword)}
              className="absolute right-0 top-0 h-full px-3 hover:bg-transparent"
            >
              {showPassword ? (
                <EyeOff className="h-4 w-4 text-muted-foreground" />
              ) : (
                <Eye className="h-4 w-4 text-muted-foreground" />
              )}
            </Button>
          </div>
          <p className="text-xs text-warning flex items-center gap-1">
            <Lock className="h-3 w-3" />
            Not recommended for production - use Secret reference instead
          </p>
        </div>
      )}

      {value.type === 'secretKeyRef' && (
        <Popover>
          <PopoverTrigger asChild>
            <Button 
              type="button" 
              variant="outline" 
              className="w-full justify-start font-mono text-sm"
            >
              {value.secretName ? (
                <div className="flex items-center gap-2">
                  <Lock className="h-3 w-3 text-warning" />
                  <span>{value.secretName}</span>
                  {value.secretKey && (
                    <>
                      <span className="text-muted-foreground">/</span>
                      <Badge variant="secondary" className="font-mono text-xs">
                        {value.secretKey}
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
                            onClick={() => handleSecretSelect(secret.metadata.name, key)}
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
                onClick={() => setCreateSecretOpen(true)}
              >
                <Plus className="h-4 w-4 mr-1" />
                Create New Secret
              </Button>
            </div>
          </PopoverContent>
        </Popover>
      )}

      <p className="text-xs text-muted-foreground">
        Set as <code className="bg-muted px-1 rounded">PROXY_API_KEY</code> env var for LiteLLM config.
      </p>

      <CreateSecretDialog
        open={createSecretOpen}
        onOpenChange={setCreateSecretOpen}
        onSecretCreated={handleSecretCreated}
      />
    </div>
  );
}

// Helper to convert picker value to ApiKeySource
export function pickerValueToApiKeySource(value: ApiKeySecretPickerProps['value']): ApiKeySource | undefined {
  switch (value.type) {
    case 'value':
      return value.directValue ? { value: value.directValue } : undefined;
    case 'secretKeyRef':
      return value.secretName && value.secretKey
        ? { valueFrom: { secretKeyRef: { name: value.secretName, key: value.secretKey } } }
        : undefined;
    default:
      return undefined;
  }
}

// Helper to convert ApiKeySource to picker value
export function apiKeySourceToPickerValue(source?: ApiKeySource): ApiKeySecretPickerProps['value'] {
  if (!source) {
    return { type: 'none' };
  }
  if (source.value) {
    return { type: 'value', directValue: source.value };
  }
  if (source.valueFrom?.secretKeyRef) {
    return { 
      type: 'secretKeyRef', 
      secretName: source.valueFrom.secretKeyRef.name,
      secretKey: source.valueFrom.secretKeyRef.key,
    };
  }
  return { type: 'none' };
}
