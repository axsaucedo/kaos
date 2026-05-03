import { describe, it, expect, vi, beforeEach } from 'vitest';
import { listA2ATasks } from '@/lib/k8s/a2a';
import { k8sClient } from '@/lib/k8s/index';

vi.mock('@/lib/k8s/index', () => ({
  k8sClient: {
    proxyServiceRequest: vi.fn(),
  },
}));

const mockedProxyServiceRequest = vi.mocked(k8sClient.proxyServiceRequest);

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

describe('A2A K8s client', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('lists retained tasks with ListTasks JSON-RPC', async () => {
    mockedProxyServiceRequest.mockResolvedValue(jsonResponse({
      jsonrpc: '2.0',
      id: 'ui-1',
      result: {
        tasks: [
          {
            id: 'task-1',
            sessionId: 'session-1',
            status: { state: 'completed', timestamp: '2026-01-01T00:00:00Z' },
            history: [],
            artifacts: [],
            metadata: {},
            events: [],
            autonomous: false,
            output: '',
          },
        ],
        count: 1,
      },
    }));

    const result = await listA2ATasks('agent-demo', 'kaos-system');
    const [serviceName, path, options, namespace, port] = mockedProxyServiceRequest.mock.calls[0];
    const body = JSON.parse(String(options.body));

    expect(result.count).toBe(1);
    expect(result.tasks[0].id).toBe('task-1');
    expect(serviceName).toBe('agent-demo');
    expect(path).toBe('/');
    expect(namespace).toBe('kaos-system');
    expect(port).toBe(8000);
    expect(body.method).toBe('ListTasks');
    expect(body.params).toEqual({});
  });

  it('throws JSON-RPC list errors', async () => {
    mockedProxyServiceRequest.mockResolvedValue(jsonResponse({
      jsonrpc: '2.0',
      id: 'ui-1',
      error: { code: -32601, message: 'Method not found' },
    }));

    await expect(listA2ATasks('agent-demo', 'default')).rejects.toThrow('Method not found');
  });
});
