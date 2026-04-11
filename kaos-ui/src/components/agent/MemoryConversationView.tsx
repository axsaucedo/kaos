import React, { useState } from 'react';
import { User, Bot, Wrench, AlertCircle, Users, ChevronDown, ChevronRight, CheckCircle2 } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { cn } from '@/lib/utils';

interface MemoryEvent {
  id: string;
  type: string;
  content?: string | Record<string, unknown>;
  timestamp?: string;
  session_id?: string;
  metadata?: Record<string, unknown>;
}

interface MemoryConversationViewProps {
  events: MemoryEvent[];
}

function ToolPill({ event }: { event: MemoryEvent }) {
  const [expanded, setExpanded] = useState(false);
  const obj = typeof event.content === 'object' ? (event.content as Record<string, unknown>) : {};
  const toolName = String(obj.tool || obj.agent || 'unknown');
  const isError = event.type === 'tool_error' || event.type === 'delegation_error';
  const isDelegation = event.type.startsWith('delegation_');
  const isResult = event.type === 'tool_result' || event.type === 'delegation_response';

  const Icon = isError ? AlertCircle : isDelegation ? Users : isResult ? CheckCircle2 : Wrench;
  const colorClass = isError ? 'text-destructive border-destructive/30 bg-destructive/5' :
    isDelegation ? 'text-purple-500 border-purple-500/30 bg-purple-500/5' :
    isResult ? 'text-green-500 border-green-500/30 bg-green-500/5' :
    'text-mcpserver border-mcpserver/30 bg-mcpserver/5';

  const label = isResult ? '✓' : isError ? '✗' : isDelegation && isResult ? '←' : isDelegation ? '→' : '🔧';
  const detail = isResult ? (obj.result || obj.response) : isError ? obj.error : (obj.arguments || obj.task);

  return (
    <div className="my-1">
      <button
        onClick={() => setExpanded(!expanded)}
        className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full border text-xs font-mono transition-colors hover:opacity-80 ${colorClass}`}
      >
        <Icon className="h-3 w-3" />
        <span>{label} {toolName}</span>
        {detail && (
          expanded ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />
        )}
      </button>
      {expanded && detail && (
        <pre className="text-xs font-mono ml-4 mt-1 p-2 rounded bg-muted/50 max-h-32 overflow-auto whitespace-pre-wrap break-all">
          {typeof detail === 'string' ? detail : JSON.stringify(detail, null, 2)}
        </pre>
      )}
    </div>
  );
}

function MessageBubble({ event }: { event: MemoryEvent }) {
  const isUser = event.type === 'user_message';
  const content = typeof event.content === 'string' ? event.content :
    typeof event.content === 'object' ? JSON.stringify(event.content) : '';

  return (
    <div className={`flex gap-2 ${isUser ? '' : 'flex-row-reverse'}`}>
      <div className="shrink-0 mt-1">
        {isUser ? (
          <div className="h-6 w-6 rounded-full bg-blue-500/10 flex items-center justify-center">
            <User className="h-3.5 w-3.5 text-blue-500" />
          </div>
        ) : (
          <div className="h-6 w-6 rounded-full bg-green-500/10 flex items-center justify-center">
            <Bot className="h-3.5 w-3.5 text-agent" />
          </div>
        )}
      </div>
      <div className={`max-w-[80%] rounded-lg px-3 py-2 text-sm ${
        isUser ? 'bg-blue-500/10 text-foreground' : 'bg-muted text-foreground'
      }`}>
        <div className={cn(
          "prose prose-sm dark:prose-invert max-w-none",
          "prose-headings:text-foreground prose-p:text-foreground/90",
          "prose-strong:text-foreground prose-code:text-primary prose-code:bg-muted prose-code:px-1 prose-code:py-0.5 prose-code:rounded",
          "prose-pre:bg-muted prose-pre:border prose-pre:border-border",
          "prose-ul:text-foreground/90 prose-ol:text-foreground/90 prose-li:text-foreground/90",
          "prose-a:text-primary prose-a:underline"
        )}>
          <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            components={{
              p: ({ children }) => <p className="leading-relaxed mb-2 last:mb-0">{children}</p>,
              ul: ({ children }) => <ul className="list-disc list-inside mb-2 space-y-0.5">{children}</ul>,
              ol: ({ children }) => <ol className="list-decimal list-inside mb-2 space-y-0.5">{children}</ol>,
              li: ({ children }) => <li className="leading-relaxed">{children}</li>,
              h1: ({ children }) => <h1 className="text-xl font-bold mb-2 mt-3 first:mt-0">{children}</h1>,
              h2: ({ children }) => <h2 className="text-lg font-bold mb-2 mt-2 first:mt-0">{children}</h2>,
              h3: ({ children }) => <h3 className="text-base font-semibold mb-1.5 mt-2 first:mt-0">{children}</h3>,
              strong: ({ children }) => <strong className="font-bold">{children}</strong>,
              em: ({ children }) => <em className="italic">{children}</em>,
              code: ({ children, className }) => {
                const isBlock = className?.includes('language-');
                return isBlock ? (
                  <code className={cn("block overflow-x-auto p-2 rounded bg-muted", className)}>{children}</code>
                ) : (
                  <code className="text-sm bg-muted px-1 py-0.5 rounded">{children}</code>
                );
              },
              pre: ({ children }) => <pre className="overflow-x-auto mb-2 rounded border border-border">{children}</pre>,
              blockquote: ({ children }) => <blockquote className="border-l-2 border-primary pl-4 italic my-2">{children}</blockquote>,
              hr: () => <hr className="my-3 border-border" />,
            }}
          >
            {content}
          </ReactMarkdown>
        </div>
        {event.timestamp && (
          <p className="text-[10px] text-muted-foreground mt-1">
            {new Date(event.timestamp).toLocaleTimeString()}
          </p>
        )}
      </div>
    </div>
  );
}

export function MemoryConversationView({ events }: MemoryConversationViewProps) {
  // Group consecutive user_message events as iteration boundaries
  let lastWasUserMessage = false;
  let iterationCount = 0;

  return (
    <div className="space-y-2 p-2">
      {events.length === 0 ? (
        <p className="text-xs text-muted-foreground italic text-center py-8">No events to display</p>
      ) : (
        events.map((event, i) => {
          const isUserMessage = event.type === 'user_message';
          const showDivider = isUserMessage && lastWasUserMessage && i > 0;
          if (isUserMessage && i > 0) iterationCount++;
          lastWasUserMessage = isUserMessage;

          const isToolOrDelegation = ['tool_call', 'tool_result', 'tool_error',
            'delegation_request', 'delegation_response', 'delegation_error'].includes(event.type);

          return (
            <React.Fragment key={event.id || i}>
              {showDivider && (
                <div className="flex items-center gap-2 py-2">
                  <div className="flex-1 border-t border-border/50" />
                  <Badge variant="outline" className="text-[10px] text-muted-foreground">
                    Iteration {iterationCount}
                  </Badge>
                  <div className="flex-1 border-t border-border/50" />
                </div>
              )}
              {isToolOrDelegation ? (
                <ToolPill event={event} />
              ) : isUserMessage || event.type === 'agent_response' ? (
                <MessageBubble event={event} />
              ) : (
                // Fallback for other event types
                <div className="flex items-center gap-2 my-1 text-xs text-muted-foreground">
                  <Badge variant="secondary" className="text-[10px]">{event.type}</Badge>
                  <span className="truncate">{typeof event.content === 'string' ? event.content : ''}</span>
                </div>
              )}
            </React.Fragment>
          );
        })
      )}
    </div>
  );
}
