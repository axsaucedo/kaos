import React from 'react';
import { UseFormRegister } from 'react-hook-form';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';

interface GatewayRouteEditorProps {
  register: UseFormRegister<any>;
  prefix?: string;
}

export function GatewayRouteEditor({ register, prefix = '' }: GatewayRouteEditorProps) {
  const fieldName = (name: string) => prefix ? `${prefix}.${name}` : name;

  return (
    <div className="space-y-4">
      <Label className="text-sm font-medium">Gateway Route Settings</Label>
      <div className="grid grid-cols-2 gap-4">
        <div className="space-y-2">
          <Label htmlFor={fieldName('timeout')} className="text-xs text-muted-foreground">
            Timeout
          </Label>
          <Input
            id={fieldName('timeout')}
            {...register(fieldName('timeout') as any)}
            placeholder="e.g., 30s, 5m"
            className="font-mono text-sm"
          />
          <p className="text-[10px] text-muted-foreground">
            Request timeout (e.g., "30s", "5m")
          </p>
        </div>
        <div className="space-y-2">
          <Label htmlFor={fieldName('retries')} className="text-xs text-muted-foreground">
            Retries
          </Label>
          <Input
            id={fieldName('retries')}
            type="number"
            min={0}
            max={10}
            {...register(fieldName('retries') as any, { valueAsNumber: true })}
            placeholder="e.g., 3"
            className="font-mono text-sm"
          />
          <p className="text-[10px] text-muted-foreground">
            Number of retry attempts
          </p>
        </div>
      </div>
    </div>
  );
}
