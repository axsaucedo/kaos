import React, { useState } from 'react';
import { Send, Loader2, Zap, MessageCircle } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { Alert, AlertDescription } from '@/components/ui/alert';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import type { SendMessageParams } from '@/types/a2a';

interface A2ASendMessageProps {
  isSending: boolean;
  error: string | null;
  onSend: (params: SendMessageParams) => Promise<unknown>;
}

export function A2ASendMessage({ isSending, error, onSend }: A2ASendMessageProps) {
  const [message, setMessage] = useState('');
  const [mode, setMode] = useState<'interactive' | 'autonomous'>('interactive');
  const [sessionId, setSessionId] = useState(() => `ui-${Date.now()}`);
  const [maxIterations, setMaxIterations] = useState('10');
  const [maxRuntimeSeconds, setMaxRuntimeSeconds] = useState('300');
  const [maxToolCalls, setMaxToolCalls] = useState('50');

  const handleSend = async () => {
    if (!message.trim()) return;

    const params: SendMessageParams = {
      message: {
        role: 'user',
        parts: [{ type: 'text', text: message.trim() }],
      },
      configuration: {
        mode,
        ...(mode === 'autonomous' ? {
          budgets: {
            maxIterations: parseInt(maxIterations) || 10,
            maxRuntimeSeconds: parseInt(maxRuntimeSeconds) || 300,
            maxToolCalls: parseInt(maxToolCalls) || 50,
          },
        } : {}),
      },
      contextId: sessionId,
    };

    await onSend(params);
    setMessage('');
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div className="space-y-4">
      {/* Mode selector */}
      <div className="flex items-center gap-3">
        <Label className="text-xs text-muted-foreground shrink-0">Mode:</Label>
        <Select value={mode} onValueChange={(v) => setMode(v as 'interactive' | 'autonomous')}>
          <SelectTrigger className="w-40 h-8 text-xs" data-testid="a2a-mode-select">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="interactive">
              <div className="flex items-center gap-1.5">
                <MessageCircle className="h-3 w-3" />
                Interactive
              </div>
            </SelectItem>
            <SelectItem value="autonomous">
              <div className="flex items-center gap-1.5">
                <Zap className="h-3 w-3" />
                Autonomous
              </div>
            </SelectItem>
          </SelectContent>
        </Select>
        <Badge variant={mode === 'autonomous' ? 'default' : 'secondary'} className="text-[10px]">
          {mode === 'autonomous' ? 'Async Task' : 'Sync'}
        </Badge>
      </div>

      {/* Session ID */}
      <div className="space-y-1">
        <Label htmlFor="a2a-session" className="text-xs text-muted-foreground">Session / Context ID</Label>
        <Input
          id="a2a-session"
          value={sessionId}
          onChange={(e) => setSessionId(e.target.value)}
          placeholder="Session ID"
          className="h-8 text-xs font-mono"
          data-testid="a2a-session-input"
        />
      </div>

      {/* Autonomous budgets */}
      {mode === 'autonomous' && (
        <div className="grid grid-cols-3 gap-3 p-3 rounded-md border bg-muted/30">
          <div className="space-y-1">
            <Label className="text-[10px] text-muted-foreground">Max Iterations</Label>
            <Input
              type="number"
              value={maxIterations}
              onChange={(e) => setMaxIterations(e.target.value)}
              className="h-7 text-xs font-mono"
              min={1}
            />
          </div>
          <div className="space-y-1">
            <Label className="text-[10px] text-muted-foreground">Max Runtime (s)</Label>
            <Input
              type="number"
              value={maxRuntimeSeconds}
              onChange={(e) => setMaxRuntimeSeconds(e.target.value)}
              className="h-7 text-xs font-mono"
              min={1}
            />
          </div>
          <div className="space-y-1">
            <Label className="text-[10px] text-muted-foreground">Max Tool Calls</Label>
            <Input
              type="number"
              value={maxToolCalls}
              onChange={(e) => setMaxToolCalls(e.target.value)}
              className="h-7 text-xs font-mono"
              min={1}
            />
          </div>
        </div>
      )}

      {/* Message input */}
      <div className="space-y-1">
        <Label htmlFor="a2a-message" className="text-xs text-muted-foreground">Message</Label>
        <Textarea
          id="a2a-message"
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Enter message to send via A2A protocol..."
          rows={3}
          className="text-sm resize-none"
          data-testid="a2a-message-input"
        />
        <p className="text-[10px] text-muted-foreground">⌘+Enter to send</p>
      </div>

      {error && (
        <Alert variant="destructive" className="py-2">
          <AlertDescription className="text-xs">{error}</AlertDescription>
        </Alert>
      )}

      {/* Send button */}
      <Button
        onClick={handleSend}
        disabled={isSending || !message.trim()}
        className="w-full"
        data-testid="a2a-send-button"
      >
        {isSending ? (
          <>
            <Loader2 className="h-4 w-4 mr-2 animate-spin" />
            {mode === 'autonomous' ? 'Submitting Task...' : 'Sending...'}
          </>
        ) : (
          <>
            <Send className="h-4 w-4 mr-2" />
            Send Message
          </>
        )}
      </Button>
    </div>
  );
}
