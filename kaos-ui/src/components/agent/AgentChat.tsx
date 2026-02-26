import React, { useState, useRef, useEffect, useCallback } from 'react';
import { Send, Trash2, StopCircle, AlertCircle, RefreshCw, Hash, Copy, Check, Plus, Shuffle, Download } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { Input } from '@/components/ui/input';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Label } from '@/components/ui/label';
import { ChatMessage } from './ChatMessage';
import { ReasoningSteps } from './ReasoningSteps';
import { useAgentChat, ChatMessage as ChatMessageType } from '@/hooks/useAgentChat';
import { k8sClient } from '@/lib/kubernetes-client';
import type { Agent } from '@/types/kubernetes';

interface AgentChatProps {
  agent: Agent;
  sessionId: string;
  messages: ChatMessageType[];
  onSessionChange: (sessionId: string) => void;
  onMessagesChange: (messages: ChatMessageType[]) => void;
  onNewSession: () => void;
}

export function AgentChat({ 
  agent, 
  sessionId, 
  messages: externalMessages, 
  onSessionChange, 
  onMessagesChange,
  onNewSession 
}: AgentChatProps) {
  const [input, setInput] = useState('');
  const [copied, setCopied] = useState(false);
  const [seed, setSeed] = useState<string>('');
  const [isLoadingHistory, setIsLoadingHistory] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const scrollAreaRef = useRef<HTMLDivElement>(null);

  // Track if session is active (has messages)
  const hasActiveSession = sessionId !== '' && externalMessages.length > 0;

  const handleSessionIdReceived = useCallback((newSessionId: string) => {
    if (newSessionId && !sessionId) {
      onSessionChange(newSessionId);
      console.log('[AgentChat] Session ID received from server:', newSessionId);
    }
  }, [sessionId, onSessionChange]);
  
  // Generate a session ID on first message if none exists
  const getOrCreateSessionId = useCallback(() => {
    if (sessionId) {
      return sessionId;
    }
    const newId = `session-${Date.now()}-${Math.random().toString(36).substring(2, 9)}`;
    onSessionChange(newId);
    console.log('[AgentChat] Generated new session ID:', newId);
    return newId;
  }, [sessionId, onSessionChange]);

  const { messages: hookMessages, isLoading, error, sendMessage: sendChatMessage, clearMessages, stopGeneration } = useAgentChat({
    agentName: agent.metadata.name,
    namespace: agent.metadata.namespace || 'default',
    sessionId: sessionId || undefined,
    seed: seed ? parseInt(seed, 10) : undefined,
    onSessionIdReceived: handleSessionIdReceived,
    initialMessages: externalMessages,
  });

  // Fetch session history when a session ID is entered manually
  const fetchSessionHistory = useCallback(async (sid: string) => {
    if (!sid || !k8sClient.isConfigured()) return;
    
    setIsLoadingHistory(true);
    try {
      const serviceName = `agent-${agent.metadata.name}`;
      const namespace = agent.metadata.namespace || 'default';
      
      const response = await k8sClient.proxyServiceRequest(
        serviceName,
        `/memory/events?session_id=${encodeURIComponent(sid)}`,
        { method: 'GET' },
        namespace
      );
      
      if (response.ok) {
        const data = await response.json();
        const events = data.events || [];
        
        // Convert memory events to chat messages
        const historyMessages: ChatMessageType[] = events
          .filter((e: any) => e.role === 'user' || e.role === 'assistant')
          .map((e: any, idx: number) => ({
            id: e.id || `hist-${idx}`,
            role: e.role,
            content: typeof e.content === 'string' ? e.content : JSON.stringify(e.content),
            timestamp: e.timestamp ? new Date(e.timestamp) : new Date(),
            isStreaming: false,
          }));
        
        if (historyMessages.length > 0) {
          onMessagesChange(historyMessages);
          console.log(`[AgentChat] Loaded ${historyMessages.length} messages from session history`);
        }
      }
    } catch (err) {
      console.error('[AgentChat] Failed to fetch session history:', err);
    } finally {
      setIsLoadingHistory(false);
    }
  }, [agent.metadata.name, agent.metadata.namespace, onMessagesChange]);

  // Handler for session ID input blur - fetch history if session ID was entered
  const handleSessionIdBlur = useCallback(() => {
    if (sessionId && externalMessages.length === 0 && !hasActiveSession) {
      fetchSessionHistory(sessionId);
    }
  }, [sessionId, externalMessages.length, hasActiveSession, fetchSessionHistory]);
  
  // Sync hook messages back to parent for persistence (but render hookMessages directly for real-time streaming)
  useEffect(() => {
    if (hookMessages.length > 0 && hookMessages !== externalMessages) {
      onMessagesChange(hookMessages);
    }
  }, [hookMessages]);

  // Use hookMessages for rendering to get real-time streaming updates
  const displayMessages = hookMessages.length > 0 ? hookMessages : externalMessages;
  
  const sendMessage = useCallback((content: string) => {
    // Ensure we have a session ID before sending the first message
    getOrCreateSessionId();
    sendChatMessage(content);
  }, [getOrCreateSessionId, sendChatMessage]);

  // Auto-scroll to bottom when new messages arrive
  useEffect(() => {
    if (scrollAreaRef.current) {
      const scrollContainer = scrollAreaRef.current.querySelector('[data-radix-scroll-area-viewport]');
      if (scrollContainer) {
        scrollContainer.scrollTop = scrollContainer.scrollHeight;
      }
    }
  }, [displayMessages]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (input.trim() && !isLoading) {
      sendMessage(input);
      setInput('');
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit(e);
    }
  };

  const handleCopySessionId = () => {
    if (sessionId) {
      navigator.clipboard.writeText(sessionId);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  const handleNewSession = () => {
    clearMessages();
    onNewSession();
  };

  return (
    <div className="flex flex-col h-full bg-background rounded-lg border border-border overflow-hidden">
      {/* Session & Seed Header */}
      <div className="px-4 py-3 border-b border-border bg-muted/20 space-y-2">
        <div className="flex items-center gap-2">
          <Label htmlFor="session-id" className="text-xs text-muted-foreground flex items-center gap-1 shrink-0">
            <Hash className="h-3 w-3" />
            Session
          </Label>
          <div className="flex-1 flex items-center gap-2">
            <Input
              id="session-id"
              value={sessionId}
              onChange={(e) => !hasActiveSession && onSessionChange(e.target.value)}
              onBlur={handleSessionIdBlur}
              placeholder={hasActiveSession ? "Session active" : "Enter session ID or leave empty..."}
              className="h-7 text-xs font-mono bg-background"
              disabled={isLoading || hasActiveSession || isLoadingHistory}
              readOnly={hasActiveSession}
            />
            {sessionId && !hasActiveSession && externalMessages.length === 0 && (
              <Button
                variant="ghost"
                size="sm"
                onClick={() => fetchSessionHistory(sessionId)}
                className="h-7 w-7 p-0 shrink-0"
                title="Load session history"
                disabled={isLoadingHistory}
              >
                <Download className={`h-3 w-3 ${isLoadingHistory ? 'animate-pulse' : ''}`} />
              </Button>
            )}
            {sessionId && (
              <Button
                variant="ghost"
                size="sm"
                onClick={handleCopySessionId}
                className="h-7 w-7 p-0 shrink-0"
                title="Copy session ID"
              >
                {copied ? (
                  <Check className="h-3 w-3 text-green-500" />
                ) : (
                  <Copy className="h-3 w-3" />
                )}
              </Button>
            )}
            <Button
              variant="outline"
              size="sm"
              onClick={handleNewSession}
              className="h-7 shrink-0 text-xs"
              disabled={isLoading}
            >
              <Plus className="h-3 w-3 mr-1" />
              New
            </Button>
          </div>
        </div>
        
        {/* Seed input row */}
        <div className="flex items-center gap-2">
          <Label htmlFor="seed" className="text-xs text-muted-foreground flex items-center gap-1 shrink-0">
            <Shuffle className="h-3 w-3" />
            Seed
          </Label>
          <Input
            id="seed"
            type="number"
            value={seed}
            onChange={(e) => setSeed(e.target.value)}
            placeholder="Optional (for determinism)"
            className="h-7 text-xs font-mono bg-background max-w-[200px]"
            disabled={isLoading}
          />
          <span className="text-xs text-muted-foreground">
            {seed ? 'Deterministic mode' : 'Random responses'}
          </span>
        </div>
      </div>

      {/* Chat Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-border bg-muted/30">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium">Chat with {agent.metadata.name}</span>
          {agent.spec.model && (
            <span className="text-xs text-muted-foreground font-mono bg-muted px-1.5 py-0.5 rounded">
              {agent.spec.model}
            </span>
          )}
          {displayMessages.length > 0 && (
            <span className="text-xs text-muted-foreground">
              ({displayMessages.length} messages)
            </span>
          )}
        </div>
      </div>

      {/* Error Alert */}
      {error && (
        <Alert variant="destructive" className="m-4 mb-0">
          <AlertCircle className="h-4 w-4" />
          <AlertDescription>
            <div className="flex flex-col gap-2">
              <span className="font-medium">
                {error.includes('503') || error.includes('no endpoints') 
                  ? 'Agent Unavailable' 
                  : 'Connection Error'}
              </span>
              <span className="text-sm opacity-90">
                {error.includes('no endpoints') 
                  ? 'The agent pod is not ready. Check that the pod is running and healthy.'
                  : error}
              </span>
              <div className="flex gap-2 mt-1">
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => displayMessages.length > 1 && sendMessage(displayMessages[displayMessages.length - 2]?.content || '')}
                  className="h-7 text-xs"
                  disabled={displayMessages.length < 2}
                >
                  <RefreshCw className="h-3 w-3 mr-1" />
                  Retry
                </Button>
              </div>
            </div>
          </AlertDescription>
        </Alert>
      )}

      {/* Messages */}
      <ScrollArea ref={scrollAreaRef} className="flex-1">
        {displayMessages.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full py-12 px-4 text-center">
            <div className="h-16 w-16 rounded-full bg-agent/10 flex items-center justify-center mb-4">
              <span className="text-3xl">🤖</span>
            </div>
            <h3 className="text-lg font-medium text-foreground mb-2">
              Start a conversation
            </h3>
            <p className="text-sm text-muted-foreground max-w-sm">
              Send a message to {agent.metadata.name} to begin chatting.
              The agent uses the <span className="font-mono text-agent">{agent.spec.modelAPI}</span> model.
            </p>
          </div>
        ) : (
          <div className="divide-y divide-border/50">
            {displayMessages.map((message) => (
              <div key={message.id}>
                {message.role === 'assistant' && message.progressSteps && message.progressSteps.length > 0 && (
                  <ReasoningSteps
                    steps={message.progressSteps}
                    isActive={!!message.isStreaming && !message.content}
                  />
                )}
                <ChatMessage
                  role={message.role}
                  content={message.content}
                  isStreaming={message.isStreaming}
                  timestamp={message.timestamp}
                />
              </div>
            ))}
          </div>
        )}
      </ScrollArea>

      {/* Input Area */}
      <form onSubmit={handleSubmit} className="p-4 border-t border-border bg-muted/20">
        <div className="flex gap-2">
          <Textarea
            ref={textareaRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Type a message... (Shift+Enter for new line)"
            className="min-h-[44px] max-h-32 resize-none bg-background"
            disabled={isLoading}
            rows={1}
          />
          {isLoading ? (
            <Button
              type="button"
              onClick={stopGeneration}
              variant="destructive"
              size="icon"
              className="h-11 w-11 shrink-0"
            >
              <StopCircle className="h-5 w-5" />
            </Button>
          ) : (
            <Button
              type="submit"
              disabled={!input.trim()}
              size="icon"
              className="h-11 w-11 shrink-0 bg-agent hover:bg-agent/90"
            >
              <Send className="h-5 w-5" />
            </Button>
          )}
        </div>
        <p className="text-xs text-muted-foreground mt-2">
          Press Enter to send, Shift+Enter for new line
        </p>
      </form>
    </div>
  );
}
