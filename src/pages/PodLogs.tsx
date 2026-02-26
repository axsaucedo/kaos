import React, { useState, useEffect, useRef } from 'react';
import { useParams, useNavigate, useSearchParams } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Badge } from '@/components/ui/badge';
import { ScrollArea } from '@/components/ui/scroll-area';
import { ArrowLeft, RefreshCw, Download, Terminal, AlertCircle } from 'lucide-react';
import { k8sClient } from '@/lib/kubernetes-client';
import { useKubernetesStore } from '@/stores/kubernetesStore';
import type { Pod } from '@/types/kubernetes';

export default function PodLogs() {
  const { namespace, name } = useParams<{ namespace: string; name: string }>();
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  
  // Get return path from URL params (for returning to correct tab)
  const returnPath = searchParams.get('returnTo');
  
  const { pods } = useKubernetesStore();
  const [logs, setLogs] = useState<string>('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedContainer, setSelectedContainer] = useState<string>('');
  const [tailLines, setTailLines] = useState<number>(200);
  const [autoRefresh, setAutoRefresh] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  
  const pod = pods.find(p => p.metadata.name === name && p.metadata.namespace === namespace);
  const containers = pod?.spec?.containers?.map(c => c.name) || [];

  const fetchLogs = async () => {
    if (!namespace || !name) return;
    
    setLoading(true);
    setError(null);
    
    try {
      const logContent = await k8sClient.getPodLogs(name, namespace, {
        container: selectedContainer || undefined,
        tailLines,
      });
      setLogs(logContent);
      
      // Auto-scroll to bottom
      if (scrollRef.current) {
        scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch logs');
      setLogs('');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchLogs();
  }, [namespace, name, selectedContainer, tailLines]);

  useEffect(() => {
    if (!autoRefresh) return;
    
    const interval = setInterval(fetchLogs, 5000);
    return () => clearInterval(interval);
  }, [autoRefresh, namespace, name, selectedContainer, tailLines]);

  // Set default container when pod is loaded
  useEffect(() => {
    if (containers.length > 0 && !selectedContainer) {
      setSelectedContainer(containers[0]);
    }
  }, [containers, selectedContainer]);

  const handleDownload = () => {
    const blob = new Blob([logs], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${name}-${selectedContainer || 'logs'}.txt`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const formatLogLine = (line: string, index: number) => {
    // Detect log levels for coloring
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
  };

  return (
    <div className="min-h-screen bg-background">
      {/* Header */}
      <div className="border-b border-border bg-card">
        <div className="container mx-auto px-4 py-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-4">
              <Button variant="ghost" size="icon" onClick={() => returnPath ? navigate(returnPath) : navigate(-1)}>
                <ArrowLeft className="h-5 w-5" />
              </Button>
              <div>
                <div className="flex items-center gap-2">
                  <Terminal className="h-5 w-5 text-primary" />
                  <h1 className="text-lg font-semibold">Pod Logs</h1>
                </div>
                <p className="text-sm text-muted-foreground font-mono">
                  {namespace}/{name}
                </p>
              </div>
            </div>
            
            <div className="flex items-center gap-2">
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
              <Button variant="outline" size="sm" onClick={fetchLogs} disabled={loading}>
                <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
              </Button>
              
              {/* Download button */}
              <Button variant="outline" size="sm" onClick={handleDownload} disabled={!logs}>
                <Download className="h-4 w-4" />
              </Button>
            </div>
          </div>
        </div>
      </div>
      
      {/* Pod info bar */}
      {pod && (
        <div className="border-b border-border bg-muted/30">
          <div className="container mx-auto px-4 py-2">
            <div className="flex items-center gap-4 text-sm">
              <Badge variant={pod.status?.phase === 'Running' ? 'success' : 'secondary'}>
                {pod.status?.phase || 'Unknown'}
              </Badge>
              <span className="text-muted-foreground">
                IP: {pod.status?.podIP || 'N/A'}
              </span>
              <span className="text-muted-foreground">
                Host: {pod.status?.hostIP || 'N/A'}
              </span>
              {selectedContainer && containers.length > 0 && (
                <span className="text-muted-foreground">
                  Container: <span className="font-mono">{selectedContainer}</span>
                </span>
              )}
            </div>
          </div>
        </div>
      )}
      
      {/* Logs content */}
      <div className="container mx-auto px-4 py-4">
        <Card className="border-border bg-[hsl(var(--card))]">
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
            {error ? (
              <div className="flex flex-col items-center justify-center py-12 text-center">
                <AlertCircle className="h-10 w-10 text-destructive mb-3" />
                <p className="text-sm text-destructive font-medium">Failed to load logs</p>
                <p className="text-xs text-muted-foreground mt-1 max-w-md">{error}</p>
                <Button variant="outline" size="sm" className="mt-4" onClick={fetchLogs}>
                  Retry
                </Button>
              </div>
            ) : loading && !logs ? (
              <div className="flex items-center justify-center py-12">
                <RefreshCw className="h-6 w-6 animate-spin text-muted-foreground" />
              </div>
            ) : !logs ? (
              <div className="flex flex-col items-center justify-center py-12 text-center">
                <Terminal className="h-10 w-10 text-muted-foreground mb-3" />
                <p className="text-sm text-muted-foreground">No logs available</p>
              </div>
            ) : (
              <ScrollArea className="h-[calc(100vh-280px)]" ref={scrollRef}>
                <div className="p-4 bg-[hsl(var(--background))]">
                  {logs.split('\n').map((line, index) => formatLogLine(line, index))}
                </div>
              </ScrollArea>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
