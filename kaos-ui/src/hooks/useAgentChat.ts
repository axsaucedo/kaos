/**
 * Hook for managing chat state and streaming with an Agent
 * 
 * Supports:
 * - Two-phase agentic loop (Phase 1: progress events, Phase 2: streamed response)
 * - Progress/reasoning step display during tool execution
 * - Background request survival across tab switches
 * - Session history recovery
 */

import { useState, useCallback, useRef, useEffect } from 'react';
import { flushSync } from 'react-dom';
import { streamAgentChat } from '@/lib/agent-client';
import type { ProgressStep } from '@/components/agent/ReasoningSteps';

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  timestamp: Date;
  isStreaming?: boolean;
  progressSteps?: ProgressStep[];
}

interface UseAgentChatOptions {
  agentName: string;
  namespace: string;
  serviceName?: string;
  model?: string;
  temperature?: number;
  sessionId?: string;
  seed?: number;
  onSessionIdReceived?: (sessionId: string) => void;
  initialMessages?: ChatMessage[];
}

export function useAgentChat(options: UseAgentChatOptions) {
  const { agentName, namespace, serviceName, model, temperature, sessionId, seed, onSessionIdReceived, initialMessages = [] } = options;
  
  const [messages, setMessages] = useState<ChatMessage[]>(initialMessages);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abortControllerRef = useRef<AbortController | null>(null);
  
  // Sync with external messages when they change
  useEffect(() => {
    if (initialMessages.length > 0 && messages.length === 0) {
      setMessages(initialMessages);
    }
  }, [initialMessages]);

  const resolvedServiceName = serviceName || `agent-${agentName}`;

  const generateId = () => `msg-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;

  const sendMessage = useCallback(async (content: string) => {
    if (!content.trim() || isLoading) return;

    setError(null);
    setIsLoading(true);

    const userMessage: ChatMessage = {
      id: generateId(),
      role: 'user',
      content: content.trim(),
      timestamp: new Date(),
    };

    const assistantMessage: ChatMessage = {
      id: generateId(),
      role: 'assistant',
      content: '',
      timestamp: new Date(),
      isStreaming: true,
      progressSteps: [],
    };

    setMessages(prev => [...prev, userMessage, assistantMessage]);

    const apiMessages = [...messages, userMessage].map(m => ({
      role: m.role,
      content: m.content,
    }));

    // Create abort controller for this request
    const abortController = new AbortController();
    abortControllerRef.current = abortController;

    try {
      console.log(`[useAgentChat] Sending to service: ${resolvedServiceName} in namespace: ${namespace} (stream=true)`);
      
      await streamAgentChat(
        resolvedServiceName,
        apiMessages,
        {
          namespace,
          model,
          temperature,
          sessionId,
          seed,
          stream: true,
          signal: abortController.signal,
          onProgress: (progress) => {
            console.log(`[useAgentChat] Progress:`, progress);
            flushSync(() => {
              setMessages(prev => {
                const updated = [...prev];
                const lastMessage = updated[updated.length - 1];
                if (lastMessage.role === 'assistant') {
                  const existingSteps = (lastMessage.progressSteps || []).map(s => ({ ...s, completed: true } as ProgressStep));
                  lastMessage.progressSteps = [...existingSteps, { ...progress, type: 'progress' as const }];
                }
                return updated;
              });
            });
          },
          onChunk: (chunk) => {
            flushSync(() => {
              setMessages(prev => {
                const updated = [...prev];
                const lastMessage = updated[updated.length - 1];
                if (lastMessage.role === 'assistant') {
                  lastMessage.content += chunk;
                }
                return updated;
              });
            });
          },
          onDone: (metadata) => {
            console.log(`[useAgentChat] Stream complete`, metadata);
            if (metadata?.sessionId && onSessionIdReceived) {
              onSessionIdReceived(metadata.sessionId);
            }
            setMessages(prev => {
              const updated = [...prev];
              const lastMessage = updated[updated.length - 1];
              if (lastMessage.role === 'assistant') {
                lastMessage.isStreaming = false;
                lastMessage.content = lastMessage.content.trim();
                if (lastMessage.progressSteps) {
                  lastMessage.progressSteps = lastMessage.progressSteps.map(s => ({ ...s, completed: true }));
                }
              }
              return updated;
            });
            setIsLoading(false);
            abortControllerRef.current = null;
          },
          onError: (err) => {
            console.error('[useAgentChat] Stream error:', err);
            setError(err.message);
            setMessages(prev => {
              const updated = [...prev];
              const lastMessage = updated[updated.length - 1];
              if (lastMessage.role === 'assistant') {
                lastMessage.isStreaming = false;
                lastMessage.content = lastMessage.content || 'Error: Failed to get response';
              }
              return updated;
            });
            setIsLoading(false);
            abortControllerRef.current = null;
          },
        }
      );
    } catch (err) {
      if (abortController.signal.aborted) return;
      console.error('[useAgentChat] Error:', err);
      setError(err instanceof Error ? err.message : 'Unknown error');
      setIsLoading(false);
    }
  }, [messages, isLoading, resolvedServiceName, namespace, model, temperature, sessionId, seed, onSessionIdReceived]);

  const clearMessages = useCallback(() => {
    setMessages([]);
    setError(null);
  }, []);

  const stopGeneration = useCallback(() => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
    setIsLoading(false);
    setMessages(prev => {
      const updated = [...prev];
      const lastMessage = updated[updated.length - 1];
      if (lastMessage?.role === 'assistant' && lastMessage.isStreaming) {
        lastMessage.isStreaming = false;
      }
      return updated;
    });
  }, []);

  return {
    messages,
    isLoading,
    error,
    sendMessage,
    clearMessages,
    stopGeneration,
  };
}
