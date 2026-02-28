/**
 * Base Kubernetes HTTP client with configuration and request methods.
 */

export interface K8sClientConfig {
  baseUrl: string;
  namespace: string;
}

export interface K8sListResponse<T> {
  apiVersion: string;
  kind: string;
  metadata: {
    resourceVersion: string;
    continue?: string;
  };
  items: T[];
}

export interface K8sStatus {
  kind: 'Status';
  apiVersion: 'v1';
  metadata: Record<string, unknown>;
  status: 'Success' | 'Failure';
  message?: string;
  reason?: string;
  code: number;
}

export class KubernetesClientBase {
  protected config: K8sClientConfig = {
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

  protected async request<T>(path: string, options: RequestInit = {}): Promise<T> {
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

  protected async simpleRequest<T>(path: string): Promise<T> {
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
}
