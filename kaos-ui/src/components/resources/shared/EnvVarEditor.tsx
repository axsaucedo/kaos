import React from 'react';
import { Plus, Trash2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { UseFieldArrayReturn } from 'react-hook-form';

interface EnvVarEditorProps {
  fields: { id: string; name: string; value: string }[];
  register: (name: string) => any;
  append: (value: { name: string; value: string }) => void;
  remove: (index: number) => void;
  fieldPrefix: string;
}

export function EnvVarEditor({ 
  fields, 
  register, 
  append, 
  remove, 
  fieldPrefix 
}: EnvVarEditorProps) {
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <Label>Environment Variables</Label>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => append({ name: '', value: '' })}
        >
          <Plus className="h-4 w-4 mr-1" />
          Add
        </Button>
      </div>
      {fields.length > 0 && (
        <div className="space-y-2">
          {fields.map((field, index) => (
            <div key={field.id} className="flex gap-2">
              <Input
                {...register(`${fieldPrefix}.${index}.name`)}
                placeholder="NAME"
                className="font-mono text-sm"
              />
              <Input
                {...register(`${fieldPrefix}.${index}.value`)}
                placeholder="value"
                className="font-mono text-sm"
              />
              <Button
                type="button"
                variant="ghost"
                size="icon"
                onClick={() => remove(index)}
              >
                <Trash2 className="h-4 w-4 text-destructive" />
              </Button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// Kubernetes RFC 1123 name validation
export function validateKubernetesName(name: string): string | true {
  if (!name) return 'Name is required';
  if (name.length > 253) return 'Name must be 253 characters or less';
  if (!/^[a-z0-9]([-a-z0-9]*[a-z0-9])?$/.test(name)) {
    return 'Name must be lowercase, start with alphanumeric, and contain only alphanumeric or hyphens';
  }
  return true;
}
