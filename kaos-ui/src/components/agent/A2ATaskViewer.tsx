import React, { useState } from 'react';
import { Search, XCircle, Loader2, Copy, Check, RefreshCw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { ScrollArea } from '@/components/ui/scroll-area';
import type { A2ATask } from '@/types/a2a';

interface A2ATaskViewerProps {
  currentTask: A2ATask | null;
  isLoading: boolean;
  error: string | null;
  isPolling: boolean;
  onFetchTask: (taskId: string) => void;
  onCancelTask: (taskId: string) => void;
  onStartPolling: (taskId: string) => void;
  onStopPolling: () => void;
}

function getStateBadgeVariant(state: string): 'default' | 'secondary' | 'destructive' | 'outline' {
  switch (state) {
    case 'completed': return 'default';
    case 'failed': return 'destructive';
    case 'canceled': return 'outline';
    case 'working': return 'secondary';
    case 'submitted': return 'secondary';
    default: return 'outline';
  }
}

export function A2ATaskViewer({
  currentTask,
  isLoading,
  error,
  isPolling,
  onFetchTask,
  onCancelTask,
  onStartPolling,
  onStopPolling,
}: A2ATaskViewerProps) {
  const [taskIdInput, setTaskIdInput] = useState('');
  const [copiedField, setCopiedField] = useState<string | null>(null);

  const handleFetch = () => {
    if (taskIdInput.trim()) {
      onFetchTask(taskIdInput.trim());
    }
  };

  const handleCopy = async (text: string, field: string) => {
    await navigator.clipboard.writeText(text);
    setCopiedField(field);
    setTimeout(() => setCopiedField(null), 2000);
  };

  const isTerminal = currentTask?.status?.state && ['completed', 'failed', 'canceled'].includes(currentTask.status.state);
  const isRunning = currentTask?.status?.state && ['submitted', 'working'].includes(currentTask.status.state);

  return (
    <div className="space-y-4">
      {/* Task ID lookup */}
      <div className="space-y-1">
        <Label className="text-xs text-muted-foreground">Task ID</Label>
        <div className="flex gap-2">
          <Input
            value={taskIdInput}
            onChange={(e) => setTaskIdInput(e.target.value)}
            placeholder="Enter task ID to look up..."
            className="h-8 text-xs font-mono flex-1"
            data-testid="a2a-task-id-input"
            onKeyDown={(e) => e.key === 'Enter' && handleFetch()}
          />
          <Button variant="outline" size="sm" onClick={handleFetch} disabled={isLoading || !taskIdInput.trim()}>
            {isLoading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Search className="h-3.5 w-3.5" />}
          </Button>
        </div>
      </div>

      {error && (
        <Alert variant="destructive" className="py-2">
          <AlertDescription className="text-xs">{error}</AlertDescription>
        </Alert>
      )}

      {/* Task details */}
      {currentTask && (
        <div className="rounded-md border p-3 space-y-3" data-testid="a2a-task-detail">
          {/* Header: ID + State */}
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span className="text-xs font-mono text-muted-foreground truncate max-w-[200px]">{currentTask.id}</span>
              <Button
                variant="ghost"
                size="sm"
                className="h-5 w-5 p-0"
                onClick={() => handleCopy(currentTask.id, 'id')}
              >
                {copiedField === 'id' ? <Check className="h-3 w-3 text-green-500" /> : <Copy className="h-3 w-3" />}
              </Button>
            </div>
            <Badge variant={getStateBadgeVariant(currentTask.status?.state || 'unknown')} data-testid="a2a-task-state">
              {isPolling && <Loader2 className="h-3 w-3 mr-1 animate-spin" />}
              {currentTask.status?.state || 'unknown'}
            </Badge>
          </div>

          {/* Session ID */}
          {currentTask.sessionId && (
            <div className="text-[10px] text-muted-foreground">
              Session: <span className="font-mono">{currentTask.sessionId}</span>
            </div>
          )}

          {/* Status message */}
          {currentTask.status?.message && (
            <div className="text-xs p-2 rounded bg-muted/50">
              <p className="text-muted-foreground mb-0.5 text-[10px]">Status Message:</p>
              <p>{currentTask.status.message}</p>
            </div>
          )}

          {/* Output / Artifacts */}
          {currentTask.output && (
            <div className="space-y-1">
              <p className="text-[10px] text-muted-foreground">Output:</p>
              <ScrollArea className="max-h-40">
                <pre className="text-xs font-mono p-2 rounded bg-muted/50 whitespace-pre-wrap break-all">
                  {typeof currentTask.output === 'string' ? currentTask.output : JSON.stringify(currentTask.output, null, 2)}
                </pre>
              </ScrollArea>
              <Button
                variant="ghost"
                size="sm"
                className="h-6 text-[10px]"
                onClick={() => handleCopy(
                  typeof currentTask.output === 'string' ? currentTask.output : JSON.stringify(currentTask.output, null, 2),
                  'output'
                )}
              >
                {copiedField === 'output' ? <Check className="h-3 w-3 mr-1 text-green-500" /> : <Copy className="h-3 w-3 mr-1" />}
                Copy Output
              </Button>
            </div>
          )}

          {/* History */}
          {currentTask.history && currentTask.history.length > 0 && (
            <div className="space-y-1">
              <p className="text-[10px] text-muted-foreground">History ({currentTask.history.length} messages):</p>
              <ScrollArea className="max-h-48">
                <div className="space-y-1">
                  {currentTask.history.map((msg, i) => (
                    <div key={i} className="text-xs p-1.5 rounded bg-muted/30 flex gap-2">
                      <Badge variant="outline" className="text-[10px] shrink-0 h-5">
                        {msg.role}
                      </Badge>
                      <span className="text-muted-foreground break-all">
                        {msg.parts?.map((p: { text?: string }) => p.text).join(' ') || '(no text)'}
                      </span>
                    </div>
                  ))}
                </div>
              </ScrollArea>
            </div>
          )}

          {/* Actions */}
          <div className="flex gap-2 pt-1">
            {isRunning && !isPolling && (
              <Button variant="outline" size="sm" className="text-xs" onClick={() => onStartPolling(currentTask.id)}>
                <RefreshCw className="h-3 w-3 mr-1" />
                Auto-Refresh
              </Button>
            )}
            {isPolling && (
              <Button variant="outline" size="sm" className="text-xs" onClick={onStopPolling}>
                Stop Polling
              </Button>
            )}
            {isRunning && (
              <Button variant="destructive" size="sm" className="text-xs" onClick={() => onCancelTask(currentTask.id)} data-testid="a2a-cancel-button">
                <XCircle className="h-3 w-3 mr-1" />
                Cancel Task
              </Button>
            )}
            {!isPolling && isTerminal && (
              <Button variant="ghost" size="sm" className="text-xs" onClick={() => onFetchTask(currentTask.id)}>
                <RefreshCw className="h-3 w-3 mr-1" />
                Refresh
              </Button>
            )}
          </div>
        </div>
      )}

      {!currentTask && !isLoading && !error && (
        <p className="text-xs text-muted-foreground italic text-center py-4">
          Send a message or look up a task ID to view details
        </p>
      )}
    </div>
  );
}
