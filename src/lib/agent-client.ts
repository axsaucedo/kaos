/**
 * Dedicated Agent Chat Client
 * 
 * Handles SSE streaming for agent chat completions via the K8s service proxy.
 * Separated from the general-purpose K8s client to isolate streaming concerns
 * and progress block parsing.
 */

import { k8sClient } from './kubernetes-client';

export interface StreamAgentChatOptions {
  namespace?: string;
  model?: string;
  temperature?: number;
  maxTokens?: number;
  sessionId?: string;
  seed?: number;
  stream?: boolean;
  signal?: AbortSignal;
  onChunk: (content: string) => void;
  onProgress?: (progress: { type: string; step: number; max_steps: number; action: string; target: string }) => void;
  onDone: (metadata?: { sessionId?: string }) => void;
  onError: (error: Error) => void;
}

/**
 * Stream a chat completion request to an agent service via the K8s API proxy.
 * 
 * The agent uses a two-phase agentic loop:
 * - Phase 1: Progress events (tool_call/delegate actions as JSON in delta.content)
 * - Phase 2: Streamed final response text in delta.content
 */
export async function streamAgentChat(
  serviceName: string,
  messages: { role: string; content: string }[],
  options: StreamAgentChatOptions
): Promise<void> {
  const {
    namespace,
    model = 'default',
    temperature = 0.7,
    maxTokens,
    sessionId,
    seed,
    stream = true,
    signal,
    onChunk,
    onProgress,
    onDone,
    onError,
  } = options;

  const config = k8sClient.getConfig();
  if (!config.baseUrl) {
    onError(new Error('Kubernetes API not configured. Please set the base URL.'));
    return;
  }

  const ns = namespace || config.namespace;
  const proxyUrl = `${config.baseUrl}/api/v1/namespaces/${ns}/services/${serviceName}:8000/proxy/v1/chat/completions`;

  const body = JSON.stringify({
    model,
    messages,
    stream,
    temperature,
    ...(maxTokens && { max_tokens: maxTokens }),
    ...(sessionId && { session_id: sessionId }),
    ...(seed !== undefined && { seed }),
  });

  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    'X-Requested-With': 'XMLHttpRequest',
    'bypass-tunnel-reminder': '1',
  };

  if (stream) {
    headers['Accept'] = 'text/event-stream';
    headers['Cache-Control'] = 'no-cache';
    headers['Connection'] = 'keep-alive';
  }

  try {
    console.log(`[agentClient] POST ${proxyUrl} (stream=${stream})`);

    const response = await fetch(proxyUrl, {
      method: 'POST',
      headers,
      body,
      signal,
    });

    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(`Chat API error ${response.status}: ${errorText}`);
    }

    if (!stream) {
      const data = await response.json();
      console.log('[agentClient] Non-streaming response:', JSON.stringify(data).substring(0, 500));
      const content = data.choices?.[0]?.message?.content;
      if (content) {
        onChunk(content);
      }
      onDone({ sessionId: data.session_id });
      return;
    }

    // Streaming SSE mode
    const reader = response.body?.getReader();
    if (!reader) {
      throw new Error('No response body for streaming');
    }

    const decoder = new TextDecoder();
    let buffer = '';
    let receivedSessionId: string | undefined;

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';

      for (const line of lines) {
        const trimmed = line.trim();
        if (!trimmed || trimmed.startsWith(':')) continue;

        if (trimmed.startsWith('data: ')) {
          const data = trimmed.slice(6);
          if (data === '[DONE]') {
            onDone({ sessionId: receivedSessionId });
            return;
          }

          try {
            const parsed = JSON.parse(data);

            if (parsed.session_id) {
              receivedSessionId = parsed.session_id;
            }

            const content = parsed.choices?.[0]?.delta?.content;
            if (content !== undefined && content !== null && content !== '') {
              const trimmedContent = content.trim();

              // Detect progress blocks (stringified JSON with type=progress)
              if (trimmedContent.startsWith('{')) {
                try {
                  const progressData = JSON.parse(trimmedContent);
                  if (progressData?.type === 'progress' && onProgress) {
                    console.log('[agentClient] Progress block:', progressData);
                    onProgress(progressData);
                    continue;
                  }
                } catch {
                  // Not valid JSON progress — treat as regular content
                }
              }

              onChunk(content);
            }
          } catch {
            console.warn('[agentClient] Skipping unparseable SSE line:', trimmed);
          }
        }
      }
    }

    // Stream ended without [DONE]
    onDone({ sessionId: receivedSessionId });
  } catch (error) {
    if (signal?.aborted) {
      console.log('[agentClient] Stream aborted by user');
      return;
    }
    console.error('[agentClient] chatCompletion error:', error);
    onError(error instanceof Error ? error : new Error(String(error)));
  }
}
