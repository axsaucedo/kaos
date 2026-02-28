import { Loader2 } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { ScrollArea } from '@/components/ui/scroll-area';
import type { MCPTool } from '@/types/mcp';

interface MCPToolsListProps {
  tools: MCPTool[];
  isLoading: boolean;
  selectedToolName: string | null;
  onSelectTool: (tool: MCPTool) => void;
  getToolSchema: (tool: MCPTool) => MCPTool['inputSchema'];
  getTypeBadgeVariant: (type: string) => string;
}

export function MCPToolsList({
  tools,
  isLoading,
  selectedToolName,
  onSelectTool,
  getToolSchema,
  getTypeBadgeVariant,
}: MCPToolsListProps) {
  return (
    <div className="w-1/3 border-r border-border flex flex-col">
      <div className="px-3 py-2 border-b border-border bg-muted/20">
        <span className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
          Available Tools
        </span>
      </div>
      <ScrollArea className="flex-1">
        {isLoading ? (
          <div className="flex items-center justify-center py-8">
            <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
          </div>
        ) : tools.length === 0 ? (
          <div className="text-center py-8 px-4">
            <p className="text-sm text-muted-foreground">No tools available</p>
          </div>
        ) : (
          <div className="p-2 space-y-1">
            {tools.map((tool) => {
              const schema = getToolSchema(tool);
              const paramEntries = schema?.properties ? Object.entries(schema.properties) : [];
              return (
                <button
                  key={tool.name}
                  className={`w-full text-left rounded-lg border transition-colors p-2 ${
                    selectedToolName === tool.name
                      ? 'border-mcpserver bg-mcpserver/10'
                      : 'border-border hover:border-muted-foreground/50'
                  }`}
                  onClick={() => onSelectTool(tool)}
                >
                  <div className="font-mono text-sm font-medium truncate">
                    {tool.name}
                  </div>
                  <p className="text-xs text-muted-foreground line-clamp-2 mt-0.5">
                    {tool.description}
                  </p>
                  {paramEntries.length > 0 && (
                    <div className="flex flex-wrap gap-1 mt-1.5">
                      {paramEntries.map(([name, param]) => (
                        <div key={name} className="flex items-center gap-1 text-xs">
                          <code className="bg-muted px-1 py-0.5 rounded font-mono text-[10px]">
                            {name}
                          </code>
                          <Badge variant={getTypeBadgeVariant(param.type) as "default" | "secondary" | "outline" | "destructive"} className="text-[10px]">
                            {param.type}
                          </Badge>
                        </div>
                      ))}
                    </div>
                  )}
                  {paramEntries.length === 0 && (
                    <p className="text-[10px] text-muted-foreground mt-1">No parameters</p>
                  )}
                </button>
              );
            })}
          </div>
        )}
      </ScrollArea>
    </div>
  );
}
