import type { MCPTool } from '@/types/mcp';

export interface ToolCallHistory {
  id: string;
  toolName: string;
  args: Record<string, unknown>;
  result: import('@/types/mcp').MCPToolCallResult | null;
  error: string | null;
  timestamp: Date;
  duration: number;
}

export interface MCPSession {
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
  return JSON.parse(text.trim());
}

/**
 * Extract session ID from response headers, trying multiple approaches
 * since K8s proxy may strip or rename custom headers.
 */
function extractSessionId(response: Response): string | null {
  const direct = response.headers.get('mcp-session-id');
  if (direct) return direct;

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
export async function mcpRequest<T>(
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

export const getToolSchema = (tool: MCPTool) => tool.inputSchema || tool.parameters;

export const getTypeBadgeVariant = (type: string) => {
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
