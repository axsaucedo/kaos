import React, { useEffect } from 'react';
import { Radio, Clock, Loader2 } from 'lucide-react';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Badge } from '@/components/ui/badge';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Separator } from '@/components/ui/separator';
import { useA2ADebug } from './useA2ADebug';
import { A2AAgentCard } from './A2AAgentCard';
import { A2ASendMessage } from './A2ASendMessage';
import { A2ATaskViewer } from './A2ATaskViewer';
import type { Agent } from '@/types/kubernetes';

interface AgentA2ADebugProps {
  agent: Agent;
}

function getStateBadgeVariant(state: string): 'default' | 'secondary' | 'destructive' | 'outline' {
  switch (state) {
    case 'completed': return 'default';
    case 'failed': return 'destructive';
    case 'canceled': return 'outline';
    default: return 'secondary';
  }
}

export function AgentA2ADebug({ agent }: AgentA2ADebugProps) {
  const {
    agentCard, isLoadingCard, cardError, fetchAgentCard,
    isSending, sendError, sendMessage,
    currentTask, isLoadingTask, taskError,
    isPolling, stopPolling, startPolling,
    fetchTask, cancelTask,
    taskHistory, loadTaskFromHistory,
  } = useA2ADebug(agent);

  useEffect(() => {
    fetchAgentCard();
  }, [fetchAgentCard]);

  return (
    <div className="flex gap-4 h-[calc(100vh-380px)]" data-testid="a2a-debug-container">
      {/* Main panel */}
      <div className="flex-1 min-w-0">
        <ScrollArea className="h-full pr-2">
          <div className="space-y-4 pb-4">
            {/* Agent Card */}
            <A2AAgentCard
              card={agentCard}
              isLoading={isLoadingCard}
              error={cardError}
              onRefresh={fetchAgentCard}
            />

            <Separator />

            {/* Method tabs */}
            <Tabs defaultValue="send" className="w-full">
              <TabsList className="grid w-full grid-cols-2">
                <TabsTrigger value="send" data-testid="a2a-tab-send">
                  <Radio className="h-3 w-3 mr-1.5" />
                  Send Message
                </TabsTrigger>
                <TabsTrigger value="tasks" data-testid="a2a-tab-tasks">
                  <Clock className="h-3 w-3 mr-1.5" />
                  Get / Cancel Task
                </TabsTrigger>
              </TabsList>

              <TabsContent value="send" className="mt-4">
                <A2ASendMessage
                  isSending={isSending}
                  error={sendError}
                  onSend={sendMessage}
                />
              </TabsContent>

              <TabsContent value="tasks" className="mt-4">
                <A2ATaskViewer
                  currentTask={currentTask}
                  isLoading={isLoadingTask}
                  error={taskError}
                  isPolling={isPolling}
                  onFetchTask={fetchTask}
                  onCancelTask={cancelTask}
                  onStartPolling={startPolling}
                  onStopPolling={stopPolling}
                />
              </TabsContent>
            </Tabs>
          </div>
        </ScrollArea>
      </div>

      {/* Task history sidebar */}
      <div className="w-56 shrink-0 border-l pl-3">
        <div className="flex items-center gap-2 mb-3">
          <h4 className="text-xs font-medium text-muted-foreground uppercase tracking-wider">Task History</h4>
          {taskHistory.length > 0 && (
            <Badge variant="outline" className="text-[10px] h-4 px-1.5">{taskHistory.length}</Badge>
          )}
        </div>

        <ScrollArea className="h-[calc(100%-32px)]">
          {taskHistory.length === 0 ? (
            <p className="text-[10px] text-muted-foreground italic py-2">No tasks yet</p>
          ) : (
            <div className="space-y-1.5">
              {taskHistory.map((entry, i) => (
                <button
                  key={i}
                  onClick={() => loadTaskFromHistory(entry)}
                  className={`w-full text-left p-2 rounded-md border text-xs transition-colors hover:bg-muted/50 ${
                    currentTask?.id === entry.taskId ? 'bg-muted border-primary/30' : ''
                  }`}
                  data-testid={`a2a-history-${i}`}
                >
                  <div className="flex items-center justify-between mb-1">
                    <Badge variant={getStateBadgeVariant(entry.state)} className="text-[10px] h-4">
                      {entry.state === 'working' && <Loader2 className="h-2.5 w-2.5 mr-0.5 animate-spin" />}
                      {entry.state}
                    </Badge>
                    <Badge variant="outline" className="text-[10px] h-4">
                      {entry.mode === 'autonomous' ? '⚡' : '💬'}
                    </Badge>
                  </div>
                  <p className="text-[10px] text-muted-foreground truncate">{entry.message || '(empty)'}</p>
                  <p className="text-[10px] text-muted-foreground/60 mt-0.5 font-mono">
                    {entry.createdAt.toLocaleTimeString()}
                  </p>
                </button>
              ))}
            </div>
          )}
        </ScrollArea>
      </div>
    </div>
  );
}
