import React from 'react';
import { Search, LayoutGrid, Maximize, Plus } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Tooltip, TooltipTrigger, TooltipContent } from '@/components/ui/tooltip';
import type { ResourceKind } from './types';

interface VisualMapToolbarProps {
  kindFilter: Set<ResourceKind>;
  statusFilter: Set<string>;
  searchQuery: string;
  onToggleKind: (kind: ResourceKind) => void;
  onToggleStatus: (status: string) => void;
  onSearchChange: (query: string) => void;
  onReLayout: () => void;
  onFitView: () => void;
  onCreateResource: (kind: ResourceKind) => void;
}

const KIND_CHIPS: { kind: ResourceKind; label: string; colorVar: string }[] = [
  { kind: 'ModelAPI', label: 'ModelAPI', colorVar: '--modelapi-color' },
  { kind: 'Agent', label: 'Agent', colorVar: '--agent-color' },
  { kind: 'MCPServer', label: 'MCPServer', colorVar: '--mcpserver-color' },
];

export function VisualMapToolbar({
  kindFilter,
  statusFilter,
  searchQuery,
  onToggleKind,
  onToggleStatus,
  onSearchChange,
  onReLayout,
  onFitView,
  onCreateResource,
}: VisualMapToolbarProps) {
  return (
    <div className="absolute top-3 left-3 right-3 z-10 flex items-center gap-2 flex-wrap">
      {/* Search */}
      <div className="relative">
        <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
        <Input
          placeholder="Search nodes..."
          value={searchQuery}
          onChange={(e) => onSearchChange(e.target.value)}
          className="h-8 w-48 pl-7 text-xs bg-card/90 backdrop-blur-sm border-border"
        />
      </div>

      {/* Create resource buttons */}
      <div className="flex items-center gap-1">
        {KIND_CHIPS.map((chip) => (
          <Tooltip key={chip.kind}>
            <TooltipTrigger asChild>
              <button
                onClick={() => onCreateResource(chip.kind)}
                className="flex items-center gap-1.5 text-[10px] font-medium px-2 py-1 rounded-full border border-border bg-card hover:bg-secondary text-foreground shadow-sm transition-all duration-150"
              >
                <span
                  className="w-2 h-2 rounded-full shrink-0"
                  style={{ backgroundColor: `hsl(var(${chip.colorVar}))` }}
                />
                <span>{chip.label}</span>
                <Plus className="h-3 w-3 text-muted-foreground" />
              </button>
            </TooltipTrigger>
            <TooltipContent side="bottom">Create {chip.label}</TooltipContent>
          </Tooltip>
        ))}
      </div>

      <div className="flex-1" />

      {/* Status filter with RAG colors */}
      <div className="flex items-center gap-1">
        {([
          { key: 'ready', color: 'hsl(var(--success))' },
          { key: 'pending', color: 'hsl(var(--warning))' },
          { key: 'failed', color: 'hsl(var(--destructive))' },
        ] as const).map(({ key, color }) => {
          const active = statusFilter.has(key);
          return (
            <button
              key={key}
              onClick={() => onToggleStatus(key)}
              className={`
                flex items-center gap-1 text-[10px] px-2 py-0.5 rounded-full capitalize transition-all duration-150
                ${active ? 'bg-secondary text-foreground' : 'text-muted-foreground/40 hover:text-muted-foreground'}
              `}
            >
              <span
                className="w-2 h-2 rounded-full shrink-0"
                style={{ backgroundColor: color, opacity: active ? 1 : 0.3 }}
              />
              {key}
            </button>
          );
        })}
      </div>

      {/* Kind filter toggles with colored dots */}
      <div className="flex items-center gap-1 bg-card/90 backdrop-blur-sm rounded-lg border border-border px-1 py-0.5">
        {KIND_CHIPS.map((chip) => {
          const active = kindFilter.has(chip.kind);
          return (
            <Tooltip key={chip.kind}>
              <TooltipTrigger asChild>
                <button
                  onClick={() => onToggleKind(chip.kind)}
                  className={`flex items-center gap-1 px-1.5 py-1 rounded text-[10px] font-medium transition-all duration-150
                    ${active ? 'text-foreground' : 'text-muted-foreground/30'}
                  `}
                >
                  <span
                    className="w-2.5 h-2.5 rounded-full shrink-0 transition-opacity"
                    style={{
                      backgroundColor: `hsl(var(${chip.colorVar}))`,
                      opacity: active ? 1 : 0.2,
                    }}
                  />
                </button>
              </TooltipTrigger>
              <TooltipContent side="bottom">{active ? `Hide ${chip.label}` : `Show ${chip.label}`}</TooltipContent>
            </Tooltip>
          );
        })}
      </div>

      {/* Layout controls */}
      <div className="flex items-center gap-1 bg-card/90 backdrop-blur-sm rounded-lg border border-border px-1 py-0.5">
        <Tooltip>
          <TooltipTrigger asChild>
            <Button variant="ghost" size="xs" onClick={onReLayout} className="h-7 w-7 p-0">
              <LayoutGrid className="h-3.5 w-3.5" />
            </Button>
          </TooltipTrigger>
          <TooltipContent side="bottom">Re-layout (resets positions)</TooltipContent>
        </Tooltip>

        <Tooltip>
          <TooltipTrigger asChild>
            <Button variant="ghost" size="xs" onClick={onFitView} className="h-7 w-7 p-0">
              <Maximize className="h-3.5 w-3.5" />
            </Button>
          </TooltipTrigger>
          <TooltipContent side="bottom">Fit to view</TooltipContent>
        </Tooltip>
      </div>
    </div>
  );
}
