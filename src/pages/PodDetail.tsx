import React, { useState, useEffect, useRef, useCallback } from 'react';
import { useParams, useNavigate, useSearchParams } from 'react-router-dom';
import { ArrowLeft, Boxes, RefreshCw, Download, Terminal, AlertCircle, Copy, Check, Info, FileCode } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { ScrollArea } from '@/components/ui/scroll-area';
import { useKubernetesStore } from '@/stores/kubernetesStore';
import { useKubernetesConnection } from '@/contexts/KubernetesConnectionContext';
import { k8sClient } from '@/lib/kubernetes-client';
import { YamlViewer } from '@/components/shared/YamlViewer';
import type { Pod } from '@/types/kubernetes';

export default function PodDetail() {
  const { namespace, name } = useParams<{ namespace: string; name: string }>();
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  
  const returnPath = searchParams.get('returnTo');
  const initialTab = searchParams.get('tab') || 'overview';
  
  const { pods } = useKubernetesStore();
  const { connected, refreshAll } = useKubernetesConnection();
  
  const [currentTab, setCurrentTab] = useState(initialTab);
  const [logs, setLogs] = useState<string>('');
  const [logsLoading, setLogsLoading] = useState(false);
  const [logsError, setLogsError] = useState<string | null>(null);
  const [selectedContainer, setSelectedContainer] = useState<string>('');
  const [tailLines, setTailLines] = useState<number>(200);
  const [autoRefresh, setAutoRefresh] = useState(false);
  const [copiedCommand, setCopiedCommand] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  const pod = pods.find(p => p.metadata.name === name && p.metadata.namespace === namespace);
  const containers = pod?.spec?.containers?.map(c => c.name) || [];

  // Set default container when pod is loaded
  useEffect(() => {
    if (containers.length > 0 && !selectedContainer) {
      setSelectedContainer(containers[0]);
    }
  }, [containers, selectedContainer]);

  const fetchLogs = useCallback(async () => {
    if (!namespace || !name) return;
    
    setLogsLoading(true);
    setLogsError(null);
    
    try {
      const logContent = await k8sClient.getPodLogs(name, namespace, {
        container: selectedContainer || undefined,
        tailLines,
      });
      setLogs(logContent);
      
      if (scrollRef.current) {
        scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
      }
    } catch (err) {
      setLogsError(err instanceof Error ? err.message : 'Failed to fetch logs');
      setLogs('');
    } finally {
      setLogsLoading(false);
    }
  }, [namespace, name, selectedContainer, tailLines]);

  // Fetch logs when on logs tab
  useEffect(() => {
    if (currentTab === 'logs') {
      fetchLogs();
    }
  }, [currentTab, fetchLogs]);

  // Auto-refresh logs
  useEffect(() => {
    if (!autoRefresh || currentTab !== 'logs') return;
    
    const interval = setInterval(fetchLogs, 5000);
    return () => clearInterval(interval);
  }, [autoRefresh, currentTab, fetchLogs]);

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

  const copyExecCommand = () => {
    const container = selectedContainer || containers[0];
    const command = container
      ? `kubectl exec -it -n ${namespace} ${name} -c ${container} -- /bin/sh`
      : `kubectl exec -it -n ${namespace} ${name} -- /bin/sh`;
    navigator.clipboard.writeText(command);
    setCopiedCommand(true);
    setTimeout(() => setCopiedCommand(false), 2000);
  };

  const handleBack = () => {
    if (returnPath) {
      navigate(decodeURIComponent(returnPath));
    } else {
      navigate('/');
    }
  };

  if (!connected) {
    return (
      <div className="flex flex-col items-center justify-center h-full p-8">
        <div className="text-center">
          <h2 className="text-xl font-semibold mb-2">Not Connected</h2>
          <p className="text-muted-foreground mb-4">
            Please connect to a Kubernetes cluster first.
          </p>
          <Button onClick={() => navigate('/')}>Go to Dashboard</Button>
        </div>
      </div>
    );
  }

  if (!pod) {
    return (
      <div className="flex flex-col items-center justify-center h-full p-8">
        <div className="text-center">
          <h2 className="text-xl font-semibold mb-2">Pod Not Found</h2>
          <p className="text-muted-foreground mb-4">
            The pod "{name}" in namespace "{namespace}" could not be found.
          </p>
          <div className="flex gap-2 justify-center">
            <Button variant="outline" onClick={() => refreshAll()}>
              <RefreshCw className="h-4 w-4 mr-2" />
              Refresh
            </Button>
            <Button onClick={() => navigate('/')}>Go to Dashboard</Button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="p-6 space-y-6 animate-fade-in">
      {/* Page Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <Button
            variant="ghost"
            size="icon"
            onClick={handleBack}
            className="shrink-0"
          >
            <ArrowLeft className="h-5 w-5" />
          </Button>
          
          <div className="flex items-center gap-3">
            <div className="h-12 w-12 rounded-xl bg-pod/10 flex items-center justify-center">
              <Boxes className="h-6 w-6 text-pod" />
            </div>
            <div>
              <h1 className="text-2xl font-bold text-foreground">{pod.metadata.name}</h1>
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <span className="font-mono">{pod.metadata.namespace || 'default'}</span>
                <Badge
                  variant={pod.status?.phase === 'Running' ? 'success' : pod.status?.phase === 'Pending' ? 'warning' : 'destructive'}
                  className="text-xs"
                >
                  {pod.status?.phase || 'Unknown'}
                </Badge>
              </div>
            </div>
          </div>
        </div>

        <Button variant="outline" size="sm" onClick={() => refreshAll()}>
          <RefreshCw className="h-4 w-4 mr-2" />
          Refresh
        </Button>
      </div>

      {/* Tabs Content */}
      <Tabs value={currentTab} onValueChange={setCurrentTab} className="space-y-6">
        <TabsList className="grid w-full max-w-md grid-cols-3">
          <TabsTrigger value="overview" className="flex items-center gap-1">
            <Info className="h-3 w-3" />
            Overview
          </TabsTrigger>
          <TabsTrigger value="logs" className="flex items-center gap-1">
            <Terminal className="h-3 w-3" />
            Logs
          </TabsTrigger>
          <TabsTrigger value="yaml" className="flex items-center gap-1">
            <FileCode className="h-3 w-3" />
            YAML
          </TabsTrigger>
        </TabsList>

        {/* Overview Tab */}
        <TabsContent value="overview" className="space-y-6">
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* Pod Info */}
            <Card>
              <CardHeader>
                <CardTitle className="text-base">Pod Information</CardTitle>
              </CardHeader>
              <CardContent className="grid grid-cols-2 gap-4 text-sm">
                <div>
                  <span className="text-muted-foreground">Name</span>
                  <p className="font-mono font-medium">{pod.metadata.name}</p>
                </div>
                <div>
                  <span className="text-muted-foreground">Namespace</span>
                  <p className="font-mono font-medium">{pod.metadata.namespace || 'default'}</p>
                </div>
                <div>
                  <span className="text-muted-foreground">Status</span>
                  <p className="font-medium">
                    <Badge variant={pod.status?.phase === 'Running' ? 'success' : pod.status?.phase === 'Pending' ? 'warning' : 'destructive'}>
                      {pod.status?.phase || 'Unknown'}
                    </Badge>
                  </p>
                </div>
                <div>
                  <span className="text-muted-foreground">Pod IP</span>
                  <p className="font-mono font-medium">{pod.status?.podIP || 'N/A'}</p>
                </div>
                <div>
                  <span className="text-muted-foreground">Host IP</span>
                  <p className="font-mono font-medium">{pod.status?.hostIP || 'N/A'}</p>
                </div>
                <div>
                  <span className="text-muted-foreground">Node</span>
                  <p className="font-mono font-medium">{pod.spec.nodeName || 'N/A'}</p>
                </div>
                {pod.metadata.creationTimestamp && (
                  <div className="col-span-2">
                    <span className="text-muted-foreground">Created</span>
                    <p className="font-medium">{new Date(pod.metadata.creationTimestamp).toLocaleString()}</p>
                  </div>
                )}
              </CardContent>
            </Card>

            {/* Container Command & Args */}
            <Card>
              <CardHeader>
                <CardTitle className="text-base">Container Command & Args</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                {pod.spec.containers.map((container) => (
                  <div key={container.name} className="space-y-2">
                    {containers.length > 1 && (
                      <p className="text-sm font-medium text-muted-foreground">{container.name}</p>
                    )}
                    <div className="space-y-2">
                      {container.command && container.command.length > 0 && (
                        <div>
                          <span className="text-xs text-muted-foreground">Command:</span>
                          <code className="block bg-muted p-2 rounded-md font-mono text-xs break-all mt-1">
                            {container.command.join(' ')}
                          </code>
                        </div>
                      )}
                      {container.args && container.args.length > 0 && (
                        <div>
                          <span className="text-xs text-muted-foreground">Args:</span>
                          <code className="block bg-muted p-2 rounded-md font-mono text-xs break-all mt-1">
                            {container.args.join(' ')}
                          </code>
                        </div>
                      )}
                      {(!container.command || container.command.length === 0) && (!container.args || container.args.length === 0) && (
                        <p className="text-xs text-muted-foreground italic">Using image default entrypoint</p>
                      )}
                    </div>
                  </div>
                ))}
                <div className="pt-2 border-t border-border">
                  <p className="text-xs text-muted-foreground mb-2">Exec into pod:</p>
                  <div className="flex items-center gap-2">
                    <code className="flex-1 bg-muted p-2 rounded-md font-mono text-xs break-all">
                      kubectl exec -it -n {namespace} {name} {selectedContainer ? `-c ${selectedContainer}` : ''} -- /bin/sh
                    </code>
                    <Button variant="outline" size="icon" onClick={copyExecCommand}>
                      {copiedCommand ? <Check className="h-4 w-4 text-success" /> : <Copy className="h-4 w-4" />}
                    </Button>
                  </div>
                </div>
              </CardContent>
            </Card>

            {/* Containers */}
            <Card className="lg:col-span-2">
              <CardHeader>
                <CardTitle className="text-base">Containers ({containers.length})</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="space-y-4">
                  {pod.spec.containers.map((container) => (
                    <div key={container.name} className="p-4 bg-muted/50 rounded-lg">
                      <div className="flex items-start justify-between mb-3">
                        <div>
                          <p className="font-semibold">{container.name}</p>
                          <p className="text-xs text-muted-foreground font-mono mt-1">{container.image}</p>
                        </div>
                        <Badge variant="outline">
                          {container.ports?.length || 0} ports
                        </Badge>
                      </div>
                      
                      {container.ports && container.ports.length > 0 && (
                        <div className="mt-2">
                          <span className="text-xs text-muted-foreground">Ports:</span>
                          <div className="flex flex-wrap gap-1 mt-1">
                            {container.ports.map((port, idx) => (
                              <Badge key={idx} variant="secondary" className="text-xs">
                                {port.containerPort}
                              </Badge>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>

            {/* Environment Variables */}
            <Card className="lg:col-span-2">
              <CardHeader>
                <CardTitle className="text-base">Environment Variables</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="space-y-4">
                  {pod.spec.containers.map((container) => {
                    const envVars = container.env || [];
                    if (envVars.length === 0) return null;
                    
                    return (
                      <div key={container.name} className="space-y-2">
                        {containers.length > 1 && (
                          <p className="text-sm font-medium text-muted-foreground">{container.name}</p>
                        )}
                        <div className="bg-muted/30 rounded-lg overflow-hidden">
                          <table className="w-full text-xs">
                            <thead>
                              <tr className="border-b border-border">
                                <th className="text-left p-2 font-medium text-muted-foreground w-1/3">Name</th>
                                <th className="text-left p-2 font-medium text-muted-foreground">Value / Source</th>
                              </tr>
                            </thead>
                            <tbody>
                              {envVars.map((env, idx) => (
                                <tr key={idx} className="border-b border-border/50 last:border-0">
                                  <td className="p-2 font-mono font-medium">{env.name}</td>
                                  <td className="p-2 font-mono text-muted-foreground break-all">
                                    {env.value ? (
                                      <span className="text-foreground">{env.value.length > 100 ? env.value.substring(0, 100) + '...' : env.value}</span>
                                    ) : env.valueFrom?.secretKeyRef ? (
                                      <Badge variant="outline" className="text-xs">
                                        Secret: {env.valueFrom.secretKeyRef.name}/{env.valueFrom.secretKeyRef.key}
                                      </Badge>
                                    ) : env.valueFrom?.configMapKeyRef ? (
                                      <Badge variant="secondary" className="text-xs">
                                        ConfigMap: {env.valueFrom.configMapKeyRef.name}/{env.valueFrom.configMapKeyRef.key}
                                      </Badge>
                                    ) : (
                                      <span className="italic text-muted-foreground">-</span>
                                    )}
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      </div>
                    );
                  })}
                  {pod.spec.containers.every(c => !c.env || c.env.length === 0) && (
                    <p className="text-sm text-muted-foreground italic">No environment variables configured</p>
                  )}
                </div>
              </CardContent>
            </Card>

            {/* Labels & Annotations */}
            {(pod.metadata.labels || pod.metadata.annotations) && (
              <Card className="lg:col-span-2">
                <CardHeader>
                  <CardTitle className="text-base">Labels & Annotations</CardTitle>
                </CardHeader>
                <CardContent className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                  {pod.metadata.labels && Object.keys(pod.metadata.labels).length > 0 && (
                    <div>
                      <h4 className="text-sm font-medium mb-2">Labels</h4>
                      <div className="flex flex-wrap gap-1">
                        {Object.entries(pod.metadata.labels).map(([key, value]) => (
                          <Badge key={key} variant="secondary" className="text-xs font-mono">
                            {key}={value}
                          </Badge>
                        ))}
                      </div>
                    </div>
                  )}
                  {pod.metadata.annotations && Object.keys(pod.metadata.annotations).length > 0 && (
                    <div>
                      <h4 className="text-sm font-medium mb-2">Annotations</h4>
                      <div className="space-y-1 text-xs">
                        {Object.entries(pod.metadata.annotations).slice(0, 5).map(([key, value]) => (
                          <div key={key} className="font-mono bg-muted/50 p-2 rounded">
                            <span className="text-muted-foreground">{key}:</span> {String(value).substring(0, 100)}
                          </div>
                        ))}
                        {Object.keys(pod.metadata.annotations).length > 5 && (
                          <p className="text-muted-foreground">+{Object.keys(pod.metadata.annotations).length - 5} more</p>
                        )}
                      </div>
                    </div>
                  )}
                </CardContent>
              </Card>
            )}
          </div>
        </TabsContent>

        {/* Logs Tab */}
        <TabsContent value="logs" className="space-y-4">
          {/* Logs Controls */}
          <div className="flex items-center gap-2 flex-wrap">
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
            
            <Button
              variant={autoRefresh ? "default" : "outline"}
              size="sm"
              onClick={() => setAutoRefresh(!autoRefresh)}
            >
              <RefreshCw className={`h-4 w-4 mr-2 ${autoRefresh ? 'animate-spin' : ''}`} />
              Auto
            </Button>
            
            <Button variant="outline" size="sm" onClick={fetchLogs} disabled={logsLoading}>
              <RefreshCw className={`h-4 w-4 ${logsLoading ? 'animate-spin' : ''}`} />
            </Button>
            
            <Button variant="outline" size="sm" onClick={handleDownload} disabled={!logs}>
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
        </TabsContent>

        {/* YAML Tab */}
        <TabsContent value="yaml" className="space-y-6">
          <YamlViewer resource={pod} title="Pod YAML" maxHeight="calc(100vh - 380px)" />
        </TabsContent>
      </Tabs>
    </div>
  );
}
