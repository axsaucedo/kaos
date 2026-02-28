import {
  Wrench,
  RefreshCw,
  AlertCircle,
  ChevronDown,
  ChevronUp,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { MCPToolsList } from '@/components/mcp/MCPToolsList';
import { MCPToolExecutor } from '@/components/mcp/MCPToolExecutor';
import { MCPToolResult } from '@/components/mcp/MCPToolResult';
import { getToolSchema, getTypeBadgeVariant } from '@/components/mcp/mcpToolsUtils';
import { useMCPTools } from '@/components/mcp/useMCPTools';
import type { MCPServer } from '@/types/kubernetes';

interface MCPToolsDebugProps {
  mcpServer: MCPServer;
}

export function MCPToolsDebug({ mcpServer }: MCPToolsDebugProps) {
  const {
    tools,
    isLoadingTools,
    toolsError,
    selectedTool,
    toolArgs,
    isCallingTool,
    copiedResult,
    descExpanded,
    setDescExpanded,
    currentResult,
    fetchTools,
    handleSelectTool,
    handleCallTool,
    handleCopyResult,
    handleArgChange,
  } = useMCPTools(mcpServer);

  return (
    <div className="flex flex-col h-full bg-background rounded-lg border border-border overflow-hidden min-h-0">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-border bg-muted/30">
        <div className="flex items-center gap-2">
          <Wrench className="h-4 w-4 text-mcpserver" />
          <span className="text-sm font-medium">Tools</span>
          {tools.length > 0 && (
            <Badge variant="secondary" className="text-xs">
              {tools.length} tools
            </Badge>
          )}
        </div>
        <Button
          variant="ghost"
          size="sm"
          onClick={fetchTools}
          disabled={isLoadingTools}
        >
          <RefreshCw className={`h-4 w-4 mr-1 ${isLoadingTools ? 'animate-spin' : ''}`} />
          Refresh
        </Button>
      </div>

      {toolsError && (
        <Alert variant="destructive" className="m-4 mb-0">
          <AlertCircle className="h-4 w-4" />
          <AlertDescription>
            <div className="flex flex-col gap-1">
              <span className="font-medium">Failed to load tools</span>
              <span className="text-sm opacity-90">{toolsError}</span>
            </div>
          </AlertDescription>
        </Alert>
      )}

      <div className="flex flex-1 min-h-0">
        <MCPToolsList
          tools={tools}
          isLoading={isLoadingTools}
          selectedToolName={selectedTool?.name ?? null}
          onSelectTool={handleSelectTool}
          getToolSchema={getToolSchema}
          getTypeBadgeVariant={getTypeBadgeVariant}
        />

        <div className="flex-1 flex flex-col">
          {selectedTool ? (
            <>
              {/* Selected Tool Header with collapsible description */}
              <div className="px-4 py-3 border-b border-border bg-muted/20 shrink-0">
                <div className="flex items-center justify-between">
                  <Badge variant="outline" className="font-mono">
                    {selectedTool.name}
                  </Badge>
                  {selectedTool.description && selectedTool.description.length > 80 && (
                    <Button
                      variant="ghost"
                      size="sm"
                      className="h-6 px-2"
                      onClick={() => setDescExpanded(!descExpanded)}
                    >
                      {descExpanded ? (
                        <ChevronUp className="h-3 w-3" />
                      ) : (
                        <ChevronDown className="h-3 w-3" />
                      )}
                    </Button>
                  )}
                </div>
                {selectedTool.description && (
                  <p className={`text-xs text-muted-foreground mt-1 whitespace-pre-wrap ${
                    descExpanded ? '' : 'line-clamp-1'
                  }`}>
                    {selectedTool.description}
                  </p>
                )}
              </div>

              {/* Scrollable content area */}
              <ScrollArea className="flex-1 min-h-0">
                <div className="p-4 space-y-4">
                  <MCPToolExecutor
                    selectedTool={selectedTool}
                    toolArgs={toolArgs}
                    onArgChange={handleArgChange}
                    isCalling={isCallingTool}
                    onCallTool={handleCallTool}
                    getToolSchema={getToolSchema}
                    getTypeBadgeVariant={getTypeBadgeVariant}
                  />

                  {currentResult && (
                    <MCPToolResult
                      result={currentResult}
                      copiedResult={copiedResult}
                      onCopyResult={handleCopyResult}
                    />
                  )}
                </div>
              </ScrollArea>
            </>
          ) : (
            <div className="flex-1 flex items-center justify-center">
              <div className="text-center">
                <Wrench className="h-12 w-12 text-muted-foreground/20 mx-auto mb-3" />
                <p className="text-sm text-muted-foreground">Select a tool to get started</p>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
