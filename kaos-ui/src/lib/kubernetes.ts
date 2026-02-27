import { type ModelAPI, type MCPServer, type Agent, type ResourceStatus } from '@/types/kubernetes';

const API_BASE = '/api/v1';
const AGENTIC_API_BASE = '/apis/agentic.example.com/v1alpha1';

// Simulated API delay for realistic UX
const simulateDelay = (ms: number = 300) => new Promise(resolve => setTimeout(resolve, ms));

// Kubernetes API Client
export class KubernetesClient {
  private baseUrl: string;
  private token: string | null = null;

  constructor(baseUrl: string = '') {
    this.baseUrl = baseUrl;
  }

  setToken(token: string) {
    this.token = token;
  }

  private async request<T>(endpoint: string, options: RequestInit = {}): Promise<T> {
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      ...(options.headers as Record<string, string>),
    };

    if (this.token) {
      headers['Authorization'] = `Bearer ${this.token}`;
    }

    // For demo purposes, simulate API calls
    await simulateDelay();

    // In a real implementation, this would make actual API calls:
    // const response = await fetch(`${this.baseUrl}${endpoint}`, { ...options, headers });
    // if (!response.ok) throw new Error(`API Error: ${response.statusText}`);
    // return response.json();

    throw new Error('API not connected - using mock data');
  }

  // ModelAPI CRUD
  async listModelAPIs(namespace: string = 'agentic-system'): Promise<ModelAPI[]> {
    return this.request<ModelAPI[]>(`${AGENTIC_API_BASE}/namespaces/${namespace}/modelapis`);
  }

  async getModelAPI(name: string, namespace: string = 'agentic-system'): Promise<ModelAPI> {
    return this.request<ModelAPI>(`${AGENTIC_API_BASE}/namespaces/${namespace}/modelapis/${name}`);
  }

  async createModelAPI(api: ModelAPI): Promise<ModelAPI> {
    return this.request<ModelAPI>(`${AGENTIC_API_BASE}/namespaces/${api.metadata.namespace}/modelapis`, {
      method: 'POST',
      body: JSON.stringify(api),
    });
  }

  async updateModelAPI(api: ModelAPI): Promise<ModelAPI> {
    return this.request<ModelAPI>(
      `${AGENTIC_API_BASE}/namespaces/${api.metadata.namespace}/modelapis/${api.metadata.name}`,
      {
        method: 'PUT',
        body: JSON.stringify(api),
      }
    );
  }

  async deleteModelAPI(name: string, namespace: string = 'agentic-system'): Promise<void> {
    return this.request<void>(`${AGENTIC_API_BASE}/namespaces/${namespace}/modelapis/${name}`, {
      method: 'DELETE',
    });
  }

  // MCPServer CRUD
  async listMCPServers(namespace: string = 'agentic-system'): Promise<MCPServer[]> {
    return this.request<MCPServer[]>(`${AGENTIC_API_BASE}/namespaces/${namespace}/mcpservers`);
  }

  async getMCPServer(name: string, namespace: string = 'agentic-system'): Promise<MCPServer> {
    return this.request<MCPServer>(`${AGENTIC_API_BASE}/namespaces/${namespace}/mcpservers/${name}`);
  }

  async createMCPServer(server: MCPServer): Promise<MCPServer> {
    return this.request<MCPServer>(`${AGENTIC_API_BASE}/namespaces/${server.metadata.namespace}/mcpservers`, {
      method: 'POST',
      body: JSON.stringify(server),
    });
  }

  async updateMCPServer(server: MCPServer): Promise<MCPServer> {
    return this.request<MCPServer>(
      `${AGENTIC_API_BASE}/namespaces/${server.metadata.namespace}/mcpservers/${server.metadata.name}`,
      {
        method: 'PUT',
        body: JSON.stringify(server),
      }
    );
  }

  async deleteMCPServer(name: string, namespace: string = 'agentic-system'): Promise<void> {
    return this.request<void>(`${AGENTIC_API_BASE}/namespaces/${namespace}/mcpservers/${name}`, {
      method: 'DELETE',
    });
  }

  // Agent CRUD
  async listAgents(namespace: string = 'agentic-system'): Promise<Agent[]> {
    return this.request<Agent[]>(`${AGENTIC_API_BASE}/namespaces/${namespace}/agents`);
  }

  async getAgent(name: string, namespace: string = 'agentic-system'): Promise<Agent> {
    return this.request<Agent>(`${AGENTIC_API_BASE}/namespaces/${namespace}/agents/${name}`);
  }

  async createAgent(agent: Agent): Promise<Agent> {
    return this.request<Agent>(`${AGENTIC_API_BASE}/namespaces/${agent.metadata.namespace}/agents`, {
      method: 'POST',
      body: JSON.stringify(agent),
    });
  }

  async updateAgent(agent: Agent): Promise<Agent> {
    return this.request<Agent>(
      `${AGENTIC_API_BASE}/namespaces/${agent.metadata.namespace}/agents/${agent.metadata.name}`,
      {
        method: 'PUT',
        body: JSON.stringify(agent),
      }
    );
  }

  async deleteAgent(name: string, namespace: string = 'agentic-system'): Promise<void> {
    return this.request<void>(`${AGENTIC_API_BASE}/namespaces/${namespace}/agents/${name}`, {
      method: 'DELETE',
    });
  }

  // Standard K8s resources
  async listPods(namespace: string = 'agentic-system') {
    return this.request(`${API_BASE}/namespaces/${namespace}/pods`);
  }

  async getPodLogs(name: string, namespace: string = 'agentic-system', container?: string) {
    const containerParam = container ? `?container=${container}` : '';
    return this.request(`${API_BASE}/namespaces/${namespace}/pods/${name}/log${containerParam}`);
  }

  async listDeployments(namespace: string = 'agentic-system') {
    return this.request(`/apis/apps/v1/namespaces/${namespace}/deployments`);
  }

  async listPVCs(namespace: string = 'agentic-system') {
    return this.request(`${API_BASE}/namespaces/${namespace}/persistentvolumeclaims`);
  }

  // Watch resources (WebSocket)
  watchResources(resourceType: string, namespace: string = 'agentic-system', onMessage: (data: any) => void) {
    // In a real implementation, this would establish a WebSocket connection:
    // const ws = new WebSocket(`wss://${this.baseUrl}/apis/.../watch`);
    // ws.onmessage = (event) => onMessage(JSON.parse(event.data));
    // return () => ws.close();

    // For demo, simulate periodic updates
    const interval = setInterval(() => {
      onMessage({
        type: 'MODIFIED',
        object: { metadata: { name: 'demo' } },
      });
    }, 30000);

    return () => clearInterval(interval);
  }
}

