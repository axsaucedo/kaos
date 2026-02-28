import React, { useState, useEffect } from 'react';
import { RefreshCw, AlertCircle, Download, Terminal } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { usePodLogs } from '@/hooks/usePodLogs';
import type { Pod } from '@/types/kubernetes';

interface SystemLogsProps {
  selectedPod: Pod | null;
  operatorPods: Pod[];
  onSelectPod: (pod: Pod) => void;
  active: boolean;
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

export default function SystemLogs({
  selectedPod,
  operatorPods,
  onSelectPod,
  active,
}: SystemLogsProps) {
  const [selectedContainer, setSelectedContainer] = useState<string>('');

  const containers = selectedPod?.spec?.containers?.map(c => c.name) || [];

  const {
    logs, logsLoading, logsError,
    tailLines, setTailLines,
    autoRefresh, setAutoRefresh,
    scrollRef, fetchLogs, handleDownload: handleDownloadLogs,
  } = usePodLogs({
    namespace: selectedPod?.metadata.namespace,
    podName: selectedPod?.metadata.name,
    containerName: selectedContainer,
    active: active && !!selectedPod,
  });

  // Set default container when pod is selected
  useEffect(() => {
    if (selectedPod && selectedPod.spec.containers.length > 0) {
      setSelectedContainer(selectedPod.spec.containers[0].name);
    }
  }, [selectedPod]);

  return (
    <>
      {/* Logs Controls */}
      <div className="flex items-center justify-between gap-4 flex-wrap">
        <div className="flex items-center gap-2">
          {/* Pod selector */}
          <Select 
            value={selectedPod?.metadata.name || ''} 
            onValueChange={(name) => {
              const pod = operatorPods.find(p => p.metadata.name === name);
              if (pod) onSelectPod(pod);
            }}
          >
            <SelectTrigger className="w-[240px]">
              <SelectValue placeholder="Select pod" />
            </SelectTrigger>
            <SelectContent>
              {operatorPods.map(pod => (
                <SelectItem key={pod.metadata.name} value={pod.metadata.name}>
                  {pod.metadata.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>

          {/* Container selector */}
          {containers.length > 1 && (
            <Select value={selectedContainer} onValueChange={setSelectedContainer}>
              <SelectTrigger className="w-[180px]">
                <SelectValue placeholder="Select container" />
              </SelectTrigger>
              <SelectContent>
                {containers.map(container => (
                  <SelectItem key={container} value={container}>
                    {container}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          )}
          
          {/* Tail lines selector */}
          <Select value={String(tailLines)} onValueChange={(v) => setTailLines(Number(v))}>
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
        </div>

        <div className="flex items-center gap-2">
          {/* Auto-refresh toggle */}
          <Button
            variant={autoRefresh ? "default" : "outline"}
            size="sm"
            onClick={() => setAutoRefresh(!autoRefresh)}
          >
            <RefreshCw className={`h-4 w-4 mr-2 ${autoRefresh ? 'animate-spin' : ''}`} />
            Auto
          </Button>
          
          {/* Refresh button */}
          <Button variant="outline" size="sm" onClick={fetchLogs} disabled={logsLoading}>
            <RefreshCw className={`h-4 w-4 ${logsLoading ? 'animate-spin' : ''}`} />
          </Button>
          
          {/* Download button */}
          <Button variant="outline" size="sm" onClick={handleDownloadLogs} disabled={!logs}>
            <Download className="h-4 w-4" />
          </Button>
        </div>
      </div>

      {/* Logs Content */}
      <Card>
        <CardHeader className="py-3 border-b border-border">
          <CardTitle className="text-sm font-medium flex items-center justify-between">
            <span>Log Output</span>
            {logs && (
              <span className="text-xs text-muted-foreground font-normal">
                {logs.split('\n').length} lines
              </span>
            )}
          </CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          {logsError ? (
            <div className="flex flex-col items-center justify-center py-12 text-center">
              <AlertCircle className="h-10 w-10 text-destructive mb-3" />
              <p className="text-sm text-destructive font-medium">Failed to load logs</p>
              <p className="text-xs text-muted-foreground mt-1 max-w-md">{logsError}</p>
              <Button variant="outline" size="sm" className="mt-4" onClick={fetchLogs}>
                Retry
              </Button>
            </div>
          ) : logsLoading && !logs ? (
            <div className="flex items-center justify-center py-12">
              <RefreshCw className="h-6 w-6 animate-spin text-muted-foreground" />
            </div>
          ) : !logs ? (
            <div className="flex flex-col items-center justify-center py-12 text-center">
              <Terminal className="h-10 w-10 text-muted-foreground mb-3" />
              <p className="text-sm text-muted-foreground">No logs available</p>
              <p className="text-xs text-muted-foreground mt-1">Select a pod to view its logs</p>
            </div>
          ) : (
            <ScrollArea className="h-[500px]" ref={scrollRef as React.RefObject<HTMLDivElement>}>
              <div className="p-4 bg-background">
                {logs.split('\n').map((line, index) => formatLogLine(line, index))}
              </div>
            </ScrollArea>
          )}
        </CardContent>
      </Card>
    </>
  );
}
