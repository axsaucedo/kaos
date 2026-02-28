import React from 'react';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';

interface ContainerSelectorProps {
  containers: string[];
  selectedContainer: string;
  onContainerChange: (container: string) => void;
  className?: string;
}

export function ContainerSelector({ containers, selectedContainer, onContainerChange, className = 'w-[180px]' }: ContainerSelectorProps) {
  if (containers.length <= 1) return null;

  return (
    <Select value={selectedContainer} onValueChange={onContainerChange}>
      <SelectTrigger className={className}>
        <SelectValue placeholder="Select container" />
      </SelectTrigger>
      <SelectContent>
        {containers.map(container => (
          <SelectItem key={container} value={container}>
            {container}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
