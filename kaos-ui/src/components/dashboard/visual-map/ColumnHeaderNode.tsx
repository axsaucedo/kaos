import React from 'react';
import type { ColumnHeaderData } from './types';

interface ColumnHeaderNodeProps {
  data: ColumnHeaderData;
}

export function ColumnHeaderNode({ data }: ColumnHeaderNodeProps) {
  return (
    <div className="flex items-center gap-2 pointer-events-auto select-none">
      <span className="text-xs font-bold uppercase tracking-widest text-muted-foreground/60">
        {data.label}
      </span>
      <span className="text-[10px] text-muted-foreground/40">({data.count})</span>
    </div>
  );
}
