/**
 * Real Kubernetes API Client
 * 
 * Connects to a Kubernetes cluster via kubectl proxy or kaos CLI
 * Provides full CRUD operations for CRDs and standard K8s resources
 */

import type {
  ModelAPI,
  MCPServer,
  Agent,
  Pod,
  Deployment,
  PersistentVolumeClaim,
  Service,
  ConfigMap,
  SecretRef,
} from '@/types/kubernetes';

import type { MCPTool, MCPToolCallResult } from '@/types/mcp';

export interface K8sClientConfig {
  baseUrl: string;
  namespace: string;
}

interface K8sListResponse<T> {
  apiVersion: string;
  kind: string;
  metadata: {
    resourceVersion: string;
    continue?: string;
  };
  items: T[];
}

interface K8sStatus {
  kind: 'Status';
  apiVersion: 'v1';
  metadata: Record<string, unknown>;
  status: 'Success' | 'Failure';
  message?: string;
  reason?: string;
  code: number;
}

class KubernetesClient {
  private config: K8sClientConfig = {
    baseUrl: '',
    namespace: 'default',
  };

  setConfig(config: Partial<K8sClientConfig>) {
    this.config = { ...this.config, ...config };
  }

  getConfig(): K8sClientConfig {
    return { ...this.config };
  }

  isConfigured(): boolean {
    return !!this.config.baseUrl;
  }

  private async request<T>(path: string, options: RequestInit = {}): Promise<T> {
    if (!this.config.baseUrl) {
      throw new Error('Kubernetes API not configured. Please set the base URL.');
    }

    const url = `${this.config.baseUrl}${path}`;
    
    const headers: HeadersInit = {};
    
    if (options.body) {
      headers['Content-Type'] = 'application/json';
    }
    
    // Headers to bypass tunnel warnings (for various proxy tools)
    headers['X-Requested-With'] = 'XMLHttpRequest';
    headers['bypass-tunnel-reminder'] = '1';
    
    const response = await fetch(url, {
      ...options,
      headers: {
        ...headers,
        ...options.headers,
      },
    });

    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(`K8s API error ${response.status}: ${errorText}`);
    }

