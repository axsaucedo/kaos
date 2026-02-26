import React, { useState } from 'react';
import { Plus, Trash2, KeyRound } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { useKubernetesConnection } from '@/contexts/KubernetesConnectionContext';
import { toast } from 'sonner';

export interface SecretFormData {
  name: string;
  type: string;
  data: { key: string; value: string }[];
}

export interface CreateSecretDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSecretCreated?: (secretName: string, keys: string[]) => void;
  /** Pre-fill with a single key for quick secret creation */
  initialKey?: string;
  /** Pre-fill the secret name */
  initialName?: string;
}

export function CreateSecretDialog({ 
  open, 
  onOpenChange, 
  onSecretCreated,
  initialKey,
  initialName,
}: CreateSecretDialogProps) {
  const { createSecret, namespace } = useKubernetesConnection();
  
  const [isCreating, setIsCreating] = useState(false);
  const [formData, setFormData] = useState<SecretFormData>({
    name: initialName || '',
    type: 'Opaque',
    data: [{ key: initialKey || '', value: '' }],
  });

  // Reset form when dialog opens with new initial values
  React.useEffect(() => {
    if (open) {
      setFormData({
        name: initialName || '',
        type: 'Opaque',
        data: [{ key: initialKey || '', value: '' }],
      });
    }
  }, [open, initialKey, initialName]);

  const handleCreateSecret = async () => {
    if (!formData.name.trim()) {
      toast.error('Secret name is required');
      return;
    }

    // Validate kubernetes naming
    if (!/^[a-z0-9]([-a-z0-9]*[a-z0-9])?$/.test(formData.name)) {
      toast.error('Name must be lowercase, start with alphanumeric, and contain only alphanumeric or hyphens');
      return;
    }

    // Filter out empty entries and encode values to base64
    const secretData: Record<string, string> = {};
    const keys: string[] = [];
    for (const entry of formData.data) {
      if (entry.key.trim() && entry.value.trim()) {
        secretData[entry.key.trim()] = btoa(entry.value);
        keys.push(entry.key.trim());
      }
    }

    if (Object.keys(secretData).length === 0) {
      toast.error('At least one key-value pair is required');
      return;
    }

    setIsCreating(true);
    try {
      await createSecret({
        apiVersion: 'v1',
        kind: 'Secret',
        metadata: {
          name: formData.name.trim(),
          namespace: namespace || 'default',
        },
        type: formData.type,
        data: secretData,
      });
      toast.success(`Secret "${formData.name}" created successfully`);
      onOpenChange(false);
      onSecretCreated?.(formData.name.trim(), keys);
      setFormData({ name: '', type: 'Opaque', data: [{ key: '', value: '' }] });
    } catch (error) {
      toast.error(`Failed to create secret: ${error instanceof Error ? error.message : 'Unknown error'}`);
    } finally {
      setIsCreating(false);
    }
  };

  const addDataEntry = () => {
    setFormData(prev => ({
      ...prev,
      data: [...prev.data, { key: '', value: '' }],
    }));
  };

  const removeDataEntry = (index: number) => {
    setFormData(prev => ({
      ...prev,
      data: prev.data.filter((_, i) => i !== index),
    }));
  };

  const updateDataEntry = (index: number, field: 'key' | 'value', value: string) => {
    setFormData(prev => ({
      ...prev,
      data: prev.data.map((entry, i) =>
        i === index ? { ...entry, [field]: value } : entry
      ),
    }));
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <div className="flex items-center gap-3">
            <div className="h-10 w-10 rounded-lg bg-warning/20 flex items-center justify-center">
              <KeyRound className="h-5 w-5 text-warning" />
            </div>
            <div>
              <DialogTitle>Create Secret</DialogTitle>
              <DialogDescription>
                Create a new Kubernetes secret to store sensitive data like API keys, passwords, or tokens.
              </DialogDescription>
            </div>
          </div>
        </DialogHeader>
        <div className="space-y-4 py-4">
          <div className="space-y-2">
            <Label htmlFor="secret-name">Secret Name</Label>
            <Input
              id="secret-name"
              placeholder="my-api-keys"
              value={formData.name}
              onChange={(e) => setFormData(prev => ({ ...prev, name: e.target.value }))}
              className="font-mono"
            />
            <p className="text-xs text-muted-foreground">
              Must be lowercase, start with a letter or number, and contain only letters, numbers, or hyphens.
            </p>
          </div>

          <div className="space-y-2">
            <Label htmlFor="secret-type">Secret Type</Label>
            <Select
              value={formData.type}
              onValueChange={(value) => setFormData(prev => ({ ...prev, type: value }))}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="Opaque">Opaque (Generic)</SelectItem>
                <SelectItem value="kubernetes.io/basic-auth">Basic Auth</SelectItem>
                <SelectItem value="kubernetes.io/tls">TLS Certificate</SelectItem>
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <Label>Secret Data</Label>
              <Button type="button" variant="outline" size="sm" onClick={addDataEntry}>
                <Plus className="h-4 w-4 mr-1" />
                Add Key
              </Button>
            </div>
            <div className="space-y-2">
              {formData.data.map((entry, index) => (
                <div key={index} className="flex gap-2">
                  <Input
                    placeholder="KEY"
                    value={entry.key}
                    onChange={(e) => updateDataEntry(index, 'key', e.target.value)}
                    className="font-mono text-sm"
                  />
                  <Input
                    type="password"
                    placeholder="value"
                    value={entry.value}
                    onChange={(e) => updateDataEntry(index, 'value', e.target.value)}
                    className="font-mono text-sm"
                  />
                  {formData.data.length > 1 && (
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      onClick={() => removeDataEntry(index)}
                    >
                      <Trash2 className="h-4 w-4 text-destructive" />
                    </Button>
                  )}
                </div>
              ))}
            </div>
            <p className="text-xs text-muted-foreground">
              Values will be automatically base64 encoded when stored.
            </p>
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button onClick={handleCreateSecret} disabled={isCreating}>
            {isCreating ? 'Creating...' : 'Create Secret'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
