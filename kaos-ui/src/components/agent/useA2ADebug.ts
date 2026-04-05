import { useState, useCallback, useRef, useEffect } from 'react';
import { getAgentCard, sendA2AMessage, getA2ATask, cancelA2ATask } from '@/lib/k8s/a2a';
import type { Agent } from '@/types/kubernetes';
import type { AgentCard, A2ATask, SendMessageParams } from '@/types/a2a';

export interface TaskHistoryEntry {
  taskId: string;
  state: string;
  mode: string;
  createdAt: Date;
  message: string;
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

  const startPolling = useCallback((taskId: string) => {
    stopPolling();
    setIsPolling(true);
    pollRef.current = setInterval(async () => {
      try {
        const task = await getA2ATask(serviceName, taskId, namespace);
        setCurrentTask(task);
        setTaskHistory(prev => prev.map(entry =>
          entry.taskId === taskId ? { ...entry, state: task.status?.state || entry.state } : entry
        ));
        const terminalStates = ['completed', 'failed', 'canceled'];
        if (task.status && terminalStates.includes(task.status.state)) {
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
      // Add to history
      const messageText = params.message?.parts?.[0]?.text || '';
      setTaskHistory(prev => [{
        taskId: task.id,
        state: task.status?.state || 'unknown',
        mode: params.configuration?.mode === 'autonomous' ? 'autonomous' : 'interactive',
        createdAt: new Date(),
        message: messageText.slice(0, 100),
      }, ...prev]);

      // Start polling if task is not terminal
      const terminalStates = ['completed', 'failed', 'canceled'];
      if (task.status && !terminalStates.includes(task.status.state)) {
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
      // Update history entry
      setTaskHistory(prev => prev.map(entry =>
        entry.taskId === taskId ? { ...entry, state: task.status?.state || entry.state } : entry
      ));
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
      // Update history
      setTaskHistory(prev => prev.map(entry =>
        entry.taskId === taskId ? { ...entry, state: 'canceled' } : entry
      ));
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
    loadTaskFromHistory,
  };
}
