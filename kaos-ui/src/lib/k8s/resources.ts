/**
 * CRUD operations for KAOS CRDs: Agent, MCPServer, ModelAPI.
 */

import type {
  ModelAPI,
  MCPServer,
  Agent,
} from '@/types/kubernetes';

import { KubernetesClientBase, type K8sListResponse, type K8sStatus } from './client';

export class KubernetesClientWithResources extends KubernetesClientBase {
  // ============= CRD API Group Configuration =============
  private readonly agenticApiGroup = 'kaos.tools';
  private readonly agenticApiVersion = 'v1alpha1';

  protected getCrdPath(resource: string, namespace?: string, name?: string): string {
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
}
