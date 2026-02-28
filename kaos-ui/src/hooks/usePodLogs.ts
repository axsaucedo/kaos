import { useState, useEffect, useRef, useCallback } from 'react';
import { k8sClient } from '@/lib/kubernetes-client';

interface UsePodLogsOptions {
  namespace: string | undefined;
  podName: string | undefined;
  containerName: string;
  active: boolean;
}

export function usePodLogs({ namespace, podName, containerName, active }: UsePodLogsOptions) {
  const [logs, setLogs] = useState<string>('');
  const [logsLoading, setLogsLoading] = useState(false);
  const [logsError, setLogsError] = useState<string | null>(null);
  const [tailLines, setTailLines] = useState<number>(200);
  const [autoRefresh, setAutoRefresh] = useState(true);
  const scrollRef = useRef<HTMLDivElement>(null);

  const fetchLogs = useCallback(async () => {
    if (!namespace || !podName) return;

    setLogsLoading(true);
    setLogsError(null);

    try {
      const logContent = await k8sClient.getPodLogs(podName, namespace, {
        container: containerName || undefined,
        tailLines,
      });
      setLogs(logContent);

      if (scrollRef.current) {
        scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
      }
    } catch (err) {
      setLogsError(err instanceof Error ? err.message : 'Failed to fetch logs');
      setLogs('');
    } finally {
      setLogsLoading(false);
    }
  }, [namespace, podName, containerName, tailLines]);

  // Fetch logs when active
  useEffect(() => {
    if (active) {
      fetchLogs();
    }
  }, [active, fetchLogs]);

  // Auto-refresh logs
  useEffect(() => {
    if (!autoRefresh || !active) return;

    const interval = setInterval(fetchLogs, 1000);
    return () => clearInterval(interval);
  }, [autoRefresh, active, fetchLogs]);

  const handleDownload = () => {
    const blob = new Blob([logs], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${podName}-${containerName || 'logs'}.txt`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return {
    logs,
    logsLoading,
    logsError,
    tailLines,
    setTailLines,
    autoRefresh,
    setAutoRefresh,
    scrollRef,
    fetchLogs,
    handleDownload,
  };
}
