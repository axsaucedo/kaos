import { describe, it, expect, beforeEach, vi } from 'vitest';

// Mock localStorage for auto-refresh state
const localStorageMock = (() => {
  const store: Record<string, string> = {};
  return {
    getItem: (key: string) => store[key] ?? null,
    setItem: (key: string, value: string) => { store[key] = value; },
    removeItem: (key: string) => { delete store[key]; },
    clear: () => { Object.keys(store).forEach((k) => delete store[k]); },
  };
})();
vi.stubGlobal('localStorage', localStorageMock);

import { useKubernetesStore } from '@/stores/kubernetesStore';

describe('kubernetesStore', () => {
  beforeEach(() => {
    // Reset store to initial state between tests
    useKubernetesStore.setState({
      modelAPIs: [],
      mcpServers: [],
      agents: [],
      pods: [],
      deployments: [],
      pvcs: [],
      services: [],
      secrets: [],
      logs: [],
      selectedResource: null,
      selectedResourceMode: null,
      activeTab: 'overview',
      isRefreshing: false,
      nextRefreshTime: null,
    });
  });

  describe('initial state', () => {
    it('starts with empty resource arrays', () => {
      const state = useKubernetesStore.getState();
      expect(state.agents).toEqual([]);
      expect(state.modelAPIs).toEqual([]);
      expect(state.mcpServers).toEqual([]);
      expect(state.pods).toEqual([]);
      expect(state.deployments).toEqual([]);
      expect(state.services).toEqual([]);
      expect(state.secrets).toEqual([]);
    });

    it('starts with default UI state', () => {
      const state = useKubernetesStore.getState();
      expect(state.selectedResource).toBeNull();
      expect(state.selectedResourceMode).toBeNull();
      expect(state.activeTab).toBe('overview');
    });
  });

  describe('agent mutations', () => {
    const mockAgent = {
      metadata: { name: 'test-agent', namespace: 'default' },
      spec: { modelAPI: 'test-model', model: 'gpt-4' },
    } as any;

    it('sets agents', () => {
      useKubernetesStore.getState().setAgents([mockAgent]);
      expect(useKubernetesStore.getState().agents).toEqual([mockAgent]);
    });

    it('adds an agent', () => {
      useKubernetesStore.getState().setAgents([mockAgent]);
      const newAgent = { ...mockAgent, metadata: { name: 'agent-2', namespace: 'default' } };
      useKubernetesStore.getState().addAgent(newAgent);
      expect(useKubernetesStore.getState().agents).toHaveLength(2);
    });

    it('updates an agent by name', () => {
      useKubernetesStore.getState().setAgents([mockAgent]);
      useKubernetesStore.getState().updateAgent('test-agent', {
        spec: { modelAPI: 'updated-model', model: 'gpt-5' },
      } as any);
      expect(useKubernetesStore.getState().agents[0].spec.modelAPI).toBe('updated-model');
    });

    it('deletes an agent by name', () => {
      useKubernetesStore.getState().setAgents([mockAgent]);
      useKubernetesStore.getState().deleteAgent('test-agent');
      expect(useKubernetesStore.getState().agents).toEqual([]);
    });

    it('does not replace existing agents with empty array unless forceReplace', () => {
      useKubernetesStore.getState().setAgents([mockAgent], true);
      useKubernetesStore.getState().setAgents([]);
      expect(useKubernetesStore.getState().agents).toHaveLength(1);

      useKubernetesStore.getState().setAgents([], true);
      expect(useKubernetesStore.getState().agents).toHaveLength(0);
    });
  });

  describe('modelAPI mutations', () => {
    const mockAPI = {
      metadata: { name: 'test-api', namespace: 'default' },
      spec: {},
    } as any;

    it('sets and deletes modelAPIs', () => {
      useKubernetesStore.getState().setModelAPIs([mockAPI], true);
      expect(useKubernetesStore.getState().modelAPIs).toHaveLength(1);
      useKubernetesStore.getState().deleteModelAPI('test-api');
      expect(useKubernetesStore.getState().modelAPIs).toHaveLength(0);
    });
  });

  describe('mcpServer mutations', () => {
    const mockServer = {
      metadata: { name: 'test-mcp', namespace: 'default' },
      spec: {},
    } as any;

    it('sets and deletes mcpServers', () => {
      useKubernetesStore.getState().setMCPServers([mockServer], true);
      expect(useKubernetesStore.getState().mcpServers).toHaveLength(1);
      useKubernetesStore.getState().deleteMCPServer('test-mcp');
      expect(useKubernetesStore.getState().mcpServers).toHaveLength(0);
    });
  });

  describe('clearAllResources', () => {
    it('clears all resource arrays', () => {
      const state = useKubernetesStore.getState();
      state.setAgents([{ metadata: { name: 'a' } } as any], true);
      state.setModelAPIs([{ metadata: { name: 'b' } } as any], true);
      state.setMCPServers([{ metadata: { name: 'c' } } as any], true);
      state.setPods([{ metadata: { name: 'd' } } as any]);

      useKubernetesStore.getState().clearAllResources();

      const cleared = useKubernetesStore.getState();
      expect(cleared.agents).toEqual([]);
      expect(cleared.modelAPIs).toEqual([]);
      expect(cleared.mcpServers).toEqual([]);
      expect(cleared.pods).toEqual([]);
      expect(cleared.services).toEqual([]);
      expect(cleared.secrets).toEqual([]);
    });
  });

  describe('UI state', () => {
    it('sets active tab', () => {
      useKubernetesStore.getState().setActiveTab('pods');
      expect(useKubernetesStore.getState().activeTab).toBe('pods');
    });

    it('sets selected resource and mode', () => {
      const resource = { name: 'test' };
      useKubernetesStore.getState().setSelectedResource(resource);
      useKubernetesStore.getState().setSelectedResourceMode('edit');
      expect(useKubernetesStore.getState().selectedResource).toBe(resource);
      expect(useKubernetesStore.getState().selectedResourceMode).toBe('edit');
    });
  });

  describe('logs', () => {
    it('adds logs and caps at 1000', () => {
      const state = useKubernetesStore.getState();
      for (let i = 0; i < 1005; i++) {
        state.addLog({ timestamp: new Date().toISOString(), message: `log-${i}` } as any);
      }
      expect(useKubernetesStore.getState().logs.length).toBeLessThanOrEqual(1000);
    });

    it('clears logs', () => {
      useKubernetesStore.getState().addLog({ timestamp: new Date().toISOString(), message: 'test' } as any);
      useKubernetesStore.getState().clearLogs();
      expect(useKubernetesStore.getState().logs).toEqual([]);
    });
  });

  describe('auto-refresh', () => {
    it('persists autoRefreshEnabled to localStorage', () => {
      useKubernetesStore.getState().setAutoRefreshEnabled(false);
      expect(localStorageMock.getItem('autoRefreshEnabled')).toBe('false');
    });

    it('persists autoRefreshInterval to localStorage', () => {
      useKubernetesStore.getState().setAutoRefreshInterval(60000);
      expect(localStorageMock.getItem('autoRefreshInterval')).toBe('60000');
    });
  });
});
