import { useState, useEffect, useCallback, useRef } from 'react';
import { mcpRequest, getToolSchema } from '@/components/mcp/mcpToolsUtils';
import type { ToolCallHistory, MCPSession } from '@/components/mcp/mcpToolsUtils';
import { k8sClient } from '@/lib/kubernetes-client';
import type { MCPServer } from '@/types/kubernetes';
import type { MCPTool, MCPToolCallResult } from '@/types/mcp';

export function useMCPTools(mcpServer: MCPServer) {
  const [tools, setTools] = useState<MCPTool[]>([]);
  const [isLoadingTools, setIsLoadingTools] = useState(false);
  const [toolsError, setToolsError] = useState<string | null>(null);
  const [selectedTool, setSelectedTool] = useState<MCPTool | null>(null);
  const [toolArgs, setToolArgs] = useState<Record<string, string>>({});
  const [isCallingTool, setIsCallingTool] = useState(false);
  const [toolResults, setToolResults] = useState<Record<string, ToolCallHistory>>({});
  const [copiedResult, setCopiedResult] = useState(false);
  const [descExpanded, setDescExpanded] = useState(false);

  const sessionRef = useRef<MCPSession | null>(null);

  const getMCPUrl = useCallback(() => {
    const k8sBaseUrl = k8sClient.getConfig().baseUrl;
    if (!k8sBaseUrl) throw new Error('Kubernetes API not configured');

    const endpoint = mcpServer.status?.endpoint;
    const namespace = mcpServer.metadata.namespace || 'default';

    if (endpoint) {
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

  const fetchTools = useCallback(async () => {
    setIsLoadingTools(true);
    setToolsError(null);

    try {
      const endpoint = mcpServer.status?.endpoint;
      if (endpoint) {
        const result = await k8sClient.listMCPToolsFromEndpoint(endpoint);
        setTools(result.tools || []);
        sessionRef.current = { sessionId: null, initialized: true };
        return;
      }

      const mcpUrl = getMCPUrl();

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

  useEffect(() => {
    fetchTools();
  }, [fetchTools]);

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

  const handleCallTool = async () => {
    if (!selectedTool) return;

    setIsCallingTool(true);
    const startTime = Date.now();

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
      const endpoint = mcpServer.status?.endpoint;
      if (endpoint) {
        const result = await k8sClient.callMCPToolFromEndpoint(endpoint, selectedTool.name, parsedArgs);
        historyEntry.result = result;
      } else {
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

  const handleCopyResult = async (content: string) => {
    await navigator.clipboard.writeText(content);
    setCopiedResult(true);
    setTimeout(() => setCopiedResult(false), 2000);
  };

  const handleArgChange = (name: string, value: string) => {
    setToolArgs(prev => ({ ...prev, [name]: value }));
  };

  const currentResult = selectedTool ? toolResults[selectedTool.name] : null;

  return {
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
  };
}
