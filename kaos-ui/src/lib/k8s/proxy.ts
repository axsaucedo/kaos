/**
 * Service proxy methods, SSE streaming, and MCP session/tool operations.
 */

import type { MCPTool, MCPToolCallResult } from '@/types/mcp';

import { KubernetesClientWithCore } from './core';

export class KubernetesClientWithProxy extends KubernetesClientWithCore {
  // ============= MCP Server Tools Operations =============
  
  /**
   * Parse a Kubernetes internal endpoint URL to extract service details
   * Endpoint format: http://servicename.namespace.svc.cluster.local:port
   */
  private parseK8sEndpoint(endpoint: string): { serviceName: string; namespace: string; port: number } | null {
    try {
      const url = new URL(endpoint);
      const host = url.hostname;
      const port = parseInt(url.port) || 8000;
      
      // Parse host format: servicename.namespace.svc.cluster.local
      const parts = host.split('.');
      if (parts.length >= 2) {
        return {
          serviceName: parts[0],
          namespace: parts[1],
          port,
        };
      }
      return null;
    } catch {
      return null;
    }
  }

  /**
   * List available tools from an MCP server using endpoint from status
   */
  async listMCPToolsFromEndpoint(
    endpoint: string
  ): Promise<{ tools: MCPTool[] }> {
    const parsed = this.parseK8sEndpoint(endpoint);
    if (!parsed) {
      throw new Error(`Invalid MCP endpoint format: ${endpoint}`);
    }
    
    console.log(`[k8sClient] Fetching MCP tools via proxy for service: ${parsed.serviceName} in ${parsed.namespace}`);
    return this.listMCPTools(parsed.serviceName, parsed.namespace, parsed.port);
  }

  /**
   * Call a tool on an MCP server using endpoint from status
   */
  async callMCPToolFromEndpoint(
    endpoint: string,
    toolName: string,
    args: Record<string, unknown>
  ): Promise<MCPToolCallResult> {
    const parsed = this.parseK8sEndpoint(endpoint);
    if (!parsed) {
      throw new Error(`Invalid MCP endpoint format: ${endpoint}`);
    }
    
    console.log(`[k8sClient] Calling MCP tool via proxy for service: ${parsed.serviceName} in ${parsed.namespace}`);
    return this.callMCPTool(parsed.serviceName, toolName, args, parsed.namespace, parsed.port);
  }
  
  /**
   * Parse SSE response to extract JSON-RPC messages
   */
  private async parseSSEResponse(response: Response): Promise<unknown> {
    const text = await response.text();
    console.log(`[k8sClient] Raw SSE response:`, text);
    
    // Parse SSE format: "event: message\ndata: {...}\n\n"
    const lines = text.split('\n');
    let jsonData = null;
    
    for (const line of lines) {
      const trimmed = line.trim();
      if (trimmed.startsWith('data:')) {
        const data = trimmed.slice(5).trim();
        if (data && data !== '[DONE]') {
          try {
            jsonData = JSON.parse(data);
          } catch {
            // Continue to next line
          }
        }
      }
    }
    
    // If no SSE data: lines found, try parsing the entire text as plain JSON
    // (some servers return plain JSON with text/event-stream Content-Type on errors)
    if (jsonData === null) {
      try {
        jsonData = JSON.parse(text.trim());
      } catch {
        // Not valid JSON either
      }
    }
    
    return jsonData;
  }

  /**
   * Parse response based on Content-Type (JSON or SSE)
   */
  private async parseMCPResponse(response: Response): Promise<unknown> {
    const contentType = response.headers.get('Content-Type') || '';
    console.log(`[k8sClient] Response Content-Type:`, contentType);
    
    if (contentType.includes('text/event-stream')) {
      return this.parseSSEResponse(response);
    } else {
      return response.json();
    }
  }

