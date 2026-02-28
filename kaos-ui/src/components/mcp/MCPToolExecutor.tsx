import {
  Play,
  Loader2,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import type { MCPTool } from '@/types/mcp';

interface MCPToolExecutorProps {
  selectedTool: MCPTool;
  toolArgs: Record<string, string>;
  onArgChange: (name: string, value: string) => void;
  isCalling: boolean;
  onCallTool: () => void;
  getToolSchema: (tool: MCPTool) => MCPTool['inputSchema'];
  getTypeBadgeVariant: (type: string) => string;
}

export function MCPToolExecutor({
  selectedTool,
  toolArgs,
  onArgChange,
  isCalling,
  onCallTool,
  getToolSchema,
  getTypeBadgeVariant,
}: MCPToolExecutorProps) {
  const schema = getToolSchema(selectedTool);

  return (
    <>
      {/* Parameters Form */}
      <div>
        <h4 className="text-sm font-medium mb-3">Parameters</h4>
        {schema?.properties && Object.entries(schema.properties).length > 0 ? (
          <div className="space-y-3">
            {Object.entries(schema.properties).map(([name, param]) => (
              <div key={name}>
                <Label htmlFor={name} className="text-sm flex items-center gap-2 mb-1.5">
                  <code className="font-mono">{name}</code>
                  <Badge variant={getTypeBadgeVariant(param.type) as "default" | "secondary" | "outline" | "destructive"} className="text-[10px]">
                    {param.type}
                  </Badge>
                  {schema.required?.includes(name) && (
                    <span className="text-destructive text-xs">*</span>
                  )}
                </Label>
                {param.description && (
                  <p className="text-xs text-muted-foreground mb-1.5">{param.description}</p>
                )}
                {param.type === 'integer' || param.type === 'number' ? (
                  <Input
                    id={name}
                    type="number"
                    value={toolArgs[name] || ''}
                    onChange={(e) => onArgChange(name, e.target.value)}
                    placeholder={param.default !== undefined ? String(param.default) : `Enter ${name}...`}
                    className="font-mono"
                  />
                ) : (
                  <Textarea
                    id={name}
                    value={toolArgs[name] || ''}
                    onChange={(e) => onArgChange(name, e.target.value)}
                    placeholder={param.default !== undefined ? String(param.default) : `Enter ${name}...`}
                    className="font-mono text-sm"
                    rows={3}
                  />
                )}
              </div>
            ))}
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">This tool has no parameters</p>
        )}
      </div>

      <Button
        onClick={onCallTool}
        disabled={isCalling}
        className="w-full bg-mcpserver hover:bg-mcpserver/90"
      >
        {isCalling ? (
          <>
            <Loader2 className="h-4 w-4 mr-2 animate-spin" />
            Calling...
          </>
        ) : (
          <>
            <Play className="h-4 w-4 mr-2" />
            Call Tool
          </>
        )}
      </Button>
    </>
  );
}
