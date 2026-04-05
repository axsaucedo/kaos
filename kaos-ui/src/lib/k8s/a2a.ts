/**
 * A2A (Agent-to-Agent) protocol client methods.
 * Uses K8s service proxy to communicate with agent pods.
 */

import type { AgentCard, JsonRpcResponse } from '@/types/a2a';
import { k8sClient } from './index';

/**
 * Fetch agent card from /.well-known/agent.json via K8s service proxy.
 */
export async function getAgentCard(
  serviceName: string,
  namespace?: string,
  port: number = 8000
): Promise<AgentCard> {
  const response = await k8sClient.proxyServiceRequest(
    serviceName,
    '/.well-known/agent.json',
    { method: 'GET' },
    namespace,
    port
  );

  if (!response.ok) {
    const text = await response.text();
    throw new Error(`Failed to fetch agent card: ${response.status} — ${text}`);
  }

  return response.json();
}

/**
 * Send a JSON-RPC 2.0 request to an agent's A2A endpoint (POST /).
 */
export async function sendA2AJsonRpc(
  serviceName: string,
  method: string,
  params: Record<string, unknown>,
  namespace?: string,
  port: number = 8000
): Promise<JsonRpcResponse> {
  const rpcId = `ui-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;

  const response = await k8sClient.proxyServiceRequest(
    serviceName,
    '/',
    {
      method: 'POST',
      body: JSON.stringify({
        jsonrpc: '2.0',
        id: rpcId,
        method,
        params,
      }),
    },
    namespace,
    port
  );

  if (!response.ok) {
    const text = await response.text();
    throw new Error(`A2A JSON-RPC request failed: ${response.status} — ${text}`);
  }

  return response.json();
}

/**
 * Send an A2A SendMessage request.
 */
export async function sendA2AMessage(
  serviceName: string,
  message: string,
  options: {
    sessionId?: string;
    mode?: 'interactive' | 'autonomous';
    budgets?: {
      maxIterations?: number;
      maxRuntimeSeconds?: number;
      maxToolCalls?: number;
    };
    namespace?: string;
    port?: number;
  } = {}
): Promise<JsonRpcResponse> {
  const params: Record<string, unknown> = {
    message: {
      role: 'user',
      parts: [{ type: 'text', text: message }],
    },
  };

  if (options.sessionId) {
    params.contextId = options.sessionId;
  }

  if (options.mode || options.budgets) {
    const config: Record<string, unknown> = {};
    if (options.mode) config.mode = options.mode;
    if (options.budgets) config.budgets = options.budgets;
    params.configuration = config;
  }

  return sendA2AJsonRpc(
    serviceName,
    'SendMessage',
    params,
    options.namespace,
    options.port
  );
}

/**
 * Get an A2A task by ID.
 */
export async function getA2ATask(
  serviceName: string,
  taskId: string,
  namespace?: string,
  port: number = 8000
): Promise<JsonRpcResponse> {
  return sendA2AJsonRpc(
    serviceName,
    'GetTask',
    { id: taskId },
    namespace,
    port
  );
}

/**
 * Cancel an A2A task by ID.
 */
export async function cancelA2ATask(
  serviceName: string,
  taskId: string,
  namespace?: string,
  port: number = 8000
): Promise<JsonRpcResponse> {
  return sendA2AJsonRpc(
    serviceName,
    'CancelTask',
    { id: taskId },
    namespace,
    port
  );
}
