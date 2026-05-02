import { useState, useCallback, useRef, useEffect } from 'react';
import { getAgentCard, sendA2AMessage, getA2ATask, cancelA2ATask, listA2ATasks } from '@/lib/k8s/a2a';
import type { Agent } from '@/types/kubernetes';
import type { AgentCard, A2ATask, SendMessageParams } from '@/types/a2a';

export interface TaskHistoryEntry {
  taskId: string;
  state: string;
  mode: string;
  createdAt: Date;
  message: string;
}

const TERMINAL_STATES = ['completed', 'failed', 'canceled'];

function parseTaskDate(timestamp?: string): Date {
  if (!timestamp) return new Date();
  const date = new Date(timestamp);
  return Number.isNaN(date.getTime()) ? new Date() : date;
}

function getTaskMessage(task: A2ATask): string {
  const userMessage = task.history?.find(message => message.role === 'user');
  const text = userMessage?.parts
    ?.map(part => part.text)
    .filter(Boolean)
    .join(' ') || '';
  return text.slice(0, 100);
}

function taskToHistoryEntry(task: A2ATask): TaskHistoryEntry {
  return {
    taskId: task.id,
    state: task.status?.state || 'unknown',
    mode: task.autonomous ? 'autonomous' : 'interactive',
    createdAt: parseTaskDate(task.status?.timestamp),
    message: getTaskMessage(task),
  };
}

function mergeTaskHistory(prev: TaskHistoryEntry[], tasks: A2ATask[]): TaskHistoryEntry[] {
  const byId = new Map(prev.map(entry => [entry.taskId, entry]));
  for (const task of tasks) {
    const next = taskToHistoryEntry(task);
    byId.set(task.id, { ...byId.get(task.id), ...next });
  }
  return Array.from(byId.values()).sort((a, b) => b.createdAt.getTime() - a.createdAt.getTime());
}

export function useA2ADebug(agent: Agent) {
  const namespace = agent.metadata.namespace || 'default';
  const serviceName = `agent-${agent.metadata.name}`;

  // Agent card state
  const [agentCard, setAgentCard] = useState<AgentCard | null>(null);
  const [isLoadingCard, setIsLoadingCard] = useState(false);
  const [cardError, setCardError] = useState<string | null>(null);

  // SendMessage state
  const [isSending, setIsSending] = useState(false);
  const [sendError, setSendError] = useState<string | null>(null);

  // Task viewer state
  const [currentTask, setCurrentTask] = useState<A2ATask | null>(null);
  const [isLoadingTask, setIsLoadingTask] = useState(false);
  const [taskError, setTaskError] = useState<string | null>(null);

  // Task history
  const [taskHistory, setTaskHistory] = useState<TaskHistoryEntry[]>([]);
  const [isLoadingTaskList, setIsLoadingTaskList] = useState(false);
  const [taskListError, setTaskListError] = useState<string | null>(null);

  // Auto-poll
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const [isPolling, setIsPolling] = useState(false);

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
    setIsPolling(false);
  }, []);

  useEffect(() => {
    return () => stopPolling();
  }, [stopPolling]);

  const fetchAgentCard = useCallback(async () => {
    setIsLoadingCard(true);
    setCardError(null);
    try {
      const card = await getAgentCard(serviceName, namespace);
      setAgentCard(card);
    } catch (err) {
      setCardError(err instanceof Error ? err.message : 'Failed to fetch agent card');
    } finally {
      setIsLoadingCard(false);
    }
  }, [serviceName, namespace]);

  const refreshTasks = useCallback(async () => {
    setIsLoadingTaskList(true);
    setTaskListError(null);
    try {
      const result = await listA2ATasks(serviceName, namespace);
      const tasks = result.tasks || [];
      setTaskHistory(prev => mergeTaskHistory(prev, tasks));
      setCurrentTask(prev => {
        if (!prev) return prev;
        return tasks.find(task => task.id === prev.id) || prev;
      });
      return tasks;
    } catch (err) {
      setTaskListError(err instanceof Error ? err.message : 'Failed to list tasks');
      return [];
    } finally {
      setIsLoadingTaskList(false);
    }
  }, [serviceName, namespace]);

  const startPolling = useCallback((taskId: string) => {
    stopPolling();
    setIsPolling(true);
    pollRef.current = setInterval(async () => {
      try {
        const task = await getA2ATask(serviceName, taskId, namespace);
        setCurrentTask(task);
        setTaskHistory(prev => mergeTaskHistory(prev, [task]));
        if (task.status && TERMINAL_STATES.includes(task.status.state)) {
          stopPolling();
        }
      } catch {
        // Silently continue polling on transient errors
      }
    }, 3000);
  }, [serviceName, namespace, stopPolling]);

  const sendMessage = useCallback(async (params: SendMessageParams) => {
    setIsSending(true);
    setSendError(null);
    try {
      const task = await sendA2AMessage(serviceName, params, namespace);
      setCurrentTask(task);
      setTaskHistory(prev => mergeTaskHistory(prev, [task]));

      // Start polling if task is not terminal
      if (task.status && !TERMINAL_STATES.includes(task.status.state)) {
        startPolling(task.id);
      }

      return task;
    } catch (err) {
      setSendError(err instanceof Error ? err.message : 'Failed to send message');
      return null;
    } finally {
      setIsSending(false);
    }
  }, [serviceName, namespace, startPolling]);

  const fetchTask = useCallback(async (taskId: string) => {
    setIsLoadingTask(true);
    setTaskError(null);
    try {
      const task = await getA2ATask(serviceName, taskId, namespace);
      setCurrentTask(task);
      setTaskHistory(prev => mergeTaskHistory(prev, [task]));
      return task;
    } catch (err) {
      setTaskError(err instanceof Error ? err.message : 'Failed to fetch task');
      return null;
    } finally {
      setIsLoadingTask(false);
    }
  }, [serviceName, namespace]);

  const cancelTask = useCallback(async (taskId: string) => {
    setIsLoadingTask(true);
    setTaskError(null);
    try {
      const task = await cancelA2ATask(serviceName, taskId, namespace);
      setCurrentTask(task);
      stopPolling();
      setTaskHistory(prev => mergeTaskHistory(prev, [task]));
      return task;
    } catch (err) {
      setTaskError(err instanceof Error ? err.message : 'Failed to cancel task');
      return null;
    } finally {
      setIsLoadingTask(false);
    }
  }, [serviceName, namespace, stopPolling]);

  const loadTaskFromHistory = useCallback((entry: TaskHistoryEntry) => {
    fetchTask(entry.taskId);
  }, [fetchTask]);

  return {
    // Agent card
    agentCard,
    isLoadingCard,
    cardError,
    fetchAgentCard,

    // Send message
    isSending,
    sendError,
    sendMessage,

    // Task viewer
    currentTask,
    isLoadingTask,
    taskError,
    fetchTask,
    cancelTask,

    // Polling
    isPolling,
    stopPolling,
    startPolling,

    // History
    taskHistory,
    isLoadingTaskList,
    taskListError,
    refreshTasks,
    loadTaskFromHistory,
  };
}
