/**
 * Hook for KAOS CRD CRUD operations with store sync and logging.
 * Eliminates repetitive create/update/delete boilerplate in the connection context.
 */

import { k8sClient } from '@/lib/kubernetes-client';
import { useKubernetesStore } from '@/stores/kubernetesStore';
import type { ModelAPI, MCPServer, Agent, K8sSecret, LogEntry } from '@/types/kubernetes';

type LogFn = (
  level: LogEntry['level'],
  message: string,
  source: string,
  resourceName?: string,
  resourceKind?: string
) => void;

/** Creates create/update/delete operations for a CRD resource type */
function makeCrud<T extends { metadata: { name: string } }>(
  kind: string,
  client: {
    create: (item: T) => Promise<T>;
    update: (item: T) => Promise<T>;
    delete: (name: string, ns?: string) => Promise<unknown>;
  },
  storeOps: {
    add: (item: T) => void;
    update: (name: string, item: T) => void;
    delete: (name: string) => void;
  },
  log: LogFn,
  refreshAll: () => Promise<void>,
) {
  const scheduleRefresh = () => setTimeout(() => refreshAll(), 500);

  return {
    create: async (item: T): Promise<T> => {
      const result = await client.create(item);
      storeOps.add(result);
      log('info', `Created ${kind} ${result.metadata.name}`, 'api', result.metadata.name, kind);
      scheduleRefresh();
      return result;
    },
    update: async (item: T): Promise<T> => {
      const result = await client.update(item);
      storeOps.update(result.metadata.name, result);
      log('info', `Updated ${kind} ${result.metadata.name}`, 'api', result.metadata.name, kind);
      scheduleRefresh();
      return result;
    },
    delete: async (name: string, namespace?: string): Promise<void> => {
      await client.delete(name, namespace);
      storeOps.delete(name);
      log('info', `Deleted ${kind} ${name}`, 'api', name, kind);
      scheduleRefresh();
    },
  };
}

export function useResourceCrud(addLogEntry: LogFn, refreshAll: () => Promise<void>) {
  const store = useKubernetesStore();

  const modelAPI = makeCrud<ModelAPI>(
    'ModelAPI',
    { create: (a) => k8sClient.createModelAPI(a), update: (a) => k8sClient.updateModelAPI(a), delete: (n, ns) => k8sClient.deleteModelAPI(n, ns) },
    { add: store.addModelAPI, update: store.updateModelAPI, delete: store.deleteModelAPI },
    addLogEntry, refreshAll,
  );

  const mcpServer = makeCrud<MCPServer>(
    'MCPServer',
    { create: (s) => k8sClient.createMCPServer(s), update: (s) => k8sClient.updateMCPServer(s), delete: (n, ns) => k8sClient.deleteMCPServer(n, ns) },
    { add: store.addMCPServer, update: store.updateMCPServer, delete: store.deleteMCPServer },
    addLogEntry, refreshAll,
  );

  const agent = makeCrud<Agent>(
    'Agent',
    { create: (a) => k8sClient.createAgent(a), update: (a) => k8sClient.updateAgent(a), delete: (n, ns) => k8sClient.deleteAgent(n, ns) },
    { add: store.addAgent, update: store.updateAgent, delete: store.deleteAgent },
    addLogEntry, refreshAll,
  );

  const createSecret = async (secret: K8sSecret): Promise<K8sSecret> => {
    const created = await k8sClient.createSecret(secret);
    const secretWithKeys: K8sSecret = {
      ...created,
      dataKeys: secret.data ? Object.keys(secret.data) : [],
    };
    store.addSecret(secretWithKeys);
    addLogEntry('info', `Created Secret ${created.metadata.name}`, 'api', created.metadata.name, 'Secret');
    setTimeout(() => refreshAll(), 500);
    return secretWithKeys;
  };

  const deleteSecret = async (name: string, namespace?: string): Promise<void> => {
    await k8sClient.deleteSecret(name, namespace);
    store.deleteSecret(name);
    addLogEntry('info', `Deleted Secret ${name}`, 'api', name, 'Secret');
    setTimeout(() => refreshAll(), 500);
  };

  return {
    createModelAPI: modelAPI.create,
    updateModelAPI: modelAPI.update,
    deleteModelAPI: modelAPI.delete,
    createMCPServer: mcpServer.create,
    updateMCPServer: mcpServer.update,
    deleteMCPServer: mcpServer.delete,
    createAgent: agent.create,
    updateAgent: agent.update,
    deleteAgent: agent.delete,
    createSecret,
    deleteSecret,
  };
}
