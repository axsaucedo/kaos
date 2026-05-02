// A2A (Agent-to-Agent) Protocol Types
// Based on pydantic-ai-server/pais/a2a.py and serverutils.py

// ============= Agent Card =============

export interface AgentCardCapabilities {
  streaming: boolean;
  pushNotifications: boolean;
  stateTransitionHistory: boolean;
}

export interface AgentCardSkill {
  id: string;
  name: string;
  description: string;
  tags: string[];
  inputModes: string[];
  outputModes: string[];
}

export interface AgentCard {
  name: string;
  description: string;
  url: string;
  version: string;
  protocolVersion: string;
  skills: AgentCardSkill[];
  capabilities: AgentCardCapabilities;
  supportedProtocols: string[];
  defaultInputModes: string[];
  defaultOutputModes: string[];
}

// ============= Task Types =============

export type TaskState = 'submitted' | 'working' | 'completed' | 'failed' | 'canceled' | 'input-required';

export interface TaskStatus {
  state: TaskState;
  message?: string;
  timestamp: string;
}

export interface TaskMessage {
  role: 'user' | 'agent';
  parts: { type: string; text: string }[];
}

export interface TaskEvent {
  id: string;
  type: string;
  timestamp: string;
  data: Record<string, unknown>;
}

export interface A2ATask {
  id: string;
  sessionId: string;
  status: TaskStatus;
  history: TaskMessage[];
  artifacts: Record<string, unknown>[];
  metadata: Record<string, unknown>;
  events: TaskEvent[];
  autonomous: boolean;
  output: string;
}

export interface ListTasksResult {
  tasks: A2ATask[];
  count: number;
}

// ============= JSON-RPC Types =============

export interface JsonRpcRequest {
  jsonrpc: '2.0';
  id: string | number;
  method: string;
  params?: Record<string, unknown>;
}

export interface JsonRpcError {
  code: number;
  message: string;
  data?: unknown;
}

export interface JsonRpcResponse {
  jsonrpc: '2.0';
  id: string | number | null;
  result?: unknown;
  error?: JsonRpcError;
}

// ============= SendMessage Types =============

export interface SendMessageConfiguration {
  mode?: 'interactive' | 'autonomous';
  budgets?: {
    maxIterations?: number;
    maxRuntimeSeconds?: number;
    maxToolCalls?: number;
  };
}

export interface SendMessageParams {
  message: TaskMessage;
  contextId?: string;
  sessionId?: string;
  configuration?: SendMessageConfiguration;
}