export const kubernetesClient = new KubernetesClient();

// Helper to convert resource to YAML
export function resourceToYAML(resource: any): string {
  const lines: string[] = [];
  
  const addLine = (key: string, value: any, indent: number = 0) => {
    const prefix = '  '.repeat(indent);
    
    if (value === null || value === undefined) return;
    
    if (typeof value === 'object' && !Array.isArray(value)) {
      lines.push(`${prefix}${key}:`);
      Object.entries(value).forEach(([k, v]) => addLine(k, v, indent + 1));
    } else if (Array.isArray(value)) {
      lines.push(`${prefix}${key}:`);
      value.forEach((item) => {
        if (typeof item === 'object') {
          const entries = Object.entries(item);
          entries.forEach(([k, v], i) => {
            if (i === 0) {
              lines.push(`${prefix}  - ${k}: ${typeof v === 'object' ? '' : v}`);
              if (typeof v === 'object') {
                Object.entries(v as object).forEach(([k2, v2]) => addLine(k2, v2, indent + 3));
              }
            } else {
              addLine(k, v, indent + 2);
            }
          });
        } else {
          lines.push(`${prefix}  - ${item}`);
        }
      });
    } else if (typeof value === 'string' && value.includes('\n')) {
      lines.push(`${prefix}${key}: |`);
      value.split('\n').forEach((line) => {
        lines.push(`${prefix}  ${line}`);
      });
    } else {
      lines.push(`${prefix}${key}: ${JSON.stringify(value)}`);
    }
  };

  Object.entries(resource).forEach(([key, value]) => addLine(key, value));
  
  return lines.join('\n');
}

// Helper to parse YAML to resource
export function yamlToResource(yaml: string): any {
  // Simple YAML parser for demo purposes
  // In production, use a proper YAML library like js-yaml
  try {
    const lines = yaml.split('\n');
    const result: any = {};
    const stack: { obj: any; indent: number }[] = [{ obj: result, indent: -2 }];
    let currentArray: any[] | null = null;
    let currentArrayKey: string | null = null;

    for (const line of lines) {
      if (!line.trim() || line.trim().startsWith('#')) continue;

      const indent = line.search(/\S/);
      const content = line.trim();

      // Handle array items
      if (content.startsWith('- ')) {
        const value = content.slice(2);
        if (currentArray) {
          if (value.includes(':')) {
            const [k, v] = value.split(':').map(s => s.trim());
            currentArray.push({ [k]: v.replace(/^["']|["']$/g, '') });
          } else {
            currentArray.push(value.replace(/^["']|["']$/g, ''));
          }
        }
        continue;
      }

      // Handle key-value pairs
      const colonIndex = content.indexOf(':');
      if (colonIndex > 0) {
        const key = content.slice(0, colonIndex).trim();
        const value = content.slice(colonIndex + 1).trim();

        // Pop stack to correct level
        while (stack.length > 1 && stack[stack.length - 1].indent >= indent) {
          stack.pop();
        }

        const parent = stack[stack.length - 1].obj;

        if (value === '' || value === '|') {
          // Nested object or multiline string
          parent[key] = {};
          stack.push({ obj: parent[key], indent });
          currentArray = null;
        } else if (value === '[]') {
          parent[key] = [];
          currentArray = parent[key];
          currentArrayKey = key;
        } else {
          // Parse value
          let parsedValue: any = value.replace(/^["']|["']$/g, '');
          if (parsedValue === 'true') parsedValue = true;
          else if (parsedValue === 'false') parsedValue = false;
          else if (!isNaN(Number(parsedValue)) && parsedValue !== '') parsedValue = Number(parsedValue);
          
          parent[key] = parsedValue;
          currentArray = null;
        }
      }
    }

    return result;
  } catch (error) {
    console.error('YAML parsing error:', error);
    throw new Error('Invalid YAML format');
  }
}
