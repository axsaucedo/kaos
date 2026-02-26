import { useState, useEffect, useCallback, useRef } from 'react';
import { 
  Wrench, 
  Play, 
  RefreshCw, 
  AlertCircle, 
  CheckCircle2,
  Copy,
  Check,
  Loader2,
  ChevronDown,
  ChevronUp
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { JsonSyntaxHighlight } from '@/components/mcp/JsonSyntaxHighlight';
import { k8sClient } from '@/lib/kubernetes-client';
import type { MCPServer } from '@/types/kubernetes';
import type { MCPTool, MCPToolCallResult } from '@/types/mcp';

interface MCPToolsDebugProps {
  mcpServer: MCPServer;
}

interface ToolCallHistory {
  id: string;
  toolName: string;
  args: Record<string, unknown>;
  result: MCPToolCallResult | null;
  error: string | null;
  timestamp: Date;
  duration: number;
}

// Simple MCP session state
interface MCPSession {
  sessionId: string | null;
  initialized: boolean;
}

/**
 * Parse SSE response to extract JSON data
 */
function parseSSEResponse(text: string): unknown {
  const lines = text.split('\n');
  for (const line of lines) {
    if (line.startsWith('data: ')) {
      const data = line.slice(6).trim();
      if (data && data !== '[DONE]') {
        return JSON.parse(data);
      }
    } else if (line.startsWith('data:')) {
      const data = line.slice(5).trim();
      if (data && data !== '[DONE]') {
        return JSON.parse(data);
      }
    }
  }
  // Fallback: try parsing the entire text as plain JSON
  // (servers may return plain JSON with SSE Content-Type on errors)
  return JSON.parse(text.trim());
}

/**
 * Extract session ID from response headers, trying multiple approaches
 * since K8s proxy may strip or rename custom headers.
 */
function extractSessionId(response: Response): string | null {
  // Try standard header name (case-insensitive per fetch spec)
  const direct = response.headers.get('mcp-session-id');
  if (direct) return direct;

  // Iterate all headers looking for session-related ones
  // (K8s proxy may lowercase or transform header names)
  let found: string | null = null;
  response.headers.forEach((value, key) => {
    const lower = key.toLowerCase();
    if (lower === 'mcp-session-id' || lower === 'x-mcp-session-id' || lower === 'session-id') {
      found = value;
    }
  });
  return found;
}

/**
 * Simple MCP HTTP request helper
 */
async function mcpRequest<T>(
  baseUrl: string,
  method: string,
  params: Record<string, unknown> = {},
  session: MCPSession | null = null,
  isNotification: boolean = false
): Promise<{ data: T; sessionId: string | null }> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    'Accept': 'application/json, text/event-stream',
    'X-Requested-With': 'XMLHttpRequest',
    'bypass-tunnel-reminder': '1',
  };

  if (session?.sessionId) {
    headers['Mcp-Session-Id'] = session.sessionId;
  }

  const body: Record<string, unknown> = {
    jsonrpc: '2.0',
    method,
    params,
  };

  if (!isNotification) {
    body.id = Date.now();
  }

  const response = await fetch(baseUrl, {
    method: 'POST',
    headers,
    body: JSON.stringify(body),
  });

  const sessionId = extractSessionId(response);

  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`HTTP ${response.status}: ${errorText}`);
  }

  if (response.status === 202 || isNotification) {
    return { data: {} as T, sessionId };
  }

  const responseText = await response.text();
  const contentType = response.headers.get('content-type') || '';
  
  let data: T;
  if (contentType.includes('text/event-stream') || responseText.includes('data:')) {
    const parsed = parseSSEResponse(responseText) as { result?: T; error?: { code: number; message: string } };
    if (parsed && typeof parsed === 'object' && 'error' in parsed && parsed.error) {
      throw new Error(`MCP error ${parsed.error.code}: ${parsed.error.message}`);
    }
    data = (parsed as { result: T }).result || parsed as T;
  } else {
    const parsed = JSON.parse(responseText) as { result?: T; error?: { code: number; message: string } };
    if (parsed.error) {
      throw new Error(`MCP error ${parsed.error.code}: ${parsed.error.message}`);
    }
    data = parsed.result || parsed as T;
  }

  return { data, sessionId };
}

