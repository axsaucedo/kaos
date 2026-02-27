/**
 * Real Kubernetes API Hook
 * 
 * Connects to the real Kubernetes cluster via k8sClient
 * Provides CRUD operations and syncs with Zustand store
 */

import { useEffect, useState, useCallback, useRef } from 'react';
import { k8sClient } from '@/lib/kubernetes-client';
import { useKubernetesStore } from '@/stores/kubernetesStore';
import type { ModelAPI, MCPServer, Agent, LogEntry, Service } from '@/types/kubernetes';

interface APIState {
  connected: boolean;
  loading: boolean;
  error: string | null;
  lastRefresh: Date | null;
}

const POLL_INTERVAL = 30000; // 30 seconds

export function useRealKubernetesAPI() {
  const [state, setState] = useState<APIState>({
    connected: false,
    loading: false,
    error: null,
    lastRefresh: null,
  });

  const pollIntervalRef = useRef<NodeJS.Timeout | null>(null);
  const store = useKubernetesStore();

  // Add log entry helper
  const addLogEntry = useCallback(
    (level: LogEntry['level'], message: string, source: string, resourceName?: string, resourceKind?: string) => {
      store.addLog({
        timestamp: new Date().toISOString(),
        level,
        message,
        source,
        resourceName,
        resourceKind,
      });
    },
    [store]
  );

  // Test connection
  const testConnection = useCallback(async (): Promise<boolean> => {
    if (!k8sClient.isConfigured()) {
      return false;
    }

    try {
      const result = await k8sClient.testConnection();
      if (result.success) {
        setState(s => ({ ...s, connected: true, error: null }));
        addLogEntry('info', `Connected to Kubernetes ${result.version}`, 'api-client');
        return true;
      } else {
        setState(s => ({ ...s, connected: false, error: result.error || 'Connection failed' }));
        return false;
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Connection failed';
      setState(s => ({ ...s, connected: false, error: message }));
      return false;
    }
  }, [addLogEntry]);

  // Fetch and sync all resources
  const refreshAll = useCallback(async () => {
    console.log('[useRealKubernetesAPI] refreshAll called');
    console.log('[useRealKubernetesAPI] k8sClient configured:', k8sClient.isConfigured());
    console.log('[useRealKubernetesAPI] k8sClient config:', k8sClient.getConfig());
    
    if (!k8sClient.isConfigured()) {
      setState(s => ({ ...s, error: 'Not configured' }));
      return;
    }

    setState(s => ({ ...s, loading: true }));

    try {
      // Fetch all resources in parallel
      console.log('[useRealKubernetesAPI] Fetching all resources...');
      const [modelAPIs, mcpServers, agents, pods, deployments, pvcs, services] = await Promise.all([
        k8sClient.listModelAPIs().catch((e) => { console.error('[useRealKubernetesAPI] ModelAPIs error:', e); return []; }),
        k8sClient.listMCPServers().catch((e) => { console.error('[useRealKubernetesAPI] MCPServers error:', e); return []; }),
        k8sClient.listAgents().catch((e) => { console.error('[useRealKubernetesAPI] Agents error:', e); return []; }),
        k8sClient.listPods().catch((e) => { console.error('[useRealKubernetesAPI] Pods error:', e); return []; }),
        k8sClient.listDeployments().catch((e) => { console.error('[useRealKubernetesAPI] Deployments error:', e); return []; }),
        k8sClient.listPVCs().catch((e) => { console.error('[useRealKubernetesAPI] PVCs error:', e); return []; }),
        k8sClient.listServices().catch((e) => { console.error('[useRealKubernetesAPI] Services error:', e); return []; }),
      ]);

      console.log('[useRealKubernetesAPI] Fetched resources:', {
        modelAPIs: modelAPIs.length,
        mcpServers: mcpServers.length,
        agents: agents.length,
        pods: pods.length,
        deployments: deployments.length,
        pvcs: pvcs.length,
        services: services.length,
      });

      // Sync to store
      store.setModelAPIs(modelAPIs);
      store.setMCPServers(mcpServers);
      store.setAgents(agents);
      store.setPods(pods);
      store.setDeployments(deployments);
      store.setPVCs(pvcs);
      store.setServices(services);

      setState(s => ({
        ...s,
        loading: false,
        error: null,
        connected: true,
        lastRefresh: new Date(),
      }));

      addLogEntry('info', `Refreshed: ${modelAPIs.length} ModelAPIs, ${mcpServers.length} MCPServers, ${agents.length} Agents`, 'api-client');
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to fetch resources';
      console.error('[useRealKubernetesAPI] refreshAll error:', error);
      setState(s => ({ ...s, loading: false, error: message }));
      addLogEntry('error', message, 'api-client');
    }
  }, [store, addLogEntry]);

  // Start polling for updates
  const startPolling = useCallback(() => {
    if (pollIntervalRef.current) {
      clearInterval(pollIntervalRef.current);
    }

    pollIntervalRef.current = setInterval(() => {
      if (k8sClient.isConfigured()) {
        refreshAll();
      }
    }, POLL_INTERVAL);
  }, [refreshAll]);

  // Stop polling
  const stopPolling = useCallback(() => {
    if (pollIntervalRef.current) {
      clearInterval(pollIntervalRef.current);
      pollIntervalRef.current = null;
    }
  }, []);

  // Connect and start syncing
  const connect = useCallback(async (baseUrl: string, namespace: string = 'default') => {
    k8sClient.setConfig({ baseUrl, namespace });
    
    const connected = await testConnection();
    if (connected) {
      await refreshAll();
      startPolling();
    }
    
    return connected;
  }, [testConnection, refreshAll, startPolling]);

  // Disconnect
  const disconnect = useCallback(() => {
    stopPolling();
    k8sClient.setConfig({ baseUrl: '', namespace: 'default' });
    setState({ connected: false, loading: false, error: null, lastRefresh: null });
    
    // Clear store
    store.setModelAPIs([]);
    store.setMCPServers([]);
    store.setAgents([]);
    store.setPods([]);
    store.setDeployments([]);
    store.setPVCs([]);
    store.setServices([]);
  }, [stopPolling, store]);

  // Cleanup on unmount
  useEffect(() => {
    return () => stopPolling();
  }, [stopPolling]);

  // ============= ModelAPI CRUD =============
  const createModelAPI = useCallback(async (api: ModelAPI): Promise<ModelAPI> => {
    try {
      const created = await k8sClient.createModelAPI(api);
      store.addModelAPI(created);
      addLogEntry('info', `Created ModelAPI ${created.metadata.name}`, 'api-client', created.metadata.name, 'ModelAPI');
      return created;
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to create ModelAPI';
      addLogEntry('error', message, 'api-client');
      throw error;
    }
  }, [store, addLogEntry]);

  const updateModelAPI = useCallback(async (api: ModelAPI): Promise<ModelAPI> => {
    try {
      const updated = await k8sClient.updateModelAPI(api);
      store.updateModelAPI(updated.metadata.name, updated);
      addLogEntry('info', `Updated ModelAPI ${updated.metadata.name}`, 'api-client', updated.metadata.name, 'ModelAPI');
      return updated;
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to update ModelAPI';
      addLogEntry('error', message, 'api-client');
      throw error;
    }
  }, [store, addLogEntry]);

  const deleteModelAPI = useCallback(async (name: string, namespace?: string): Promise<void> => {
    try {
      await k8sClient.deleteModelAPI(name, namespace);
      store.deleteModelAPI(name);
      addLogEntry('info', `Deleted ModelAPI ${name}`, 'api-client', name, 'ModelAPI');
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to delete ModelAPI';
      addLogEntry('error', message, 'api-client');
      throw error;
    }
  }, [store, addLogEntry]);

  // ============= MCPServer CRUD =============
  const createMCPServer = useCallback(async (server: MCPServer): Promise<MCPServer> => {
    try {
      const created = await k8sClient.createMCPServer(server);
      store.addMCPServer(created);
      addLogEntry('info', `Created MCPServer ${created.metadata.name}`, 'api-client', created.metadata.name, 'MCPServer');
      return created;
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to create MCPServer';
      addLogEntry('error', message, 'api-client');
      throw error;
    }
  }, [store, addLogEntry]);

  const updateMCPServer = useCallback(async (server: MCPServer): Promise<MCPServer> => {
    try {
      const updated = await k8sClient.updateMCPServer(server);
      store.updateMCPServer(updated.metadata.name, updated);
      addLogEntry('info', `Updated MCPServer ${updated.metadata.name}`, 'api-client', updated.metadata.name, 'MCPServer');
      return updated;
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to update MCPServer';
      addLogEntry('error', message, 'api-client');
      throw error;
    }
  }, [store, addLogEntry]);

  const deleteMCPServer = useCallback(async (name: string, namespace?: string): Promise<void> => {
    try {
      await k8sClient.deleteMCPServer(name, namespace);
      store.deleteMCPServer(name);
      addLogEntry('info', `Deleted MCPServer ${name}`, 'api-client', name, 'MCPServer');
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to delete MCPServer';
      addLogEntry('error', message, 'api-client');
      throw error;
    }
  }, [store, addLogEntry]);

  // ============= Agent CRUD =============
  const createAgent = useCallback(async (agent: Agent): Promise<Agent> => {
    try {
      const created = await k8sClient.createAgent(agent);
      store.addAgent(created);
      addLogEntry('info', `Created Agent ${created.metadata.name}`, 'api-client', created.metadata.name, 'Agent');
      return created;
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to create Agent';
      addLogEntry('error', message, 'api-client');
      throw error;
    }
  }, [store, addLogEntry]);

  const updateAgent = useCallback(async (agent: Agent): Promise<Agent> => {
    try {
      const updated = await k8sClient.updateAgent(agent);
      store.updateAgent(updated.metadata.name, updated);
      addLogEntry('info', `Updated Agent ${updated.metadata.name}`, 'api-client', updated.metadata.name, 'Agent');
      return updated;
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to update Agent';
      addLogEntry('error', message, 'api-client');
      throw error;
    }
  }, [store, addLogEntry]);

  const deleteAgent = useCallback(async (name: string, namespace?: string): Promise<void> => {
    try {
      await k8sClient.deleteAgent(name, namespace);
      store.deleteAgent(name);
      addLogEntry('info', `Deleted Agent ${name}`, 'api-client', name, 'Agent');
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to delete Agent';
      addLogEntry('error', message, 'api-client');
      throw error;
    }
  }, [store, addLogEntry]);

  // ============= Service CRUD =============
  const createService = useCallback(async (service: Service): Promise<Service> => {
    try {
      const created = await k8sClient.createService(service);
      store.addService(created);
      addLogEntry('info', `Created Service ${created.metadata.name}`, 'api-client', created.metadata.name, 'Service');
      return created;
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to create Service';
      addLogEntry('error', message, 'api-client');
      throw error;
    }
  }, [store, addLogEntry]);

  const deleteService = useCallback(async (name: string, namespace?: string): Promise<void> => {
    try {
      await k8sClient.deleteService(name, namespace);
      store.deleteService(name);
      addLogEntry('info', `Deleted Service ${name}`, 'api-client', name, 'Service');
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to delete Service';
      addLogEntry('error', message, 'api-client');
      throw error;
    }
  }, [store, addLogEntry]);

  // ============= Pod Operations =============
  const deletePod = useCallback(async (name: string, namespace?: string): Promise<void> => {
    try {
      await k8sClient.deletePod(name, namespace);
      store.deletePod(name);
      addLogEntry('info', `Deleted Pod ${name}`, 'api-client', name, 'Pod');
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to delete Pod';
      addLogEntry('error', message, 'api-client');
      throw error;
    }
  }, [store, addLogEntry]);

  const getPodLogs = useCallback(async (name: string, namespace?: string, options?: { container?: string; tailLines?: number }): Promise<string> => {
    try {
      return await k8sClient.getPodLogs(name, namespace, options);
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to get pod logs';
      addLogEntry('error', message, 'api-client');
      throw error;
    }
  }, [addLogEntry]);

  // ============= Deployment Operations =============
  const scaleDeployment = useCallback(async (name: string, replicas: number, namespace?: string): Promise<void> => {
    try {
      const updated = await k8sClient.scaleDeployment(name, replicas, namespace);
      store.updateDeployment(name, updated);
      addLogEntry('info', `Scaled Deployment ${name} to ${replicas} replicas`, 'api-client', name, 'Deployment');
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to scale deployment';
      addLogEntry('error', message, 'api-client');
      throw error;
    }
  }, [store, addLogEntry]);

  const deleteDeployment = useCallback(async (name: string, namespace?: string): Promise<void> => {
    try {
      await k8sClient.deleteDeployment(name, namespace);
      store.deleteDeployment(name);
      addLogEntry('info', `Deleted Deployment ${name}`, 'api-client', name, 'Deployment');
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to delete deployment';
      addLogEntry('error', message, 'api-client');
      throw error;
    }
  }, [store, addLogEntry]);

  // ============= PVC Operations =============
  const deletePVC = useCallback(async (name: string, namespace?: string): Promise<void> => {
    try {
      await k8sClient.deletePVC(name, namespace);
      store.deletePVC(name);
      addLogEntry('info', `Deleted PVC ${name}`, 'api-client', name, 'PersistentVolumeClaim');
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to delete PVC';
      addLogEntry('error', message, 'api-client');
      throw error;
    }
  }, [store, addLogEntry]);

  return {
    // State
    ...state,
    
    // Connection
    connect,
    disconnect,
    testConnection,
    refreshAll,
    
    // Polling
    startPolling,
    stopPolling,
    
    // ModelAPI CRUD
    createModelAPI,
    updateModelAPI,
    deleteModelAPI,
    
    // MCPServer CRUD
    createMCPServer,
    updateMCPServer,
    deleteMCPServer,
    
    // Agent CRUD
    createAgent,
    updateAgent,
    deleteAgent,
    
    // Service CRUD
    createService,
    deleteService,
    
    // Pod operations
    deletePod,
    getPodLogs,
    
    // Deployment operations
    scaleDeployment,
    deleteDeployment,
    
    // PVC operations
    deletePVC,
  };
}
