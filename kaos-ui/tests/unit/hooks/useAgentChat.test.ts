import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';

// Mock streamAgentChat
vi.mock('@/lib/agent-client', () => ({
  streamAgentChat: vi.fn(),
}));

import { useAgentChat } from '@/hooks/useAgentChat';
import { streamAgentChat } from '@/lib/agent-client';

const mockedStreamAgentChat = vi.mocked(streamAgentChat);

describe('useAgentChat', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('initializes with empty messages and not loading', () => {
    const { result } = renderHook(() =>
      useAgentChat({ agentName: 'test', namespace: 'default' }),
    );
    expect(result.current.messages).toEqual([]);
    expect(result.current.isLoading).toBe(false);
    expect(result.current.error).toBeNull();
  });

  it('initializes with provided initialMessages', () => {
    const initial = [
      { id: '1', role: 'user' as const, content: 'hello', timestamp: new Date() },
    ];
    const { result } = renderHook(() =>
      useAgentChat({ agentName: 'test', namespace: 'default', initialMessages: initial }),
    );
    expect(result.current.messages).toHaveLength(1);
    expect(result.current.messages[0].content).toBe('hello');
  });

  it('sends a message and creates user + assistant message placeholders', async () => {
    // Simulate a streaming call that immediately calls onDone
    mockedStreamAgentChat.mockImplementation(async (_service, _messages, opts) => {
      opts.onChunk('Response text');
      opts.onDone({ sessionId: 'sess-1' });
    });

    const { result } = renderHook(() =>
      useAgentChat({ agentName: 'test', namespace: 'default' }),
    );

    await act(async () => {
      await result.current.sendMessage('Hello agent');
    });

    // Should have user + assistant messages
    expect(result.current.messages).toHaveLength(2);
    expect(result.current.messages[0].role).toBe('user');
    expect(result.current.messages[0].content).toBe('Hello agent');
    expect(result.current.messages[1].role).toBe('assistant');
    expect(result.current.messages[1].content).toBe('Response text');
    expect(result.current.isLoading).toBe(false);
  });

  it('does not send empty messages', async () => {
    const { result } = renderHook(() =>
      useAgentChat({ agentName: 'test', namespace: 'default' }),
    );

    await act(async () => {
      await result.current.sendMessage('   ');
    });

    expect(result.current.messages).toEqual([]);
    expect(mockedStreamAgentChat).not.toHaveBeenCalled();
  });

  it('handles stream errors', async () => {
    mockedStreamAgentChat.mockImplementation(async (_service, _messages, opts) => {
      opts.onError(new Error('Connection failed'));
    });

    const { result } = renderHook(() =>
      useAgentChat({ agentName: 'test', namespace: 'default' }),
    );

    await act(async () => {
      await result.current.sendMessage('Hello');
    });

    expect(result.current.error).toBe('Connection failed');
    expect(result.current.isLoading).toBe(false);
  });

  it('clears messages', async () => {
    mockedStreamAgentChat.mockImplementation(async (_s, _m, opts) => {
      opts.onChunk('hi');
      opts.onDone({});
    });

    const { result } = renderHook(() =>
      useAgentChat({ agentName: 'test', namespace: 'default' }),
    );

    await act(async () => {
      await result.current.sendMessage('Hello');
    });
    expect(result.current.messages.length).toBeGreaterThan(0);

    act(() => {
      result.current.clearMessages();
    });
    expect(result.current.messages).toEqual([]);
    expect(result.current.error).toBeNull();
  });

  it('resolves service name from agentName', async () => {
    mockedStreamAgentChat.mockImplementation(async (_s, _m, opts) => {
      opts.onDone({});
    });

    const { result } = renderHook(() =>
      useAgentChat({ agentName: 'my-agent', namespace: 'ns1' }),
    );

    await act(async () => {
      await result.current.sendMessage('test');
    });

    expect(mockedStreamAgentChat).toHaveBeenCalledWith(
      'agent-my-agent',
      expect.any(Array),
      expect.objectContaining({ namespace: 'ns1' }),
    );
  });

  it('uses custom serviceName when provided', async () => {
    mockedStreamAgentChat.mockImplementation(async (_s, _m, opts) => {
      opts.onDone({});
    });

    const { result } = renderHook(() =>
      useAgentChat({ agentName: 'my-agent', namespace: 'ns1', serviceName: 'custom-svc' }),
    );

    await act(async () => {
      await result.current.sendMessage('test');
    });

    expect(mockedStreamAgentChat).toHaveBeenCalledWith(
      'custom-svc',
      expect.any(Array),
      expect.any(Object),
    );
  });
});