    // Use arrayBuffer + TextDecoder to handle chunked/encoded responses (e.g. pods)
    // that cause "Decoding failed" errors with response.text() or response.json()
    const buffer = await response.arrayBuffer();
    const text = new TextDecoder('utf-8', { fatal: false }).decode(buffer);
    return JSON.parse(text);
  }

  private async simpleRequest<T>(path: string): Promise<T> {
    if (!this.config.baseUrl) {
      throw new Error('Kubernetes API not configured. Please set the base URL.');
    }

    const url = `${this.config.baseUrl}${path}`;
    const response = await fetch(url);

    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(`K8s API error ${response.status}: ${errorText}`);
    }

    return response.json();
  }

  async testConnection(): Promise<{ success: boolean; version?: string; error?: string; method?: string }> {
    try {
      const result = await this.simpleRequest<{ gitVersion: string }>('/version');
      return { success: true, version: result.gitVersion, method: 'simple' };
    } catch (simpleError) {
      console.log('Simple request failed, trying with headers:', simpleError);
    }

    try {
      const result = await this.request<{ gitVersion: string }>('/version');
      return { success: true, version: result.gitVersion, method: 'with-headers' };
    } catch (error) {
      return { success: false, error: error instanceof Error ? error.message : 'Unknown error' };
    }
  }

  // ============= CRD API Group Configuration =============
  private readonly agenticApiGroup = 'kaos.tools';
  private readonly agenticApiVersion = 'v1alpha1';

  private getCrdPath(resource: string, namespace?: string, name?: string): string {
    const ns = namespace || this.config.namespace;
    const basePath = `/apis/${this.agenticApiGroup}/${this.agenticApiVersion}/namespaces/${ns}/${resource}`;
    return name ? `${basePath}/${name}` : basePath;
  }

  // ============= ModelAPI CRUD =============
  async listModelAPIs(namespace?: string): Promise<ModelAPI[]> {
    const ns = namespace || this.config.namespace;
    const path = this.getCrdPath('modelapis', ns);
    console.log(`[k8sClient] Fetching ModelAPIs from: ${path}`);
    try {
      const response = await this.request<K8sListResponse<ModelAPI>>(path);
      console.log(`[k8sClient] Found ${response.items.length} ModelAPIs`);
      return response.items;
    } catch (error) {
      console.warn('[k8sClient] ModelAPI CRD not found:', error);
      return [];
    }
  }

  async getModelAPI(name: string, namespace?: string): Promise<ModelAPI> {
    return this.request<ModelAPI>(this.getCrdPath('modelapis', namespace, name));
  }

  async createModelAPI(api: ModelAPI): Promise<ModelAPI> {
    const ns = api.metadata.namespace || this.config.namespace;
    return this.request<ModelAPI>(this.getCrdPath('modelapis', ns), {
      method: 'POST',
      body: JSON.stringify(api),
    });
  }

  async updateModelAPI(api: ModelAPI): Promise<ModelAPI> {
    const ns = api.metadata.namespace || this.config.namespace;
    return this.request<ModelAPI>(this.getCrdPath('modelapis', ns, api.metadata.name), {
      method: 'PUT',
      body: JSON.stringify(api),
    });
  }

  async deleteModelAPI(name: string, namespace?: string): Promise<K8sStatus> {
    return this.request<K8sStatus>(this.getCrdPath('modelapis', namespace, name), {
      method: 'DELETE',
    });
  }

  // ============= MCPServer CRUD =============
  async listMCPServers(namespace?: string): Promise<MCPServer[]> {
    const ns = namespace || this.config.namespace;
    const path = this.getCrdPath('mcpservers', ns);
    console.log(`[k8sClient] Fetching MCPServers from: ${path}`);
    try {
      const response = await this.request<K8sListResponse<MCPServer>>(path);
      console.log(`[k8sClient] Found ${response.items.length} MCPServers`);
      return response.items;
    } catch (error) {
      console.warn('[k8sClient] MCPServer CRD not found:', error);
      return [];
    }
  }

  async getMCPServer(name: string, namespace?: string): Promise<MCPServer> {
    return this.request<MCPServer>(this.getCrdPath('mcpservers', namespace, name));
  }

  async createMCPServer(server: MCPServer): Promise<MCPServer> {
    const ns = server.metadata.namespace || this.config.namespace;
    return this.request<MCPServer>(this.getCrdPath('mcpservers', ns), {
      method: 'POST',
      body: JSON.stringify(server),
    });
  }

  async updateMCPServer(server: MCPServer): Promise<MCPServer> {
    const ns = server.metadata.namespace || this.config.namespace;
    return this.request<MCPServer>(this.getCrdPath('mcpservers', ns, server.metadata.name), {
      method: 'PUT',
      body: JSON.stringify(server),
    });
  }

  async deleteMCPServer(name: string, namespace?: string): Promise<K8sStatus> {
    return this.request<K8sStatus>(this.getCrdPath('mcpservers', namespace, name), {
      method: 'DELETE',
    });
  }

  // ============= Agent CRUD =============
  async listAgents(namespace?: string): Promise<Agent[]> {
    const ns = namespace || this.config.namespace;
    const path = this.getCrdPath('agents', ns);
    console.log(`[k8sClient] Fetching Agents from: ${path}`);
    try {
      const response = await this.request<K8sListResponse<Agent>>(path);
      console.log(`[k8sClient] Found ${response.items.length} Agents`);
      return response.items;
    } catch (error) {
      console.warn('[k8sClient] Agent CRD not found:', error);
      return [];
    }
  }

  async getAgent(name: string, namespace?: string): Promise<Agent> {
    return this.request<Agent>(this.getCrdPath('agents', namespace, name));
  }

  async createAgent(agent: Agent): Promise<Agent> {
    const ns = agent.metadata.namespace || this.config.namespace;
    return this.request<Agent>(this.getCrdPath('agents', ns), {
      method: 'POST',
      body: JSON.stringify(agent),
    });
  }

  async updateAgent(agent: Agent): Promise<Agent> {
    const ns = agent.metadata.namespace || this.config.namespace;
    return this.request<Agent>(this.getCrdPath('agents', ns, agent.metadata.name), {
      method: 'PUT',
      body: JSON.stringify(agent),
    });
  }

  async deleteAgent(name: string, namespace?: string): Promise<K8sStatus> {
    return this.request<K8sStatus>(this.getCrdPath('agents', namespace, name), {
      method: 'DELETE',
    });
  }

  // ============= Pod Operations =============
  async listPods(namespace?: string): Promise<Pod[]> {
    const ns = namespace || this.config.namespace;
    const response = await this.request<K8sListResponse<Pod>>(`/api/v1/namespaces/${ns}/pods`);
    return response.items;
  }

  async listAllPods(): Promise<Pod[]> {
    const response = await this.request<K8sListResponse<Pod>>('/api/v1/pods');
    return response.items;
  }

  async getPod(name: string, namespace?: string): Promise<Pod> {
    const ns = namespace || this.config.namespace;
    return this.request<Pod>(`/api/v1/namespaces/${ns}/pods/${name}`);
  }

  async deletePod(name: string, namespace?: string): Promise<K8sStatus> {
    const ns = namespace || this.config.namespace;
    return this.request<K8sStatus>(`/api/v1/namespaces/${ns}/pods/${name}`, {
      method: 'DELETE',
    });
  }

  async getPodLogs(
    name: string,
    namespace?: string,
    options?: { container?: string; tailLines?: number }
  ): Promise<string> {
    const ns = namespace || this.config.namespace;
    const params = new URLSearchParams();
    if (options?.container) params.set('container', options.container);
    if (options?.tailLines) params.set('tailLines', String(options.tailLines));
    
    const queryString = params.toString();
    const path = `/api/v1/namespaces/${ns}/pods/${name}/log${queryString ? '?' + queryString : ''}`;
    
    const response = await fetch(`${this.config.baseUrl}${path}`, {
      headers: { 
        'X-Requested-With': 'XMLHttpRequest',
        'bypass-tunnel-reminder': 'true',
      },
    });
    
    if (!response.ok) {
      throw new Error(`Failed to get logs: ${response.status}`);
    }
    
    return response.text();
  }

  // ============= Deployment Operations =============
  async listDeployments(namespace?: string): Promise<Deployment[]> {
    const ns = namespace || this.config.namespace;
    const response = await this.request<K8sListResponse<Deployment>>(`/apis/apps/v1/namespaces/${ns}/deployments`);
    return response.items;
  }

  async listAllDeployments(): Promise<Deployment[]> {
    const response = await this.request<K8sListResponse<Deployment>>('/apis/apps/v1/deployments');
    return response.items;
  }

  async getDeployment(name: string, namespace?: string): Promise<Deployment> {
    const ns = namespace || this.config.namespace;
    return this.request<Deployment>(`/apis/apps/v1/namespaces/${ns}/deployments/${name}`);
  }

  async createDeployment(deployment: Deployment): Promise<Deployment> {
    const ns = deployment.metadata.namespace || this.config.namespace;
    return this.request<Deployment>(`/apis/apps/v1/namespaces/${ns}/deployments`, {
      method: 'POST',
      body: JSON.stringify(deployment),
    });
  }

  async updateDeployment(deployment: Deployment): Promise<Deployment> {
    const ns = deployment.metadata.namespace || this.config.namespace;
    return this.request<Deployment>(`/apis/apps/v1/namespaces/${ns}/deployments/${deployment.metadata.name}`, {
      method: 'PUT',
      body: JSON.stringify(deployment),
    });
  }

  async deleteDeployment(name: string, namespace?: string): Promise<K8sStatus> {
    const ns = namespace || this.config.namespace;
    return this.request<K8sStatus>(`/apis/apps/v1/namespaces/${ns}/deployments/${name}`, {
      method: 'DELETE',
    });
  }

  async scaleDeployment(name: string, replicas: number, namespace?: string): Promise<Deployment> {
    const ns = namespace || this.config.namespace;
    const deployment = await this.getDeployment(name, ns);
    deployment.spec.replicas = replicas;
    return this.updateDeployment(deployment);
  }

  // ============= Service Operations =============
  async listServices(namespace?: string): Promise<Service[]> {
    const ns = namespace || this.config.namespace;
    const response = await this.request<K8sListResponse<Service>>(`/api/v1/namespaces/${ns}/services`);
    return response.items;
  }

  async listAllServices(): Promise<Service[]> {
    const response = await this.request<K8sListResponse<Service>>('/api/v1/services');
    return response.items;
  }

  async getService(name: string, namespace?: string): Promise<Service> {
    const ns = namespace || this.config.namespace;
    return this.request<Service>(`/api/v1/namespaces/${ns}/services/${name}`);
  }

  async createService(service: Service): Promise<Service> {
    const ns = service.metadata.namespace || this.config.namespace;
    return this.request<Service>(`/api/v1/namespaces/${ns}/services`, {
      method: 'POST',
      body: JSON.stringify(service),
    });
  }

  async updateService(service: Service): Promise<Service> {
    const ns = service.metadata.namespace || this.config.namespace;
    return this.request<Service>(`/api/v1/namespaces/${ns}/services/${service.metadata.name}`, {
      method: 'PUT',
      body: JSON.stringify(service),
    });
  }

  async deleteService(name: string, namespace?: string): Promise<K8sStatus> {
    const ns = namespace || this.config.namespace;
    return this.request<K8sStatus>(`/api/v1/namespaces/${ns}/services/${name}`, {
      method: 'DELETE',
    });
  }

  // ============= PVC Operations =============
  async listPVCs(namespace?: string): Promise<PersistentVolumeClaim[]> {
    const ns = namespace || this.config.namespace;
    const response = await this.request<K8sListResponse<PersistentVolumeClaim>>(`/api/v1/namespaces/${ns}/persistentvolumeclaims`);
    return response.items;
  }

  async getPVC(name: string, namespace?: string): Promise<PersistentVolumeClaim> {
    const ns = namespace || this.config.namespace;
    return this.request<PersistentVolumeClaim>(`/api/v1/namespaces/${ns}/persistentvolumeclaims/${name}`);
  }

  async createPVC(pvc: PersistentVolumeClaim): Promise<PersistentVolumeClaim> {
    const ns = pvc.metadata.namespace || this.config.namespace;
    return this.request<PersistentVolumeClaim>(`/api/v1/namespaces/${ns}/persistentvolumeclaims`, {
      method: 'POST',
      body: JSON.stringify(pvc),
    });
  }

  async deletePVC(name: string, namespace?: string): Promise<K8sStatus> {
    const ns = namespace || this.config.namespace;
    return this.request<K8sStatus>(`/api/v1/namespaces/${ns}/persistentvolumeclaims/${name}`, {
      method: 'DELETE',
    });
  }

  // ============= ConfigMaps & Secrets =============
  async listConfigMaps(namespace?: string): Promise<ConfigMap[]> {
    const ns = namespace || this.config.namespace;
    const response = await this.request<K8sListResponse<ConfigMap>>(`/api/v1/namespaces/${ns}/configmaps`);
    return response.items;
  }

  async listSecrets(namespace?: string): Promise<SecretRef[]> {
    const ns = namespace || this.config.namespace;
    const response = await this.request<K8sListResponse<SecretRef & { data?: Record<string, string> }>>(`/api/v1/namespaces/${ns}/secrets`);
    // Return only metadata and keys, not actual secret values
    return response.items.map(secret => ({
      apiVersion: secret.apiVersion,
      kind: secret.kind,
      metadata: secret.metadata,
      type: secret.type,
      // Include data keys for UI display without actual values
      dataKeys: secret.data ? Object.keys(secret.data) : [],
    })) as SecretRef[];
  }

  async createSecret(secret: { 
    apiVersion: string; 
    kind: string; 
    metadata: { name: string; namespace: string }; 
    type: string; 
    data?: Record<string, string>;
    stringData?: Record<string, string>;
  }): Promise<SecretRef> {
    const ns = secret.metadata.namespace || this.config.namespace;
    return this.request<SecretRef>(`/api/v1/namespaces/${ns}/secrets`, {
      method: 'POST',
      body: JSON.stringify(secret),
    });
  }

  async deleteSecret(name: string, namespace?: string): Promise<K8sStatus> {
    const ns = namespace || this.config.namespace;
    return this.request<K8sStatus>(`/api/v1/namespaces/${ns}/secrets/${name}`, {
      method: 'DELETE',
    });
  }

  // ============= Namespaces =============
  async listNamespaces(): Promise<{ metadata: { name: string } }[]> {
    const response = await this.request<K8sListResponse<{ metadata: { name: string } }>>('/api/v1/namespaces');
    return response.items;
  }

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
   * Parses the internal K8s endpoint and uses the service proxy
   * Uses GET /mcp/tools endpoint
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
   * Parses the internal K8s endpoint and uses the service proxy
   * Uses POST /mcp/tools endpoint with { name, args }
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
   * Per MCP Streamable HTTP spec: session ID is OPTIONAL
   * After initialization, we must send 'notifications/initialized' before other requests
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
    // Try multiple approaches since K8s proxy may strip or rename headers
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
   * This is required by the MCP protocol before any other requests
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
   * Tries stateless mode first (direct request), falls back to session-based if needed
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
   * Tries stateless mode first, falls back to session-based if needed
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

  async createNamespace(name: string): Promise<{ metadata: { name: string } }> {
    return this.request<{ metadata: { name: string } }>('/api/v1/namespaces', {
      method: 'POST',
      body: JSON.stringify({
        apiVersion: 'v1',
        kind: 'Namespace',
        metadata: { name },
      }),
    });
  }

  // ============= Service Proxy Operations =============
  
  /**
   * Proxy a request to a service within the cluster
   * Uses the Kubernetes API server's built-in proxy capability
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

// Singleton instance
export const k8sClient = new KubernetesClient();
