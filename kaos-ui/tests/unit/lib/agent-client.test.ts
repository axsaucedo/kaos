import { describe, it, expect, vi, beforeEach } from 'vitest';

/**
 * Tests for agent-client.ts SSE stream parsing logic.
 *
 * The streamAgentChat function depends on fetch and k8sClient,
 * so we mock those to test the SSE parsing and callback behavior.
 */

// Mock kubernetes-client before importing agent-client
vi.mock('@/lib/kubernetes-client', () => ({
  k8sClient: {
    getConfig: () => ({
      baseUrl: 'http://localhost:8010',
      namespace: 'default',
    }),
  },
}));

import { streamAgentChat } from '@/lib/agent-client';

function createSSEStream(lines: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  const data = lines.join('\n') + '\n';
  return new ReadableStream({
    start(controller) {
      controller.enqueue(encoder.encode(data));
      controller.close();
    },
  });
}

function mockFetch(stream: ReadableStream<Uint8Array>, status = 200) {
  return vi.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    body: { getReader: () => stream.getReader() },
    text: () => Promise.resolve('error'),
  });
}

describe('streamAgentChat', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('parses SSE chunks and calls onChunk for text content', async () => {
    const chunks: string[] = [];
    const sseLines = [
      'data: {"choices":[{"delta":{"content":"Hello"}}]}',
      'data: {"choices":[{"delta":{"content":" world"}}]}',
      'data: [DONE]',
    ];
    const stream = createSSEStream(sseLines);
    vi.stubGlobal('fetch', mockFetch(stream));

    const onDone = vi.fn();
    await streamAgentChat('agent-test', [{ role: 'user', content: 'hi' }], {
      onChunk: (c) => chunks.push(c),
      onDone,
      onError: vi.fn(),
    });

    expect(chunks).toEqual(['Hello', ' world']);
    expect(onDone).toHaveBeenCalledTimes(1);
  });

  it('detects progress blocks and calls onProgress', async () => {
    const progressEvents: { type: string; step: number; max_steps: number; action: string; target: string }[] = [];
    const chunks: string[] = [];
    const progressJson = JSON.stringify({
      type: 'progress',
      step: 1,
      max_steps: 3,
      action: 'tool_call',
      target: 'echo',
    });
    const sseLines = [
      `data: {"choices":[{"delta":{"content":"${progressJson.replace(/"/g, '\\"')}"}}]}`,
      'data: {"choices":[{"delta":{"content":"Result text"}}]}',
      'data: [DONE]',
    ];
    const stream = createSSEStream(sseLines);
    vi.stubGlobal('fetch', mockFetch(stream));

    await streamAgentChat('agent-test', [{ role: 'user', content: 'hi' }], {
      onChunk: (c) => chunks.push(c),
      onProgress: (p) => progressEvents.push(p),
      onDone: vi.fn(),
      onError: vi.fn(),
    });

    expect(progressEvents).toHaveLength(1);
    expect(progressEvents[0].type).toBe('progress');
    expect(progressEvents[0].action).toBe('tool_call');
    expect(chunks).toEqual(['Result text']);
  });

  it('extracts session_id from SSE data', async () => {
    const sseLines = [
      'data: {"session_id":"sess-123","choices":[{"delta":{"content":"hi"}}]}',
      'data: [DONE]',
    ];
    const stream = createSSEStream(sseLines);
    vi.stubGlobal('fetch', mockFetch(stream));

    const onDone = vi.fn();
    await streamAgentChat('agent-test', [{ role: 'user', content: 'hi' }], {
      onChunk: vi.fn(),
      onDone,
      onError: vi.fn(),
    });

    expect(onDone).toHaveBeenCalledWith({ sessionId: 'sess-123' });
  });

  it('calls onError for non-ok HTTP responses', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: false,
        status: 500,
        text: () => Promise.resolve('Internal Server Error'),
      }),
    );

    const onError = vi.fn();
    await streamAgentChat('agent-test', [{ role: 'user', content: 'hi' }], {
      onChunk: vi.fn(),
      onDone: vi.fn(),
      onError,
    });

    expect(onError).toHaveBeenCalledTimes(1);
    expect(onError.mock.calls[0][0].message).toContain('500');
  });

  it('calls onError when fetch throws a network error', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockRejectedValue(new Error('Network request failed')),
    );

    const onError = vi.fn();
    await streamAgentChat('agent-test', [{ role: 'user', content: 'hi' }], {
      onChunk: vi.fn(),
      onDone: vi.fn(),
      onError,
    });

    expect(onError).toHaveBeenCalledTimes(1);
    expect(onError.mock.calls[0][0].message).toContain('Network request failed');
  });

  it('handles non-streaming mode', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: () =>
          Promise.resolve({
            session_id: 'sess-456',
            choices: [{ message: { content: 'Non-stream response' } }],
          }),
      }),
    );

    const chunks: string[] = [];
    const onDone = vi.fn();
    await streamAgentChat('agent-test', [{ role: 'user', content: 'hi' }], {
      stream: false,
      onChunk: (c) => chunks.push(c),
      onDone,
      onError: vi.fn(),
    });

    expect(chunks).toEqual(['Non-stream response']);
    expect(onDone).toHaveBeenCalledWith({ sessionId: 'sess-456' });
  });

  it('skips comment lines and empty lines in SSE stream', async () => {
    const chunks: string[] = [];
    const sseLines = [
      ': this is a comment',
      '',
      'data: {"choices":[{"delta":{"content":"only-text"}}]}',
      '',
      'data: [DONE]',
    ];
    const stream = createSSEStream(sseLines);
    vi.stubGlobal('fetch', mockFetch(stream));

    await streamAgentChat('agent-test', [{ role: 'user', content: 'hi' }], {
      onChunk: (c) => chunks.push(c),
      onDone: vi.fn(),
      onError: vi.fn(),
    });

    expect(chunks).toEqual(['only-text']);
  });
});