  /**
   * Initialize an MCP session and get the session ID (optional per spec)
   */
  async initializeMCPSession(
    serviceName: string,
    namespace?: string,
    port: number = 8000
  ): Promise<string | null> {
    const initRequest = {
      jsonrpc: '2.0',
      id: Date.now(),
      method: 'initialize',
      params: {
        protocolVersion: '2024-11-05',
        clientInfo: {
          name: 'kaos-ui',
          version: '1.0.0',
        },
        capabilities: {},
      },
    };
    
    console.log(`[k8sClient] Initializing MCP session for ${serviceName}:`, initRequest);
    
    const response = await this.proxyServiceRequest(
      serviceName,
      '/mcp',
      {
        method: 'POST',
        body: JSON.stringify(initRequest),
      },
      namespace,
      port
    );
    
    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(`MCP session initialization error ${response.status}: ${errorText}`);
    }
    
    // Get session ID from response header (optional per MCP spec)
    let sessionId = response.headers.get('Mcp-Session-Id') || response.headers.get('mcp-session-id');
    
    if (!sessionId) {
      // Iterate all headers to find session-related ones
      response.headers.forEach((value, key) => {
        const lower = key.toLowerCase();
        if (lower === 'mcp-session-id' || lower === 'x-mcp-session-id' || lower === 'session-id') {
          sessionId = value;
        }
      });
    }

    // Log all response headers for debugging
    const allHeaders: Record<string, string> = {};
    response.headers.forEach((value, key) => { allHeaders[key] = value; });
    console.log(`[k8sClient] MCP initialize response headers:`, allHeaders);
    
    // Consume the response body
    const body = await this.parseMCPResponse(response);
    console.log(`[k8sClient] MCP initialize response body:`, body);
    
    if (sessionId) {
      console.log(`[k8sClient] MCP session initialized with ID:`, sessionId);
    } else {
      console.warn(`[k8sClient] MCP server did not return session ID — K8s proxy may strip Mcp-Session-Id header`);
    }
    
    // Send 'notifications/initialized' as required by the protocol
    await this.sendMCPInitializedNotification(serviceName, namespace, port, sessionId);
    
