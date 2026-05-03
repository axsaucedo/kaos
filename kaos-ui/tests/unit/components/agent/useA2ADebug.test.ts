import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useA2ADebug } from '@/components/agent/useA2ADebug';
import type { A2ATask } from '@/types/a2a';
import type { Agent } from '@/types/kubernetes';
import {
  getAgentCard,
  sendA2AMessage,
  getA2ATask,
  cancelA2ATask,
  listA2ATasks,
} from '@/lib/k8s/a2a';

vi.mock('@/lib/k8s/a2a', () => ({
  getAgentCard: vi.fn(),
  sendA2AMessage: vi.fn(),
  getA2ATask: vi.fn(),
  cancelA2ATask: vi.fn(),
  listA2ATasks: vi.fn(),
}));

const mockedListA2ATasks = vi.mocked(listA2ATasks);
const mockedSendA2AMessage = vi.mocked(sendA2AMessage);
const mockedGetA2ATask = vi.mocked(getA2ATask);
const mockedCancelA2ATask = vi.mocked(cancelA2ATask);
const mockedGetAgentCard = vi.mocked(getAgentCard);

const agent = {
  metadata: {
    name: 'demo',
    namespace: 'kaos-system',
  },
} as Agent;

function makeTask(id: string, text: string, timestamp: string, state: A2ATask['status']['state'] = 'completed'): A2ATask {
  return {
    id,
    sessionId: `session-${id}`,
    status: { state, timestamp },
    history: [{ role: 'user', parts: [{ type: 'text', text }] }],
    artifacts: [],
    metadata: {},
    events: [],
    autonomous: false,
    output: '',
  };
}

describe('useA2ADebug', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockedGetAgentCard.mockResolvedValue({
      name: 'demo',
      description: '',
      url: '',
      version: '0.1.0',
      protocolVersion: '0.3.0',
      skills: [],
      capabilities: {
        streaming: true,
        pushNotifications: false,
        stateTransitionHistory: true,
      },
      supportedProtocols: ['jsonrpc'],
      defaultInputModes: ['text'],
      defaultOutputModes: ['text'],
    });
  });

  it('refreshes retained tasks into newest-first history', async () => {
    mockedListA2ATasks.mockResolvedValue({
      tasks: [
        makeTask('task-old', 'Older task', '2026-01-01T00:00:00Z'),
        makeTask('task-new', 'Newer task', '2026-01-02T00:00:00Z'),
      ],
      count: 2,
    });

    const { result } = renderHook(() => useA2ADebug(agent));

    await act(async () => {
      await result.current.refreshTasks();
    });

    expect(mockedListA2ATasks).toHaveBeenCalledWith('agent-demo', 'kaos-system');
    expect(result.current.taskHistory.map(entry => entry.taskId)).toEqual(['task-new', 'task-old']);
    expect(result.current.taskHistory[0].message).toBe('Newer task');
  });

  it('dedupes refreshed tasks and keeps the newest backend state', async () => {
    const submitted = makeTask('task-1', 'Work in progress', '2026-01-01T00:00:00Z', 'working');
    const completed = makeTask('task-1', 'Work in progress', '2026-01-02T00:00:00Z', 'completed');
    mockedListA2ATasks.mockResolvedValue({ tasks: [submitted], count: 1 });
    mockedSendA2AMessage.mockResolvedValue(completed);

    const { result } = renderHook(() => useA2ADebug(agent));

    await act(async () => {
      await result.current.refreshTasks();
      await result.current.sendMessage({
        message: { role: 'user', parts: [{ type: 'text', text: 'Work in progress' }] },
      });
    });

    expect(result.current.taskHistory).toHaveLength(1);
    expect(result.current.taskHistory[0].taskId).toBe('task-1');
    expect(result.current.taskHistory[0].state).toBe('completed');
  });

  it('keeps manual task lookup working after list failures', async () => {
    const task = makeTask('task-manual', 'Manual lookup', '2026-01-01T00:00:00Z');
    mockedListA2ATasks.mockRejectedValue(new Error('List unavailable'));
    mockedGetA2ATask.mockResolvedValue(task);

    const { result } = renderHook(() => useA2ADebug(agent));

    await act(async () => {
      await result.current.refreshTasks();
    });

    expect(result.current.taskListError).toBe('List unavailable');

    await act(async () => {
      await result.current.fetchTask('task-manual');
    });

    expect(mockedGetA2ATask).toHaveBeenCalledWith('agent-demo', 'task-manual', 'kaos-system');
    expect(result.current.currentTask?.id).toBe('task-manual');
    expect(result.current.taskHistory[0].taskId).toBe('task-manual');
  });

  it('merges canceled task state into history', async () => {
    const working = makeTask('task-cancel', 'Cancel me', '2026-01-01T00:00:00Z', 'working');
    const canceled = makeTask('task-cancel', 'Cancel me', '2026-01-02T00:00:00Z', 'canceled');
    mockedListA2ATasks.mockResolvedValue({ tasks: [working], count: 1 });
    mockedCancelA2ATask.mockResolvedValue(canceled);

    const { result } = renderHook(() => useA2ADebug(agent));

    await act(async () => {
      await result.current.refreshTasks();
      await result.current.cancelTask('task-cancel');
    });

    expect(result.current.taskHistory).toHaveLength(1);
    expect(result.current.taskHistory[0].state).toBe('canceled');
  });
});
