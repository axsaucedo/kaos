/**
 * Core Kubernetes resource operations: pods, deployments, services, PVCs, configmaps, secrets, namespaces.
 */

import type {
  Pod,
  Deployment,
  PersistentVolumeClaim,
  Service,
  ConfigMap,
  SecretRef,
} from '@/types/kubernetes';

import { type K8sListResponse, type K8sStatus } from './client';
import { KubernetesClientWithResources } from './resources';

export class KubernetesClientWithCore extends KubernetesClientWithResources {
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
}
