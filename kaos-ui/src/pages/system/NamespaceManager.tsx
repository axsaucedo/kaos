import React from 'react';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';

interface NamespaceManagerProps {
  kaosNamespace: string;
  editingNamespace: boolean;
  tempNamespace: string;
  onEditStart: () => void;
  onEditCancel: () => void;
  onTempNamespaceChange: (value: string) => void;
  onSave: () => void;
}

export default function NamespaceManager({
  kaosNamespace,
  editingNamespace,
  tempNamespace,
  onEditStart,
  onEditCancel,
  onTempNamespaceChange,
  onSave,
}: NamespaceManagerProps) {
  if (editingNamespace) {
    return (
      <div className="flex items-center gap-2">
        <Input
          value={tempNamespace}
          onChange={(e) => onTempNamespaceChange(e.target.value)}
          className="w-40 h-8 text-sm"
          placeholder="Namespace"
        />
        <Button size="sm" onClick={onSave}>Save</Button>
        <Button size="sm" variant="outline" onClick={onEditCancel}>Cancel</Button>
      </div>
    );
  }

  return (
    <Button variant="outline" size="sm" onClick={onEditStart}>
      <span className="text-xs text-muted-foreground mr-2">Namespace:</span>
      <code className="text-xs">{kaosNamespace}</code>
    </Button>
  );
}
