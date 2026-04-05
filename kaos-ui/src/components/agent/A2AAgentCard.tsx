import React from 'react';
import { Globe, RefreshCw, AlertCircle, Loader2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Alert, AlertDescription } from '@/components/ui/alert';
import type { AgentCard } from '@/types/a2a';

interface A2AAgentCardProps {
  card: AgentCard | null;
  isLoading: boolean;
  error: string | null;
  onRefresh: () => void;
}

export function A2AAgentCard({ card, isLoading, error, onRefresh }: A2AAgentCardProps) {
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Globe className="h-4 w-4 text-muted-foreground" />
          <h4 className="text-sm font-medium">Agent Card</h4>
        </div>
        <Button variant="ghost" size="sm" onClick={onRefresh} disabled={isLoading}>
          {isLoading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
        </Button>
      </div>

      {error && (
        <Alert variant="destructive" className="py-2">
          <AlertCircle className="h-4 w-4" />
          <AlertDescription className="text-xs">{error}</AlertDescription>
        </Alert>
      )}

      {card && (
        <div className="rounded-md border p-3 space-y-2 text-xs">
          <div className="flex items-start justify-between">
            <div>
              <p className="font-medium text-sm">{card.name}</p>
              {card.description && (
                <p className="text-muted-foreground mt-0.5">{card.description}</p>
              )}
            </div>
            {card.version && <Badge variant="outline" className="text-[10px]">v{card.version}</Badge>}
          </div>

          {card.url && (
            <div className="flex items-center gap-1 text-muted-foreground">
              <span className="font-mono text-[10px]">{card.url}</span>
            </div>
          )}

          <div className="flex flex-wrap gap-1.5 mt-1">
            {card.capabilities?.streaming && <Badge variant="secondary" className="text-[10px]">Streaming</Badge>}
            {card.capabilities?.pushNotifications && <Badge variant="secondary" className="text-[10px]">Push Notifications</Badge>}
            {card.capabilities?.stateTransitionHistory && <Badge variant="secondary" className="text-[10px]">State History</Badge>}
          </div>

          {card.skills && card.skills.length > 0 && (
            <div className="mt-2">
              <p className="text-muted-foreground mb-1">Skills:</p>
              <div className="flex flex-wrap gap-1">
                {card.skills.map((skill, i) => (
                  <Badge key={i} variant="outline" className="text-[10px]">
                    {skill.name || skill.id}
                  </Badge>
                ))}
              </div>
            </div>
          )}

          {card.supportedProtocols && card.supportedProtocols.length > 0 && (
            <div className="mt-1">
              <p className="text-muted-foreground mb-1">Protocols:</p>
              <div className="flex flex-wrap gap-1">
                {card.supportedProtocols.map((proto, i) => (
                  <Badge key={i} variant="outline" className="text-[10px] font-mono">{proto}</Badge>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {!card && !isLoading && !error && (
        <p className="text-xs text-muted-foreground italic">Click refresh to load agent card</p>
      )}
    </div>
  );
}