    // Return session ID if provided, null for stateless servers
    return sessionId;
  }

  /**
   * Send the 'notifications/initialized' notification after initialization
   */
  private async sendMCPInitializedNotification(
    serviceName: string,
    namespace?: string,
    port: number = 8000,
    sessionId: string | null = null
  ): Promise<void> {
    const notification = {
      jsonrpc: '2.0',
      method: 'notifications/initialized',
    };
    
    console.log(`[k8sClient] Sending initialized notification to ${serviceName}`);
    
    const headers: Record<string, string> = {};
    if (sessionId) {
      headers['Mcp-Session-Id'] = sessionId;
    }
    
    const response = await this.proxyServiceRequest(
      serviceName,
      '/mcp',
      {
        method: 'POST',
        body: JSON.stringify(notification),
        headers,
      },
      namespace,
      port
    );
    
    // Per spec, server should return 202 Accepted for notifications
    if (!response.ok && response.status !== 202) {
      console.warn(`[k8sClient] Initialized notification returned status ${response.status}`);
    }
    
    // Consume response body if any
    try {
      await response.text();
    } catch {
      // Ignore
    }
    
    console.log(`[k8sClient] Initialized notification sent successfully`);
  }

  /**
   * List available tools from an MCP server via K8s service proxy
   */
  async listMCPTools(
    serviceName: string,
    namespace?: string,
    port: number = 8000
  ): Promise<{ tools: MCPTool[] }> {
    // First, try stateless mode (direct tools/list without initialization)
    console.log(`[k8sClient] Trying stateless tools/list for ${serviceName}`);
    
    const jsonRpcRequest = {
      jsonrpc: '2.0',
      id: Date.now(),
      method: 'tools/list',
      params: {},
    };
    
    try {
      const directResponse = await this.proxyServiceRequest(
        serviceName,
        '/mcp',
        {
          method: 'POST',
          body: JSON.stringify(jsonRpcRequest),
        },
        namespace,
        port
      );
      
      if (directResponse.ok) {
        const jsonRpcResponse = await this.parseMCPResponse(directResponse) as { error?: { message?: string; code?: number }; result?: { tools?: MCPTool[] } } | null;
        console.log(`[k8sClient] Stateless tools/list response:`, jsonRpcResponse);
        
        // Check if we got tools (stateless mode works)
        if (jsonRpcResponse?.result?.tools) {
          console.log(`[k8sClient] Stateless mode successful, found ${jsonRpcResponse.result.tools.length} tools`);
          return { tools: jsonRpcResponse.result.tools };
        }
        
        // Check for session-required error
        if (jsonRpcResponse?.error) {
          const errorMsg = jsonRpcResponse.error.message || '';
          if (errorMsg.includes('session') || errorMsg.includes('Session') || jsonRpcResponse.error.code === -32600) {
            console.log(`[k8sClient] Server requires session, falling back to session-based mode`);
            // Fall through to session-based mode
          } else {
            throw new Error(`MCP JSON-RPC error: ${errorMsg}`);
          }
        }
      }
    } catch (error) {
      console.log(`[k8sClient] Stateless mode failed, trying session-based:`, error);
      // Continue to session-based mode
    }
    
    // Session-based mode: Initialize → Notification → Request
    console.log(`[k8sClient] Initializing MCP session for tools/list to ${serviceName}`);
    const sessionId = await this.initializeMCPSession(serviceName, namespace, port);
    
    if (!sessionId) {
      console.warn('[k8sClient] No session ID available — K8s proxy may strip Mcp-Session-Id header. Trying without session.');
    }
    
    // Make the tools/list request with session
    console.log(`[k8sClient] Sending session-based JSON-RPC tools/list to ${serviceName}`);
    
    const headers: Record<string, string> = {};
    if (sessionId) {
      headers['Mcp-Session-Id'] = sessionId;
    }
    
    const response = await this.proxyServiceRequest(
      serviceName,
      '/mcp',
      {
        method: 'POST',
        body: JSON.stringify(jsonRpcRequest),
        headers,
      },
      namespace,
      port
    );
    
    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(`MCP tools list error ${response.status}: ${errorText}`);
    }
    
    const jsonRpcResponse = await this.parseMCPResponse(response) as { error?: { message?: string }; result?: { tools?: MCPTool[] } } | null;
    console.log(`[k8sClient] JSON-RPC tools/list response:`, jsonRpcResponse);
    
    if (!jsonRpcResponse) {
      throw new Error('MCP server returned empty response for tools/list');
    }
    
    // Handle JSON-RPC response format
    if (jsonRpcResponse.error) {
      throw new Error(`MCP JSON-RPC error: ${jsonRpcResponse.error.message || JSON.stringify(jsonRpcResponse.error)}`);
    }
    
    // The result contains the tools list - format: { tools: [...] }
    const result = jsonRpcResponse.result || jsonRpcResponse;
    return { tools: (result as { tools?: MCPTool[] }).tools || [] };
  }

  /**
   * Call a tool on an MCP server via K8s service proxy
   */
  async callMCPTool(
    serviceName: string,
    toolName: string,
    args: Record<string, unknown>,
    namespace?: string,
    port: number = 8000
  ): Promise<MCPToolCallResult> {
    // First, try stateless mode (direct tools/call without initialization)
    console.log(`[k8sClient] Trying stateless tools/call for ${serviceName}`);
    
    const jsonRpcRequest = {
      jsonrpc: '2.0',
      id: Date.now(),
      method: 'tools/call',
      params: {
        name: toolName,
        arguments: args,
      },
    };
    
    try {
      const directResponse = await this.proxyServiceRequest(
        serviceName,
        '/mcp',
        {
          method: 'POST',
          body: JSON.stringify(jsonRpcRequest),
        },
        namespace,
        port
      );
      
      if (directResponse.ok) {
        const jsonRpcResponse = await this.parseMCPResponse(directResponse) as { error?: { message?: string; code?: number }; result?: unknown } | null;
        console.log(`[k8sClient] Stateless tools/call response:`, jsonRpcResponse);
        
        // Check for session-required error
        if (jsonRpcResponse?.error) {
          const errorMsg = jsonRpcResponse.error.message || '';
          if (errorMsg.includes('session') || errorMsg.includes('Session') || jsonRpcResponse.error.code === -32600) {
            console.log(`[k8sClient] Server requires session, falling back to session-based mode`);
            // Fall through to session-based mode
          } else {
            throw new Error(`MCP JSON-RPC error: ${errorMsg}`);
          }
        } else if (jsonRpcResponse?.result !== undefined) {
          console.log(`[k8sClient] Stateless mode successful`);
          return jsonRpcResponse.result as MCPToolCallResult;
        }
      }
    } catch (error) {
      console.log(`[k8sClient] Stateless mode failed, trying session-based:`, error);
      // Continue to session-based mode
    }
    
    // Session-based mode: Initialize → Notification → Request
    console.log(`[k8sClient] Initializing MCP session for tools/call to ${serviceName}`);
    const sessionId = await this.initializeMCPSession(serviceName, namespace, port);
    
    if (!sessionId) {
      console.warn('[k8sClient] No session ID available — K8s proxy may strip Mcp-Session-Id header. Trying without session.');
    }
    
    // Make the tools/call request with session
    console.log(`[k8sClient] Sending session-based JSON-RPC tools/call to ${serviceName}`);
    
    const headers: Record<string, string> = {};
    if (sessionId) {
      headers['Mcp-Session-Id'] = sessionId;
    }
    
    const response = await this.proxyServiceRequest(
      serviceName,
      '/mcp',
      {
        method: 'POST',
        body: JSON.stringify(jsonRpcRequest),
        headers,
      },
      namespace,
      port
    );
    
    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(`MCP tool call error ${response.status}: ${errorText}`);
    }
    
    const jsonRpcResponse = await this.parseMCPResponse(response) as { error?: { message?: string }; result?: unknown } | null;
    console.log(`[k8sClient] JSON-RPC tools/call response:`, jsonRpcResponse);
    
    if (!jsonRpcResponse) {
      throw new Error('MCP server returned empty response for tools/call');
    }
    
    // Handle JSON-RPC response format
    if (jsonRpcResponse.error) {
      throw new Error(`MCP JSON-RPC error: ${jsonRpcResponse.error.message || JSON.stringify(jsonRpcResponse.error)}`);
    }
    
    // Return the result from the JSON-RPC response
    return (jsonRpcResponse.result || jsonRpcResponse) as MCPToolCallResult;
  }

  /**
   * Get MCP server health status
   */
  async getMCPHealth(
    serviceName: string,
    namespace?: string,
    port: number = 8000
  ): Promise<{ status: string }> {
    const response = await this.proxyServiceRequest(
      serviceName,
      '/health',
      { method: 'GET' },
      namespace,
      port
    );
    
    if (!response.ok) {
      throw new Error(`MCP health check failed: ${response.status}`);
    }
    
    return response.json();
  }

  /**
   * Get MCP server readiness with tool list
   */
  async getMCPReady(
    serviceName: string,
    namespace?: string,
    port: number = 8000
  ): Promise<{ ready: boolean; tools?: string[] }> {
    const response = await this.proxyServiceRequest(
      serviceName,
      '/ready',
      { method: 'GET' },
      namespace,
      port
    );
    
    if (!response.ok) {
      throw new Error(`MCP ready check failed: ${response.status}`);
    }
    
    return response.json();
  }

  // ============= Service Proxy Operations =============
  
  /**
   * Proxy a request to a service within the cluster
   */
  async proxyServiceRequest(
    serviceName: string,
    path: string,
    options: RequestInit = {},
    namespace?: string,
    port: number = 8000
  ): Promise<Response> {
    if (!this.config.baseUrl) {
      throw new Error('Kubernetes API not configured. Please set the base URL.');
    }

    const ns = namespace || this.config.namespace;
    // Ensure path starts with /
    const cleanPath = path.startsWith('/') ? path : `/${path}`;
    // Kubernetes service proxy URL format: /api/v1/namespaces/{ns}/services/{name}:{port}/proxy/{path}
    const url = `${this.config.baseUrl}/api/v1/namespaces/${ns}/services/${serviceName}:${port}/proxy${cleanPath}`;
    
    console.log(`[k8sClient] Proxying request to: ${url}`);
    
    return fetch(url, {
      ...options,
      headers: {
        'Content-Type': 'application/json',
        // FastMCP requires Accept header to include both application/json and text/event-stream
        'Accept': 'application/json, text/event-stream',
        'X-Requested-With': 'XMLHttpRequest',
        'bypass-tunnel-reminder': '1',
        ...options.headers,
      },
    });
  }
}
