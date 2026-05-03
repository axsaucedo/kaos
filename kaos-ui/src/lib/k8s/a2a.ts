/**
 * A2A (Agent-to-Agent) protocol client methods.
 * Uses K8s service proxy to communicate with agent pods.
 */

import type { AgentCard, A2ATask, JsonRpcResponse, ListTasksResult } from '@/types/a2a';
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
 * Accepts structured SendMessageParams directly.
 */
export async function sendA2AMessage(
  serviceName: string,
  params: Record<string, unknown>,
  namespace?: string,
  port: number = 8000
): Promise<A2ATask> {
  const rpcResponse = await sendA2AJsonRpc(
    serviceName,
    'SendMessage',
    params,
    namespace,
    port
  );

  if (rpcResponse.error) {
    throw new Error(rpcResponse.error.message || 'A2A SendMessage failed');
  }

  return rpcResponse.result as A2ATask;
}

/**
 * Get an A2A task by ID.
 */
export async function getA2ATask(
  serviceName: string,
  taskId: string,
  namespace?: string,
  port: number = 8000
): Promise<A2ATask> {
  const rpcResponse = await sendA2AJsonRpc(
    serviceName,
    'GetTask',
    { id: taskId },
    namespace,
    port
  );

  if (rpcResponse.error) {
    throw new Error(rpcResponse.error.message || 'A2A GetTask failed');
  }

  return rpcResponse.result as A2ATask;
}

/**
 * List retained A2A tasks for an agent.
 */
export async function listA2ATasks(
  serviceName: string,
  namespace?: string,
  port: number = 8000
): Promise<ListTasksResult> {
  const rpcResponse = await sendA2AJsonRpc(
    serviceName,
    'ListTasks',
    {},
    namespace,
    port
  );

  if (rpcResponse.error) {
    throw new Error(rpcResponse.error.message || 'A2A ListTasks failed');
  }

  return rpcResponse.result as ListTasksResult;
}

/**
 * Cancel an A2A task by ID.
 */
export async function cancelA2ATask(
  serviceName: string,
  taskId: string,
  namespace?: string,
  port: number = 8000
): Promise<A2ATask> {
  const rpcResponse = await sendA2AJsonRpc(
    serviceName,
    'CancelTask',
    { id: taskId },
    namespace,
    port
  );

  if (rpcResponse.error) {
    throw new Error(rpcResponse.error.message || 'A2A CancelTask failed');
  }

  return rpcResponse.result as A2ATask;
}
