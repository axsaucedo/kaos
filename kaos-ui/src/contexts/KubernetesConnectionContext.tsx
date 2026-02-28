/**
 * Kubernetes Connection Context
 *
 * Provides connection state and API methods to all components.
 * CRUD operations are delegated to useResourceCrud hook.
 */

import React, { createContext, useContext, useEffect, useState, useCallback, useRef } from 'react';
import { k8sClient } from '@/lib/kubernetes-client';
import { useKubernetesStore } from '@/stores/kubernetesStore';
import { useResourceCrud } from '@/hooks/useResourceCrud';
import type { ModelAPI, MCPServer, Agent, LogEntry, K8sSecret } from '@/types/kubernetes';

interface ConnectionState {
  connected: boolean;
  connecting: boolean;
  error: string | null;
  lastRefresh: Date | null;
  namespace: string;
  baseUrl: string;
  namespaces: string[];
}

interface KubernetesConnectionContextType extends ConnectionState {
  connect: (baseUrl: string, namespace?: string) => Promise<boolean>;
  disconnect: () => void;
  refreshAll: () => Promise<void>;
  refreshNamespaces: () => Promise<void>;
  switchNamespace: (namespace: string) => Promise<void>;
  startPolling: (intervalOverride?: number) => void;
  stopPolling: () => void;
  createModelAPI: (api: ModelAPI) => Promise<ModelAPI>;
  updateModelAPI: (api: ModelAPI) => Promise<ModelAPI>;
  deleteModelAPI: (name: string, namespace?: string) => Promise<void>;
  createMCPServer: (server: MCPServer) => Promise<MCPServer>;
  updateMCPServer: (server: MCPServer) => Promise<MCPServer>;
  deleteMCPServer: (name: string, namespace?: string) => Promise<void>;
  createAgent: (agent: Agent) => Promise<Agent>;
  updateAgent: (agent: Agent) => Promise<Agent>;
  deleteAgent: (name: string, namespace?: string) => Promise<void>;
  createSecret: (secret: K8sSecret) => Promise<K8sSecret>;
  deleteSecret: (name: string, namespace?: string) => Promise<void>;
}

const KubernetesConnectionContext = createContext<KubernetesConnectionContextType | null>(null);

