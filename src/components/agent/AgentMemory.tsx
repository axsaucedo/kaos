import React, { useState, useEffect, useCallback } from 'react';
import { Brain, Clock, RefreshCw, MessageSquare, User, Bot, Wrench, AlertCircle, Users, AlertTriangle, CheckCircle2 } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Skeleton } from '@/components/ui/skeleton';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { k8sClient } from '@/lib/kubernetes-client';
import type { Agent } from '@/types/kubernetes';

interface MemoryEvent {
  id: string;
  type: string;
  content?: string | Record<string, unknown>;
  timestamp?: string;
  session_id?: string;
  metadata?: Record<string, unknown>;
}

/**
 * Normalize a raw memory event from the backend API.
 * The backend returns event_type/event_id but the UI uses type/id.
 */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
function normalizeEvent(raw: any): MemoryEvent {
  return {
    id: raw.event_id || raw.id,
    type: raw.event_type || raw.type || 'unknown',
    content: raw.content,
    timestamp: raw.timestamp,
    session_id: raw.session_id,
    metadata: raw.metadata,
  };
}

interface MemorySession {
  id: string;
  created_at?: string;
  event_count?: number;
}

interface AgentMemoryProps {
  agent: Agent;
}

export function AgentMemory({ agent }: AgentMemoryProps) {
  const [events, setEvents] = useState<MemoryEvent[]>([]);
  const [sessions, setSessions] = useState<string[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null);

  // Check if memory is enabled for this agent
  const isMemoryEnabled = agent.spec.config?.memory?.enabled !== false;

  const serviceName = `agent-${agent.metadata.name}`;
  const namespace = agent.metadata.namespace || 'default';

  const fetchMemory = useCallback(async () => {
    if (!k8sClient.isConfigured()) {
      setError('Kubernetes client not configured');
      return;
    }

    setIsLoading(true);
    setError(null);

    try {
      // Fetch both events and sessions in parallel
      const [eventsResponse, sessionsResponse] = await Promise.all([
        k8sClient.proxyServiceRequest(serviceName, '/memory/events', {
          method: 'GET',
        }, namespace),
        k8sClient.proxyServiceRequest(serviceName, '/memory/sessions', {
          method: 'GET',
        }, namespace),
      ]);

      if (!eventsResponse.ok) {
        const errorText = await eventsResponse.text();
        throw new Error(`Events fetch failed: ${eventsResponse.status} - ${errorText}`);
      }

      if (!sessionsResponse.ok) {
        const errorText = await sessionsResponse.text();
        throw new Error(`Sessions fetch failed: ${sessionsResponse.status} - ${errorText}`);
      }

      const eventsData = await eventsResponse.json();
      const sessionsData = await sessionsResponse.json();

      setEvents((eventsData.events || []).map(normalizeEvent));
      setSessions(sessionsData.sessions || []);
      setLastRefresh(new Date());
    } catch (err) {
      console.error('[AgentMemory] Fetch error:', err);
      const errorMessage = err instanceof Error ? err.message : 'Failed to fetch memory';
      
      // Check for common issues
      if (errorMessage.includes('404') || errorMessage.includes('not found')) {
        setError('Memory endpoints not available. Ensure AGENT_DEBUG_MEMORY_ENDPOINTS=true is set.');
      } else if (errorMessage.includes('503') || errorMessage.includes('no endpoints')) {
        setError('Agent service unavailable. Check that the pod is running.');
      } else {
        setError(errorMessage);
      }
    } finally {
      setIsLoading(false);
    }
  }, [k8sClient, serviceName, namespace]);

  // Auto-fetch on mount, but only if memory is enabled
  useEffect(() => {
    if (isMemoryEnabled) {
      fetchMemory();
    }
  }, [fetchMemory, isMemoryEnabled]);

  const getEventIcon = (event: MemoryEvent) => {
    switch (event.type) {
      case 'user_message':
        return <User className="h-4 w-4 text-blue-500" />;
      case 'agent_response':
        return <Bot className="h-4 w-4 text-agent" />;
      case 'tool_call':
      case 'tool_result':
        return <Wrench className="h-4 w-4 text-mcpserver" />;
      case 'tool_error':
      case 'delegation_error':
      case 'error':
        return <AlertCircle className="h-4 w-4 text-destructive" />;
      case 'delegation_request':
      case 'delegation_response':
      case 'task_delegation_received':
        return <Users className="h-4 w-4 text-purple-500" />;
      case 'format_warning':
        return <AlertTriangle className="h-4 w-4 text-yellow-500" />;
      default:
        return <MessageSquare className="h-4 w-4 text-muted-foreground" />;
    }
  };

  const getEventBadge = (event: MemoryEvent) => {
    switch (event.type) {
      case 'user_message':
        return <Badge variant="outline" className="text-xs">User</Badge>;
      case 'agent_response':
        return <Badge variant="agent" className="text-xs">Agent</Badge>;
      case 'tool_call':
        return <Badge variant="mcpserver" className="text-xs">Tool Call</Badge>;
      case 'tool_result':
        return <Badge variant="outline" className="text-xs border-green-500/50 text-green-500">Tool Result</Badge>;
      case 'tool_error':
        return <Badge variant="destructive" className="text-xs">Tool Error</Badge>;
      case 'delegation_request':
        return <Badge variant="outline" className="text-xs border-purple-500/50 text-purple-500">Delegation</Badge>;
      case 'delegation_response':
        return <Badge variant="outline" className="text-xs border-purple-500/50 text-purple-500">Delegation Result</Badge>;
      case 'delegation_error':
        return <Badge variant="destructive" className="text-xs">Delegation Error</Badge>;
      case 'task_delegation_received':
        return <Badge variant="outline" className="text-xs border-blue-500/50 text-blue-500">Task Received</Badge>;
      case 'format_warning':
        return <Badge variant="outline" className="text-xs border-yellow-500/50 text-yellow-500">Warning</Badge>;
      case 'error':
        return <Badge variant="destructive" className="text-xs">Error</Badge>;
      default:
        return <Badge variant="secondary" className="text-xs">{event.type}</Badge>;
    }
  };

  const formatTimestamp = (timestamp?: string) => {
    if (!timestamp) return '';
    try {
      return new Date(timestamp).toLocaleString();
    } catch {
      return timestamp;
    }
  };

  // Safely convert content to string for rendering
  const safeContentToString = (content: unknown): string => {
    if (content === null || content === undefined) {
      return '';
    }
    if (typeof content === 'string') {
      return content;
    }
    if (typeof content === 'object') {
      try {
        return JSON.stringify(content, null, 2);
      } catch {
        return '[Object]';
      }
    }
    return String(content);
  };

  // Render structured content based on event type
  const renderEventContent = (event: MemoryEvent) => {
    const content = event.content;
    if (!content) return null;

    // Structured content for tool/delegation events
    if (typeof content === 'object') {
      const obj = content as Record<string, unknown>;

      // tool_call: {tool, arguments}
      if (event.type === 'tool_call' && obj.tool) {
        return (
          <div className="space-y-1">
            <div className="flex items-center gap-2">
              <Wrench className="h-3 w-3" />
              <span className="text-xs font-mono font-medium">{String(obj.tool)}</span>
            </div>
            {obj.arguments && (
              <pre className="text-xs bg-background/50 p-2 rounded overflow-auto max-h-24">
                {JSON.stringify(obj.arguments, null, 2)}
              </pre>
            )}
          </div>
        );
      }

      // tool_result: {tool, result}
      if (event.type === 'tool_result' && obj.tool) {
        return (
          <div className="space-y-1">
            <div className="flex items-center gap-2">
              <CheckCircle2 className="h-3 w-3 text-green-500" />
              <span className="text-xs font-mono font-medium">{String(obj.tool)}</span>
            </div>
            {obj.result !== undefined && (
              <pre className="text-xs bg-background/50 p-2 rounded overflow-auto max-h-24 text-muted-foreground">
                → {typeof obj.result === 'string' ? obj.result : JSON.stringify(obj.result, null, 2)}
              </pre>
            )}
          </div>
        );
      }

      // tool_error: {tool, error}
      if (event.type === 'tool_error' && obj.tool) {
        return (
          <div className="space-y-1">
            <div className="flex items-center gap-2">
              <AlertCircle className="h-3 w-3 text-destructive" />
              <span className="text-xs font-mono font-medium">{String(obj.tool)}</span>
            </div>
            <pre className="text-xs bg-destructive/10 p-2 rounded overflow-auto max-h-24 text-destructive">
              {String(obj.error || 'Unknown error')}
            </pre>
          </div>
        );
      }

      // delegation_request: {agent, task}
      if (event.type === 'delegation_request' && obj.agent) {
        return (
          <div className="space-y-1">
            <div className="flex items-center gap-2">
              <Users className="h-3 w-3 text-purple-500" />
              <span className="text-xs font-mono font-medium">{String(obj.agent)}</span>
            </div>
            {obj.task && (
              <p className="text-xs text-muted-foreground">{String(obj.task)}</p>
            )}
          </div>
        );
      }

      // delegation_response: {agent, response}
      if (event.type === 'delegation_response' && obj.agent) {
        return (
          <div className="space-y-1">
            <div className="flex items-center gap-2">
              <Users className="h-3 w-3 text-purple-500" />
              <span className="text-xs font-mono font-medium">{String(obj.agent)}</span>
            </div>
            {obj.response && (
              <pre className="text-xs bg-background/50 p-2 rounded overflow-auto max-h-24 text-muted-foreground">
                → {typeof obj.response === 'string' ? obj.response : JSON.stringify(obj.response, null, 2)}
              </pre>
            )}
          </div>
        );
      }

      // delegation_error: {agent, error}
      if (event.type === 'delegation_error' && obj.agent) {
        return (
          <div className="space-y-1">
            <div className="flex items-center gap-2">
              <AlertCircle className="h-3 w-3 text-destructive" />
              <span className="text-xs font-mono font-medium">{String(obj.agent)}</span>
            </div>
            <pre className="text-xs bg-destructive/10 p-2 rounded overflow-auto max-h-24 text-destructive">
              {String(obj.error || 'Unknown error')}
            </pre>
          </div>
        );
      }

      // Fallback for any other structured content
      return <span>{safeContentToString(content)}</span>;
    }

    // String content
    return <span>{String(content)}</span>;
  };

  // If memory is disabled, show a disabled state
  if (!isMemoryEnabled) {
    return (
      <div className="space-y-4">
        {/* Header */}
        <div className="flex items-center gap-2">
          <Brain className="h-5 w-5 text-muted-foreground" />
          <h2 className="text-lg font-semibold">Agent Memory</h2>
          <Badge variant="secondary">Disabled</Badge>
        </div>

        <Card>
          <CardContent className="py-12">
            <div className="text-center text-muted-foreground">
              <Brain className="h-12 w-12 mx-auto mb-4 opacity-50" />
              <p className="font-medium">Memory is disabled for this agent</p>
              <p className="text-sm mt-1">
                Enable memory in the agent configuration to store conversation history and events.
              </p>
            </div>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Brain className="h-5 w-5 text-agent" />
          <h2 className="text-lg font-semibold">Agent Memory</h2>
          {lastRefresh && (
            <span className="text-xs text-muted-foreground">
              Last updated: {lastRefresh.toLocaleTimeString()}
            </span>
          )}
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={fetchMemory}
          disabled={isLoading}
        >
          <RefreshCw className={`h-4 w-4 mr-2 ${isLoading ? 'animate-spin' : ''}`} />
          Refresh
        </Button>
      </div>

      {/* Error State */}
      {error && (
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      {/* Memory Content */}
      <Tabs defaultValue="events" className="space-y-4">
        <TabsList>
          <TabsTrigger value="events" className="gap-2">
            <MessageSquare className="h-4 w-4" />
            Events ({events.length})
          </TabsTrigger>
          <TabsTrigger value="sessions" className="gap-2">
            <Clock className="h-4 w-4" />
            Sessions ({sessions.length})
          </TabsTrigger>
        </TabsList>

        {/* Events Tab */}
        <TabsContent value="events">
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base flex items-center gap-2">
                <MessageSquare className="h-4 w-4" />
                Memory Events
              </CardTitle>
            </CardHeader>
            <CardContent>
              {isLoading ? (
                <div className="space-y-3">
                  {[1, 2, 3].map((i) => (
                    <div key={i} className="flex gap-3">
                      <Skeleton className="h-8 w-8 rounded" />
                      <div className="flex-1 space-y-2">
                        <Skeleton className="h-4 w-24" />
                        <Skeleton className="h-12 w-full" />
                      </div>
                    </div>
                  ))}
                </div>
              ) : events.length === 0 ? (
                <div className="text-center py-8 text-muted-foreground">
                  <Brain className="h-12 w-12 mx-auto mb-4 opacity-50" />
                  <p>No memory events recorded</p>
                  <p className="text-xs mt-1">Events will appear here after agent interactions</p>
                </div>
              ) : (
                <ScrollArea className="h-[400px] pr-4">
                  <div className="space-y-3">
                    {[...events].reverse().map((event, index) => (
                      <div
                        key={event.id || index}
                        className="flex gap-3 p-3 rounded-lg bg-muted/30 border border-border/50"
                      >
                        <div className="shrink-0 mt-1">
                          {getEventIcon(event)}
                        </div>
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2 mb-1">
                            {getEventBadge(event)}
                            {event.session_id && (
                              <Badge variant="outline" className="text-xs font-mono">
                                Session: {event.session_id.slice(0, 8)}...
                              </Badge>
                            )}
                            {event.timestamp && (
                              <span className="text-xs text-muted-foreground ml-auto">
                                {formatTimestamp(event.timestamp)}
                              </span>
                            )}
                          </div>
                          
                          {/* Content */}
                          {event.content && (
                            <div className="text-sm whitespace-pre-wrap break-words font-mono">
                              {renderEventContent(event)}
                            </div>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                </ScrollArea>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        {/* Sessions Tab */}
        <TabsContent value="sessions">
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base flex items-center gap-2">
                <Clock className="h-4 w-4" />
                Memory Sessions
              </CardTitle>
            </CardHeader>
            <CardContent>
              {isLoading ? (
                <div className="space-y-2">
                  {[1, 2, 3].map((i) => (
                    <Skeleton key={i} className="h-12 w-full" />
                  ))}
                </div>
              ) : sessions.length === 0 ? (
                <div className="text-center py-8 text-muted-foreground">
                  <Clock className="h-12 w-12 mx-auto mb-4 opacity-50" />
                  <p>No sessions recorded</p>
                  <p className="text-xs mt-1">Sessions will appear here after agent interactions</p>
                </div>
              ) : (
                <ScrollArea className="h-[400px] pr-4">
                  <div className="space-y-2">
                    {sessions.map((sessionId, index) => (
                      <div
                        key={sessionId || index}
                        className="flex items-center justify-between p-3 rounded-lg bg-muted/30 border border-border/50"
                      >
                        <div className="flex items-center gap-3">
                          <div className="h-8 w-8 rounded bg-primary/10 flex items-center justify-center">
                            <MessageSquare className="h-4 w-4 text-primary" />
                          </div>
                          <div>
                            <p className="text-sm font-mono font-medium">{sessionId}</p>
                            <p className="text-xs text-muted-foreground">
                              {events.filter(e => e.session_id === sessionId).length} events
                            </p>
                          </div>
                        </div>
                        <Badge variant="outline" className="text-xs">
                          Session
                        </Badge>
                      </div>
                    ))}
                  </div>
                </ScrollArea>
              )}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}
