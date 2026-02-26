import { create } from 'zustand';
import type {
  ModelAPI,
  MCPServer,
  Agent,
  Pod,
  Deployment,
  PersistentVolumeClaim,
  Service,
  K8sSecret,
  LogEntry,
  ResourceStatus,
} from '@/types/kubernetes';

interface KubernetesState {
  // Agentic Resources
  modelAPIs: ModelAPI[];
  mcpServers: MCPServer[];
  agents: Agent[];
  
  // Standard K8s Resources
  pods: Pod[];
  deployments: Deployment[];
  pvcs: PersistentVolumeClaim[];
  services: Service[];
  secrets: K8sSecret[];
  
  // Logs
  logs: LogEntry[];
  
  // UI State
  selectedResource: any | null;
  selectedResourceMode: 'view' | 'edit' | null;
  activeTab: string;
  
  // Auto-refresh state
  autoRefreshEnabled: boolean;
  autoRefreshInterval: number; // in milliseconds
  isRefreshing: boolean;
  nextRefreshTime: number | null; // timestamp when next refresh will occur
  
  // Actions
  setModelAPIs: (apis: ModelAPI[], forceReplace?: boolean) => void;
  addModelAPI: (api: ModelAPI) => void;
  updateModelAPI: (name: string, api: Partial<ModelAPI>) => void;
  deleteModelAPI: (name: string) => void;
  
  setMCPServers: (servers: MCPServer[], forceReplace?: boolean) => void;
  addMCPServer: (server: MCPServer) => void;
  updateMCPServer: (name: string, server: Partial<MCPServer>) => void;
  deleteMCPServer: (name: string) => void;
  
  setAgents: (agents: Agent[], forceReplace?: boolean) => void;
  addAgent: (agent: Agent) => void;
  updateAgent: (name: string, agent: Partial<Agent>) => void;
  deleteAgent: (name: string) => void;
  
  setPods: (pods: Pod[]) => void;
  deletePod: (name: string) => void;
  setDeployments: (deployments: Deployment[]) => void;
  updateDeployment: (name: string, deployment: Partial<Deployment>) => void;
  deleteDeployment: (name: string) => void;
  setPVCs: (pvcs: PersistentVolumeClaim[]) => void;
  deletePVC: (name: string) => void;
  setServices: (services: Service[]) => void;
  addService: (service: Service) => void;
  deleteService: (name: string) => void;
  setSecrets: (secrets: K8sSecret[]) => void;
  addSecret: (secret: K8sSecret) => void;
  deleteSecret: (name: string) => void;
  
  // Clear all resources (for namespace switching)
  clearAllResources: () => void;
  
  addLog: (log: LogEntry) => void;
  clearLogs: () => void;
  
  setSelectedResource: (resource: any | null) => void;
  setSelectedResourceMode: (mode: 'view' | 'edit' | null) => void;
  setActiveTab: (tab: string) => void;
  
  // Auto-refresh actions
  setAutoRefreshEnabled: (enabled: boolean) => void;
  setAutoRefreshInterval: (interval: number) => void;
  setIsRefreshing: (refreshing: boolean) => void;
  setNextRefreshTime: (time: number | null) => void;
  resetCountdown: () => void;
}

// No mock data - all data comes from real Kubernetes API