export function KubernetesConnectionProvider({ children }: { children: React.ReactNode }) {
  const [state, setState] = useState<ConnectionState>({
    connected: false,
    connecting: false,
    error: null,
    lastRefresh: null,
    namespace: 'default',
    baseUrl: '',
    namespaces: [],
  });

  const pollIntervalRef = useRef<NodeJS.Timeout | null>(null);
  const store = useKubernetesStore();

  const addLogEntry = useCallback(
    (level: LogEntry['level'], message: string, source: string, resourceName?: string, resourceKind?: string) => {
      store.addLog({ timestamp: new Date().toISOString(), level, message, source, resourceName, resourceKind });
    },
    [store]
  );

  // Switch to a fallback namespace when the current one is no longer available
  const switchToFallback = useCallback((namespaceNames: string[], reason: string) => {
    const fallback = namespaceNames.includes('default') ? 'default' : namespaceNames[0];
    store.clearAllResources();
    k8sClient.setConfig({ baseUrl: state.baseUrl, namespace: fallback });
    setState(s => ({ ...s, namespace: fallback, namespaces: namespaceNames, error: null, lastRefresh: new Date() }));
    addLogEntry('warn', reason, 'connection');
    return fallback;
  }, [store, state.baseUrl, addLogEntry]);

  // Fetch and sync all resources
  const refreshAll = useCallback(async () => {
    if (!k8sClient.isConfigured()) return;

    store.setIsRefreshing(true);

    try {
      const [modelAPIs, mcpServers, agents, pods, deployments, pvcs, services, secrets, namespacesList] = await Promise.all([
        k8sClient.listModelAPIs().catch(() => []),
        k8sClient.listMCPServers().catch(() => []),
        k8sClient.listAgents().catch(() => []),
        k8sClient.listPods().catch(() => []),
        k8sClient.listDeployments().catch(() => []),
        k8sClient.listPVCs().catch(() => []),
        k8sClient.listServices().catch(() => []),
        k8sClient.listSecrets().catch(() => []),
        k8sClient.listNamespaces().catch(() => []),
      ]);

      store.setModelAPIs(modelAPIs);
      store.setMCPServers(mcpServers);
      store.setAgents(agents);
      store.setPods(pods);
      store.setDeployments(deployments);
      store.setPVCs(pvcs);
      store.setServices(services);
      store.setSecrets(secrets as K8sSecret[]);

      const namespaceNames = namespacesList.map((ns: { metadata: { name: string } }) => ns.metadata.name);
      const currentNamespace = k8sClient.getConfig().namespace;
      const namespaceExists = namespaceNames.length === 0 || namespaceNames.includes(currentNamespace);

      if (!namespaceExists && namespaceNames.length > 0) {
        switchToFallback(namespaceNames, `Namespace "${currentNamespace}" was deleted, switched to fallback`);
        return;
      }

      setState(s => ({
        ...s,
        error: null,
        lastRefresh: new Date(),
        namespaces: namespaceNames.length > 0 ? namespaceNames : s.namespaces,
      }));
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to fetch resources';

      if (message.includes('404') || message.includes('not found') || message.includes('Namespace')) {
        try {
          const nsList = await k8sClient.listNamespaces();
          const namespaceNames = nsList.map(ns => ns.metadata.name);
          if (namespaceNames.length > 0) {
            switchToFallback(namespaceNames, 'Switched to fallback namespace after error');
            setTimeout(() => refreshAll(), 500);
            return;
          }
        } catch {
          // Failed to recover from namespace error
        }
      }

      setState(s => ({ ...s, error: message }));
      addLogEntry('error', message, 'connection');
    } finally {
      store.setIsRefreshing(false);
    }
  }, [store, addLogEntry, switchToFallback]);

  const startPolling = useCallback((intervalOverride?: number) => {
    if (pollIntervalRef.current) clearInterval(pollIntervalRef.current);

    const interval = intervalOverride ?? store.autoRefreshInterval;
    const enabled = intervalOverride !== undefined ? intervalOverride > 0 : store.autoRefreshEnabled;

    if (!enabled || interval <= 0) {
      store.setNextRefreshTime(null);
      return;
    }

    store.setNextRefreshTime(Date.now() + interval);
    pollIntervalRef.current = setInterval(() => {
      if (k8sClient.isConfigured()) {
        refreshAll();
        store.setNextRefreshTime(Date.now() + interval);
      }
    }, interval);
  }, [refreshAll, store]);

  const stopPolling = useCallback(() => {
    if (pollIntervalRef.current) {
      clearInterval(pollIntervalRef.current);
      pollIntervalRef.current = null;
    }
    store.setNextRefreshTime(null);
  }, [store]);

  const connect = useCallback(async (baseUrl: string, namespace: string = 'default'): Promise<boolean> => {
    setState(s => ({ ...s, connecting: true, error: null }));

    const cleanUrl = baseUrl.replace(/\/$/, '');
    k8sClient.setConfig({ baseUrl: cleanUrl, namespace });

    try {
      const result = await k8sClient.testConnection();

      if (result.success) {
        setState(s => ({
          ...s,
          connected: true,
          connecting: false,
          baseUrl: cleanUrl,
          namespace,
          error: null,
        }));

        addLogEntry('info', `Connected to Kubernetes ${result.version}`, 'connection');
        // refreshAll fetches namespaces along with all other resources
        await refreshAll();
        startPolling();
        return true;
      } else {
        setState(s => ({ ...s, connected: false, connecting: false, error: result.error || 'Connection failed' }));
        return false;
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Connection failed';
      setState(s => ({ ...s, connected: false, connecting: false, error: message }));
      return false;
    }
  }, [refreshAll, startPolling, addLogEntry]);

  const refreshNamespaces = useCallback(async () => {
    if (!k8sClient.isConfigured()) return;
    try {
      const nsList = await k8sClient.listNamespaces();
      setState(s => ({ ...s, namespaces: nsList.map(ns => ns.metadata.name) }));
    } catch {
      // Failed to fetch namespaces
    }
  }, []);

  const switchNamespace = useCallback(async (newNamespace: string) => {
    if (!state.connected || !state.baseUrl) return;

    store.clearAllResources();
    k8sClient.setConfig({ baseUrl: state.baseUrl, namespace: newNamespace });
    setState(s => ({ ...s, namespace: newNamespace }));
    localStorage.setItem('k8s-config', JSON.stringify({ baseUrl: state.baseUrl, namespace: newNamespace }));

    await refreshAll();
    addLogEntry('info', `Switched to namespace ${newNamespace}`, 'connection');
  }, [state.connected, state.baseUrl, refreshAll, addLogEntry, store]);

  const disconnect = useCallback(() => {
    stopPolling();
    k8sClient.setConfig({ baseUrl: '', namespace: 'default' });
    store.clearAllResources();
    setState({
      connected: false, connecting: false, error: null, lastRefresh: null,
      namespace: 'default', baseUrl: '', namespaces: [],
    });
    addLogEntry('info', 'Disconnected from cluster', 'connection');
  }, [stopPolling, store, addLogEntry]);

  // Auto-connect on mount if saved config exists or URL param is provided
  useEffect(() => {
    const urlParams = new URLSearchParams(window.location.search);
    const urlKubernetesUrl = urlParams.get('kubernetesUrl');
    const urlNamespace = urlParams.get('namespace');

    if (urlKubernetesUrl) {
      const ns = urlNamespace || 'default';
      localStorage.setItem('k8s-config', JSON.stringify({ baseUrl: urlKubernetesUrl, namespace: ns }));
      connect(urlKubernetesUrl, ns);
      return;
    }

    const savedConfig = localStorage.getItem('k8s-config');
    if (savedConfig) {
      try {
        const config = JSON.parse(savedConfig);
        const ns = urlNamespace || config.namespace || 'default';
        if (config.baseUrl) {
          connect(config.baseUrl, ns);
          return;
        }
      } catch {
        // Failed to parse saved config
      }
    }

    connect('http://localhost:8010', urlNamespace || 'default');
    return () => stopPolling();
  }, []);  // eslint-disable-line react-hooks/exhaustive-deps

  // CRUD operations delegated to k8s client via useResourceCrud
  const crud = useResourceCrud(addLogEntry, refreshAll);

  const value: KubernetesConnectionContextType = {
    ...state,
    connect,
    disconnect,
    refreshAll,
    refreshNamespaces,
    switchNamespace,
    startPolling,
    stopPolling,
    ...crud,
  };

  return (
    <KubernetesConnectionContext.Provider value={value}>
      {children}
    </KubernetesConnectionContext.Provider>
  );
}

const defaultContextValue: KubernetesConnectionContextType = {
  connected: false, connecting: false, error: null, lastRefresh: null,
  namespace: 'default', baseUrl: '', namespaces: [],
  connect: async () => false,
  disconnect: () => {},
  refreshAll: async () => {},
  refreshNamespaces: async () => {},
  switchNamespace: async () => {},
  startPolling: () => {},
  stopPolling: () => {},
  createModelAPI: async (api) => api,
  updateModelAPI: async (api) => api,
  deleteModelAPI: async () => {},
  createMCPServer: async (server) => server,
  updateMCPServer: async (server) => server,
  deleteMCPServer: async () => {},
  createAgent: async (agent) => agent,
  updateAgent: async (agent) => agent,
  deleteAgent: async () => {},
  createSecret: async (secret) => secret,
  deleteSecret: async () => {},
};

// eslint-disable-next-line react-refresh/only-export-components
export function useKubernetesConnection() {
  const context = useContext(KubernetesConnectionContext);
  if (!context) {
    console.warn('[useKubernetesConnection] Context unavailable, using fallback.');
    return defaultContextValue;
  }
  return context;
}
