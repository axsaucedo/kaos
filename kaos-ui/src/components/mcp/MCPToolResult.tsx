import {
  AlertCircle,
  CheckCircle2,
  Copy,
  Check,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { JsonSyntaxHighlight } from '@/components/mcp/JsonSyntaxHighlight';
import type { ToolCallHistory } from '@/components/mcp/mcpToolsUtils';

interface MCPToolResultProps {
  result: ToolCallHistory;
  copiedResult: boolean;
  onCopyResult: (content: string) => void;
}

export function MCPToolResult({ result, copiedResult, onCopyResult }: MCPToolResultProps) {
  const resultStr = result.error || JSON.stringify(result.result, null, 2);
  const isJson = !result.error && result.result != null;

  return (
    <div className="rounded-lg border border-border p-3 bg-muted/20">
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          {result.error ? (
            <AlertCircle className="h-4 w-4 text-destructive" />
          ) : (
            <CheckCircle2 className="h-4 w-4 text-emerald-500" />
          )}
          <span className="text-xs text-muted-foreground">
            {result.error ? 'Error' : 'Success'} · {result.duration}ms
          </span>
        </div>
        <Button
          variant="ghost"
          size="icon"
          className="h-6 w-6"
          onClick={() => onCopyResult(resultStr)}
        >
          {copiedResult ? (
            <Check className="h-3 w-3" />
          ) : (
            <Copy className="h-3 w-3" />
          )}
        </Button>
      </div>
      <div className="bg-background rounded p-2 overflow-auto max-h-64">
        {isJson ? (
          <JsonSyntaxHighlight json={resultStr} />
        ) : (
          <pre className="text-xs font-mono whitespace-pre-wrap break-all text-destructive">
            {resultStr}
          </pre>
        )}
      </div>
    </div>
  );
}