export const useKubernetesStore = create<KubernetesState>((set) => ({
  // Initialize with empty arrays (real data comes from API)
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
  
  // Auto-refresh defaults (saved to localStorage)
  autoRefreshEnabled: JSON.parse(localStorage.getItem('autoRefreshEnabled') || 'true'),
  autoRefreshInterval: JSON.parse(localStorage.getItem('autoRefreshInterval') || '30000'),
  isRefreshing: false,
  nextRefreshTime: null,
  
  // ModelAPI actions - forceReplace used during namespace switching
  setModelAPIs: (apis, forceReplace = false) => set((state) => {
    // If empty array from API, keep existing unless force replace (namespace switch)
    if (!forceReplace && apis.length === 0 && state.modelAPIs.length > 0) {
      return state;
    }
    return { modelAPIs: apis };
  }),
  addModelAPI: (api) => set((state) => ({ modelAPIs: [...state.modelAPIs, api] })),
  updateModelAPI: (name, api) => set((state) => ({
    modelAPIs: state.modelAPIs.map((a) => a.metadata.name === name ? { ...a, ...api } : a),
  })),
  deleteModelAPI: (name) => set((state) => ({
    modelAPIs: state.modelAPIs.filter((a) => a.metadata.name !== name),
  })),
  
  // MCPServer actions - forceReplace used during namespace switching
  setMCPServers: (servers, forceReplace = false) => set((state) => {
    if (!forceReplace && servers.length === 0 && state.mcpServers.length > 0) {
      return state;
    }
    return { mcpServers: servers };
  }),
  addMCPServer: (server) => set((state) => ({ mcpServers: [...state.mcpServers, server] })),
  updateMCPServer: (name, server) => set((state) => ({
    mcpServers: state.mcpServers.map((s) => s.metadata.name === name ? { ...s, ...server } : s),
  })),
  deleteMCPServer: (name) => set((state) => ({
    mcpServers: state.mcpServers.filter((s) => s.metadata.name !== name),
  })),
  
  // Agent actions - forceReplace used during namespace switching
  setAgents: (agents, forceReplace = false) => set((state) => {
    if (!forceReplace && agents.length === 0 && state.agents.length > 0) {
      return state;
    }
    return { agents };
  }),
  addAgent: (agent) => set((state) => ({ agents: [...state.agents, agent] })),
  updateAgent: (name, agent) => set((state) => ({
    agents: state.agents.map((a) => a.metadata.name === name ? { ...a, ...agent } : a),
  })),
  deleteAgent: (name) => set((state) => ({
    agents: state.agents.filter((a) => a.metadata.name !== name),
  })),
  
  // Clear all resources for namespace switching
  clearAllResources: () => set({
    modelAPIs: [],
    mcpServers: [],
    agents: [],
    pods: [],
    deployments: [],
    pvcs: [],
    services: [],
    secrets: [],
  }),
  
  // K8s resources
  setPods: (pods) => set({ pods }),
  deletePod: (name) => set((state) => ({ pods: state.pods.filter((p) => p.metadata.name !== name) })),
  setDeployments: (deployments) => set({ deployments }),
  updateDeployment: (name, deployment) => set((state) => ({
    deployments: state.deployments.map((d) => d.metadata.name === name ? { ...d, ...deployment } : d),
  })),
  deleteDeployment: (name) => set((state) => ({ deployments: state.deployments.filter((d) => d.metadata.name !== name) })),
  setPVCs: (pvcs) => set({ pvcs }),
  deletePVC: (name) => set((state) => ({ pvcs: state.pvcs.filter((p) => p.metadata.name !== name) })),
  setServices: (services) => set({ services }),
  addService: (service) => set((state) => ({ services: [...state.services, service] })),
  deleteService: (name) => set((state) => ({ services: state.services.filter((s) => s.metadata.name !== name) })),
  setSecrets: (secrets) => set({ secrets }),
  addSecret: (secret) => set((state) => ({ secrets: [...state.secrets, secret] })),
  deleteSecret: (name) => set((state) => ({ secrets: state.secrets.filter((s) => s.metadata.name !== name) })),
  
  // Logs
  addLog: (log) => set((state) => ({ logs: [log, ...state.logs].slice(0, 1000) })),
  clearLogs: () => set({ logs: [] }),
  
  setSelectedResource: (resource) => set({ selectedResource: resource }),
  setSelectedResourceMode: (mode) => set({ selectedResourceMode: mode }),
  setActiveTab: (tab) => set({ activeTab: tab }),
  
  // Auto-refresh actions
  setAutoRefreshEnabled: (enabled) => {
    localStorage.setItem('autoRefreshEnabled', JSON.stringify(enabled));
    set({ autoRefreshEnabled: enabled });
  },
  setAutoRefreshInterval: (interval) => {
    localStorage.setItem('autoRefreshInterval', JSON.stringify(interval));
    set({ autoRefreshInterval: interval });
  },
  setIsRefreshing: (refreshing) => set({ isRefreshing: refreshing }),
  setNextRefreshTime: (time) => set({ nextRefreshTime: time }),
  resetCountdown: () => set((state) => ({ 
    nextRefreshTime: state.autoRefreshEnabled && state.autoRefreshInterval > 0 
      ? Date.now() + state.autoRefreshInterval 
      : null 
  })),
}));