export function MCPToolsDebug({ mcpServer }: MCPToolsDebugProps) {
  const [tools, setTools] = useState<MCPTool[]>([]);
  const [isLoadingTools, setIsLoadingTools] = useState(false);
  const [toolsError, setToolsError] = useState<string | null>(null);
  const [selectedTool, setSelectedTool] = useState<MCPTool | null>(null);
  const [toolArgs, setToolArgs] = useState<Record<string, string>>({});
  const [isCallingTool, setIsCallingTool] = useState(false);
  const [toolResults, setToolResults] = useState<Record<string, ToolCallHistory>>({});
  const [copiedResult, setCopiedResult] = useState(false);
  const [descExpanded, setDescExpanded] = useState(false);

  // Session state
  const sessionRef = useRef<MCPSession | null>(null);
  
  // Build MCP URL from K8s proxy
  const getMCPUrl = useCallback(() => {
    const k8sBaseUrl = k8sClient.getConfig().baseUrl;
    if (!k8sBaseUrl) throw new Error('Kubernetes API not configured');
    
    const endpoint = mcpServer.status?.endpoint;
    const namespace = mcpServer.metadata.namespace || 'default';
    
    if (endpoint) {
      // Parse endpoint like http://service.namespace.svc.cluster.local:8000
      const url = new URL(endpoint);
      const parts = url.hostname.split('.');
      const serviceName = parts[0];
      const ns = parts[1] || namespace;
      const port = url.port || '8000';
      return `${k8sBaseUrl}/api/v1/namespaces/${ns}/services/${serviceName}:${port}/proxy/mcp`;
    }
    
    const serviceName = `mcpserver-${mcpServer.metadata.name}`;
    return `${k8sBaseUrl}/api/v1/namespaces/${namespace}/services/${serviceName}:8000/proxy/mcp`;
  }, [mcpServer]);

  // Initialize session and fetch tools
  const fetchTools = useCallback(async () => {
    setIsLoadingTools(true);
    setToolsError(null);
    
    try {
      // Use k8sClient's listMCPToolsFromEndpoint which has stateless fallback
      const endpoint = mcpServer.status?.endpoint;
      if (endpoint) {
        const result = await k8sClient.listMCPToolsFromEndpoint(endpoint);
        setTools(result.tools || []);
        // Store session as null — k8sClient manages its own session internally
        sessionRef.current = { sessionId: null, initialized: true };
        return;
      }

      // Fallback: manual MCP protocol
      const mcpUrl = getMCPUrl();
      
      // Step 1: Initialize
      const initResult = await mcpRequest<{ protocolVersion: string }>(
        mcpUrl,
        'initialize',
        {
          protocolVersion: '2024-11-05',
          capabilities: {},
          clientInfo: { name: 'kaos-ui', version: '1.0.0' },
        }
      );
      
      sessionRef.current = {
        sessionId: initResult.sessionId,
        initialized: false,
      };

      if (!initResult.sessionId) {
        console.warn('[MCPToolsDebug] No session ID returned from initialize — K8s proxy may strip Mcp-Session-Id header.');
      }
      
      // Step 2: Send initialized notification (catch errors from missing session)
      try {
        await mcpRequest(
          mcpUrl,
          'notifications/initialized',
          {},
          sessionRef.current,
          true
        );
        sessionRef.current.initialized = true;
      } catch (notifError) {
        console.warn('[MCPToolsDebug] Notification failed:', notifError);
      }
      
      // Step 3: List tools
      const { data } = await mcpRequest<{ tools: MCPTool[] }>(
        mcpUrl,
        'tools/list',
        {},
        sessionRef.current
      );
      
      setTools(data.tools || []);
    } catch (error) {
      console.error('[MCPToolsDebug] Error:', error);
      setToolsError(error instanceof Error ? error.message : 'Failed to fetch tools');
      setTools([]);
      sessionRef.current = null;
    } finally {
      setIsLoadingTools(false);
    }
  }, [getMCPUrl, mcpServer]);

  // Fetch tools on mount
  useEffect(() => {
    fetchTools();
  }, [fetchTools]);

  // Helper to get tool schema
  const getToolSchema = (tool: MCPTool) => tool.inputSchema || tool.parameters;

  // Handle tool selection
  const handleSelectTool = (tool: MCPTool) => {
    setSelectedTool(tool);
    setDescExpanded(false);
    const initialArgs: Record<string, string> = {};
    const schema = getToolSchema(tool);
    if (schema?.properties) {
      Object.keys(schema.properties).forEach(key => {
        const prop = schema.properties[key];
        initialArgs[key] = prop.default !== undefined ? String(prop.default) : '';
      });
    }
    setToolArgs(initialArgs);
  };

  // Call the selected tool
  const handleCallTool = async () => {
    if (!selectedTool) return;

    setIsCallingTool(true);
    const startTime = Date.now();

    // Parse arguments based on parameter types
    const parsedArgs: Record<string, unknown> = {};
    const schema = getToolSchema(selectedTool);
    if (schema?.properties) {
      Object.entries(toolArgs).forEach(([key, value]) => {
        const paramDef = schema.properties[key];
        if (!paramDef) {
          parsedArgs[key] = value;
          return;
        }
        
        switch (paramDef.type) {
          case 'integer':
          case 'number':
            parsedArgs[key] = Number(value);
            break;
          case 'boolean':
            parsedArgs[key] = value.toLowerCase() === 'true';
            break;
          case 'object':
          case 'array':
            try {
              parsedArgs[key] = JSON.parse(value);
            } catch {
              parsedArgs[key] = value;
            }
            break;
          default:
            parsedArgs[key] = value;
        }
      });
    }

    const historyEntry: ToolCallHistory = {
      id: `call-${Date.now()}`,
      toolName: selectedTool.name,
      args: parsedArgs,
      result: null,
      error: null,
      timestamp: new Date(),
      duration: 0,
    };

    try {
      // Use k8sClient's callMCPToolFromEndpoint which handles session management
      const endpoint = mcpServer.status?.endpoint;
      if (endpoint) {
        const result = await k8sClient.callMCPToolFromEndpoint(endpoint, selectedTool.name, parsedArgs);
        historyEntry.result = result;
      } else {
        // Fallback to inline MCP request
        const mcpUrl = getMCPUrl();
        const { data } = await mcpRequest<MCPToolCallResult>(
          mcpUrl,
          'tools/call',
          { name: selectedTool.name, arguments: parsedArgs },
          sessionRef.current
        );
        historyEntry.result = data;
      }
      historyEntry.duration = Date.now() - startTime;
    } catch (error) {
      historyEntry.error = error instanceof Error ? error.message : 'Unknown error';
      historyEntry.duration = Date.now() - startTime;
    } finally {
      setIsCallingTool(false);
      setToolResults(prev => ({ ...prev, [selectedTool.name]: historyEntry }));
    }
  };


  // Copy result to clipboard
  const handleCopyResult = async (content: string) => {
    await navigator.clipboard.writeText(content);
    setCopiedResult(true);
    setTimeout(() => setCopiedResult(false), 2000);
  };

  // Get parameter type badge color
  const getTypeBadgeVariant = (type: string) => {
    switch (type) {
      case 'string': return 'default';
      case 'integer':
      case 'number': return 'secondary';
      case 'boolean': return 'outline';
      case 'object':
      case 'array': return 'destructive';
      default: return 'default';
    }
  };

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

      {/* Error Alert */}
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
        {/* Tools List Panel */}
        <div className="w-1/3 border-r border-border flex flex-col">
          <div className="px-3 py-2 border-b border-border bg-muted/20">
            <span className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
              Available Tools
            </span>
          </div>
          <ScrollArea className="flex-1">
            {isLoadingTools ? (
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
                        selectedTool?.name === tool.name
                          ? 'border-mcpserver bg-mcpserver/10'
                          : 'border-border hover:border-muted-foreground/50'
                      }`}
                      onClick={() => handleSelectTool(tool)}
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
                              <Badge variant={getTypeBadgeVariant(param.type)} className="text-[10px]">
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

        {/* Tool Call Panel */}
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
                  {/* Parameters Form */}
                  <div>
                    <h4 className="text-sm font-medium mb-3">Parameters</h4>
                    {(() => {
                      const schema = getToolSchema(selectedTool);
                      return schema?.properties && Object.entries(schema.properties).length > 0 ? (
                        <div className="space-y-3">
                          {Object.entries(schema.properties).map(([name, param]) => (
                            <div key={name}>
                              <Label htmlFor={name} className="text-sm flex items-center gap-2 mb-1.5">
                                <code className="font-mono">{name}</code>
                                <Badge variant={getTypeBadgeVariant(param.type)} className="text-[10px]">
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
                                  onChange={(e) => setToolArgs(prev => ({ ...prev, [name]: e.target.value }))}
                                  placeholder={param.default !== undefined ? String(param.default) : `Enter ${name}...`}
                                  className="font-mono"
                                />
                              ) : (
                                <Textarea
                                  id={name}
                                  value={toolArgs[name] || ''}
                                  onChange={(e) => setToolArgs(prev => ({ ...prev, [name]: e.target.value }))}
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
                      );
                    })()}
                  </div>

                  <Button
                    onClick={handleCallTool}
                    disabled={isCallingTool}
                    className="w-full bg-mcpserver hover:bg-mcpserver/90"
                  >
                    {isCallingTool ? (
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

                  {/* Result */}
                  {(() => {
                    const result = selectedTool ? toolResults[selectedTool.name] : null;
                    if (!result) return null;
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
                            onClick={() => handleCopyResult(resultStr)}
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
                  })()}
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
