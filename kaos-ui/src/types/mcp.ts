/**
 * MCP Tools Types
 * Types for interacting with MCP server using JSON-RPC protocol
 * Endpoint: POST /mcp with JSON-RPC body
 */

// Tool parameter schema (JSON Schema format)
export interface MCPToolParameter {
  type: string;
  description?: string;
  default?: unknown;
  enum?: string[];
  items?: MCPToolParameter;
  properties?: Record<string, MCPToolParameter>;
  required?: string[];
}

// Tool definition returned from tools/list JSON-RPC method
export interface MCPTool {
  name: string;
  description: string;
  // FastMCP uses inputSchema for the parameters
  inputSchema?: {
    type: 'object';
    properties: Record<string, MCPToolParameter>;
    required?: string[];
  };
  // Also support parameters for backwards compatibility
  parameters?: {
    type: 'object';
    properties: Record<string, MCPToolParameter>;
    required?: string[];
  };
}

// Result from tools/call JSON-RPC method
export interface MCPToolCallResult {
  result?: unknown;
  error?: string;
  content?: Array<{
    type: string;
    text?: string;
  }>;
  isError?: boolean;
}

// JSON-RPC request format
export interface MCPJsonRpcRequest {
  jsonrpc: '2.0';
  id: number | string;
  method: string;
  params?: Record<string, unknown>;
}

// JSON-RPC response format
export interface MCPJsonRpcResponse {
  jsonrpc: '2.0';
  id: number | string;
  result?: unknown;
  error?: {
    code: number;
    message: string;
    data?: unknown;
  };
}

// Tool call request params
export interface MCPToolCallRequest {
  name: string;
  arguments: Record<string, unknown>;
}
