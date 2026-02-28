import React from 'react';
import { RefreshCw, Download, Terminal, AlertCircle } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { ScrollArea } from '@/components/ui/scroll-area';
import { ContainerSelector } from '@/components/kubernetes/ContainerSelector';

interface PodLogsTabProps {
  containers: string[];
  selectedContainer: string;
  onContainerChange: (container: string) => void;
  logs: string;
  logsLoading: boolean;
  logsError: string | null;
  tailLines: number;
  onTailLinesChange: (lines: number) => void;
  autoRefresh: boolean;
  onAutoRefreshToggle: () => void;
  scrollRef: React.RefObject<HTMLDivElement | null>;
  onFetchLogs: () => void;
  onDownload: () => void;
}

function formatLogLine(line: string, index: number) {
  const isError = /error|fatal|panic/i.test(line);
  const isWarning = /warn|warning/i.test(line);
  const isInfo = /info/i.test(line);
  const isDebug = /debug|trace/i.test(line);

  let className = 'text-foreground/80';
  if (isError) className = 'text-red-400';
  else if (isWarning) className = 'text-yellow-400';
  else if (isInfo) className = 'text-blue-400';
  else if (isDebug) className = 'text-muted-foreground';

  return (
    <div key={index} className={`font-mono text-xs whitespace-pre-wrap break-all ${className}`}>
      {line}
    </div>
  );
}

export function PodLogsTab({
  containers, selectedContainer, onContainerChange,
  logs, logsLoading, logsError,
  tailLines, onTailLinesChange,
  autoRefresh, onAutoRefreshToggle,
  scrollRef, onFetchLogs, onDownload,
}: PodLogsTabProps) {
  return (
    <>
      {/* Logs Controls */}
      <div className="flex items-center gap-2 flex-wrap">
        <ContainerSelector
          containers={containers}
          selectedContainer={selectedContainer}
          onContainerChange={onContainerChange}
        />
        
        <Select value={String(tailLines)} onValueChange={(v) => onTailLinesChange(Number(v))}>
          <SelectTrigger className="w-[120px]">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="50">Last 50</SelectItem>
            <SelectItem value="100">Last 100</SelectItem>
            <SelectItem value="200">Last 200</SelectItem>
            <SelectItem value="500">Last 500</SelectItem>
            <SelectItem value="1000">Last 1000</SelectItem>
          </SelectContent>
        </Select>
        
        <Button
          variant={autoRefresh ? "default" : "outline"}
          size="sm"
          onClick={onAutoRefreshToggle}
        >
          <RefreshCw className={`h-4 w-4 mr-2 ${autoRefresh ? 'animate-spin' : ''}`} />
          Auto
        </Button>
        
        <Button variant="outline" size="sm" onClick={onFetchLogs} disabled={logsLoading}>
          <RefreshCw className={`h-4 w-4 ${logsLoading ? 'animate-spin' : ''}`} />
        </Button>
        
        <Button variant="outline" size="sm" onClick={onDownload} disabled={!logs}>
          <Download className="h-4 w-4" />
        </Button>
      </div>

      {/* Logs Content */}
      <Card className="border-border">
        <CardHeader className="py-3 border-b border-border">
          <CardTitle className="text-sm font-medium flex items-center justify-between">
            <span className="flex items-center gap-2">
              <Terminal className="h-4 w-4" />
              Container Logs
              {selectedContainer && (
                <Badge variant="outline" className="text-xs font-mono">
                  {selectedContainer}
                </Badge>
              )}
            </span>
            {logsLoading && (
              <span className="text-xs text-muted-foreground">Loading...</span>
            )}
          </CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          <ScrollArea 
            ref={scrollRef}
            className="h-[calc(100vh-420px)] bg-muted/30"
          >
            <div className="p-4 space-y-0.5">
              {logsError ? (
                <div className="flex items-center gap-2 text-destructive">
                  <AlertCircle className="h-4 w-4" />
                  <span className="text-sm">{logsError}</span>
                </div>
              ) : logs ? (
                logs.split('\n').map((line, i) => formatLogLine(line, i))
              ) : (
                <p className="text-muted-foreground text-sm">
                  {logsLoading ? 'Loading logs...' : 'No logs available'}
                </p>
              )}
            </div>
          </ScrollArea>
        </CardContent>
      </Card>
    </>
  );
}
