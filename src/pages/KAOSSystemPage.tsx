import React, { useState, useEffect, useCallback, useRef } from 'react';
import { RefreshCw, Settings, AlertCircle, ExternalLink, FileText, Info, FileCode, Download, Terminal } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Input } from '@/components/ui/input';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { useKubernetesConnection } from '@/contexts/KubernetesConnectionContext';
import { k8sClient } from '@/lib/kubernetes-client';
import { YamlViewer } from '@/components/shared/YamlViewer';
import type { Pod, Deployment, ConfigMap } from '@/types/kubernetes';

const KAOS_NAMESPACE_KEY = 'kaos-system-namespace';
const DEFAULT_KAOS_NAMESPACE = 'kaos-system';

// Interface for parsed MCP runtime configuration
interface MCPRuntime {
  name: string;
  image?: string;
  command?: string[];
  args?: string[];
  env?: { name: string; value?: string }[];
  ports?: { containerPort: number; protocol?: string }[];
  [key: string]: unknown;
}

export default function KAOSSystemPage() {
  const { connected, baseUrl } = useKubernetesConnection();
  
  const [kaosNamespace, setKaosNamespace] = useState(() => 
    localStorage.getItem(KAOS_NAMESPACE_KEY) || DEFAULT_KAOS_NAMESPACE
  );
  const [editingNamespace, setEditingNamespace] = useState(false);
  const [tempNamespace, setTempNamespace] = useState(kaosNamespace);
  
  const [operatorPods, setOperatorPods] = useState<Pod[]>([]);
  const [operatorDeployments, setOperatorDeployments] = useState<Deployment[]>([]);
  const [operatorConfig, setOperatorConfig] = useState<ConfigMap | null>(null);
  const [mcpRuntimes, setMcpRuntimes] = useState<ConfigMap | null>(null);
  const [parsedRuntimes, setParsedRuntimes] = useState<MCPRuntime[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [currentTab, setCurrentTab] = useState('overview');
  const [selectedPod, setSelectedPod] = useState<Pod | null>(null);
  
  // Logs state
  const [logs, setLogs] = useState<string>('');
  const [logsLoading, setLogsLoading] = useState(false);
  const [logsError, setLogsError] = useState<string | null>(null);
  const [selectedContainer, setSelectedContainer] = useState<string>('');
  const [tailLines, setTailLines] = useState<number>(200);
  const [autoRefresh, setAutoRefresh] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  // Parse MCP runtimes ConfigMap data
  const parseRuntimes = useCallback((configMap: ConfigMap) => {
    const runtimes: MCPRuntime[] = [];
    if (configMap.data) {
      for (const [name, value] of Object.entries(configMap.data)) {
        try {
          // Try to parse as JSON first (simpler for our display)
          const parsed = JSON.parse(value);
          runtimes.push({ name, ...parsed });
        } catch {
          // If not JSON, try to parse as YAML-like structure
          // For now, just store the raw value
          runtimes.push({ name, rawConfig: value } as MCPRuntime);
        }
      }
    }
    return runtimes;
  }, []);

  const fetchKAOSResources = useCallback(async () => {
    if (!connected || !baseUrl) return;
    
    setLoading(true);
    setError(null);
    
    try {
      // Fetch pods from KAOS system namespace
      const podsResponse = await fetch(`${baseUrl}/api/v1/namespaces/${kaosNamespace}/pods`, {
        headers: {
          'bypass-tunnel-reminder': '1',
          'X-Requested-With': 'XMLHttpRequest',
        },
      });
      
      if (!podsResponse.ok) {
        if (podsResponse.status === 404) {
          setError(`Namespace "${kaosNamespace}" not found`);
          setOperatorPods([]);
          return;
        }
        throw new Error(`Failed to fetch pods: ${podsResponse.statusText}`);
      }
      
      const podsData = await podsResponse.json();
      // Filter for KAOS controller/operator pods
      const kaosPods = (podsData.items || []).filter((pod: Pod) => 
        pod.metadata.name.includes('kaos') || 
        pod.metadata.labels?.['app.kubernetes.io/name']?.includes('kaos') ||
        pod.metadata.labels?.['app']?.includes('kaos')
      );
      setOperatorPods(kaosPods);
      
      if (kaosPods.length > 0 && !selectedPod) {
        setSelectedPod(kaosPods[0]);
      }
      
      // Fetch deployments
      const deploymentsResponse = await fetch(`${baseUrl}/apis/apps/v1/namespaces/${kaosNamespace}/deployments`, {
        headers: {
          'bypass-tunnel-reminder': '1',
          'X-Requested-With': 'XMLHttpRequest',
        },
      });
      
      if (deploymentsResponse.ok) {
        const deploymentsData = await deploymentsResponse.json();
        const kaosDeployments = (deploymentsData.items || []).filter((d: Deployment) =>
          d.metadata.name.includes('kaos')
        );
        setOperatorDeployments(kaosDeployments);
      }
      
      // Fetch kaos-operator-config ConfigMap
      try {
        const configResponse = await fetch(`${baseUrl}/api/v1/namespaces/${kaosNamespace}/configmaps/kaos-operator-config`, {
          headers: {
            'bypass-tunnel-reminder': '1',
            'X-Requested-With': 'XMLHttpRequest',
          },
        });
        if (configResponse.ok) {
          const configData = await configResponse.json();
          setOperatorConfig(configData);
        } else {
          setOperatorConfig(null);
        }
      } catch {
        setOperatorConfig(null);
      }
      
      // Fetch kaos-mcp-runtimes ConfigMap
      try {
        const runtimesResponse = await fetch(`${baseUrl}/api/v1/namespaces/${kaosNamespace}/configmaps/kaos-mcp-runtimes`, {
          headers: {
            'bypass-tunnel-reminder': '1',
            'X-Requested-With': 'XMLHttpRequest',
          },
        });
        if (runtimesResponse.ok) {
          const runtimesData = await runtimesResponse.json();
          setMcpRuntimes(runtimesData);
          setParsedRuntimes(parseRuntimes(runtimesData));
        } else {
          setMcpRuntimes(null);
          setParsedRuntimes([]);
        }
      } catch {
        setMcpRuntimes(null);
        setParsedRuntimes([]);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch KAOS resources');
    } finally {
      setLoading(false);
    }
  }, [connected, baseUrl, kaosNamespace, selectedPod, parseRuntimes]);

  // Fetch logs for selected pod
  const fetchLogs = useCallback(async () => {
    if (!selectedPod || !baseUrl) return;
    
    setLogsLoading(true);
    setLogsError(null);
    
    try {
      const logContent = await k8sClient.getPodLogs(
        selectedPod.metadata.name, 
        selectedPod.metadata.namespace, 
        {
          container: selectedContainer || undefined,
          tailLines,
        }
      );
      setLogs(logContent);
      
      // Auto-scroll to bottom
      if (scrollRef.current) {
        scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
      }
    } catch (err) {
      setLogsError(err instanceof Error ? err.message : 'Failed to fetch logs');
      setLogs('');
    } finally {
      setLogsLoading(false);
    }
  }, [selectedPod, baseUrl, selectedContainer, tailLines]);

  useEffect(() => {
    fetchKAOSResources();
  }, [fetchKAOSResources]);

  // Fetch logs when tab changes to logs or pod/container changes
  useEffect(() => {
    if (currentTab === 'logs' && selectedPod) {
      fetchLogs();
    }
  }, [currentTab, selectedPod, selectedContainer, tailLines, fetchLogs]);

  // Auto-refresh logs
  useEffect(() => {
    if (!autoRefresh || currentTab !== 'logs') return;
    
    const interval = setInterval(fetchLogs, 5000);
    return () => clearInterval(interval);
  }, [autoRefresh, currentTab, fetchLogs]);

  // Set default container when pod is selected
  useEffect(() => {
    if (selectedPod && selectedPod.spec.containers.length > 0) {
      setSelectedContainer(selectedPod.spec.containers[0].name);
    }
  }, [selectedPod]);

  const handleSaveNamespace = () => {
    localStorage.setItem(KAOS_NAMESPACE_KEY, tempNamespace);
    setKaosNamespace(tempNamespace);
    setEditingNamespace(false);
    setSelectedPod(null);
  };

  const handleDownloadLogs = () => {
    const blob = new Blob([logs], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${selectedPod?.metadata.name}-${selectedContainer || 'logs'}.txt`;
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

  const containers = selectedPod?.spec?.containers?.map(c => c.name) || [];

  if (!connected) {
    return (
      <div className="flex flex-col items-center justify-center h-full p-8">
        <div className="text-center">
          <Settings className="h-12 w-12 text-muted-foreground mx-auto mb-4" />
          <h2 className="text-xl font-semibold mb-2">Not Connected</h2>
          <p className="text-muted-foreground">
            Please connect to a Kubernetes cluster first.
          </p>
        </div>
      </div>
    );
  }

  const showNotInstalled = !loading && (error || operatorPods.length === 0);

  return (
    <div className="p-6 space-y-6">
      {/* Page Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="h-12 w-12 rounded-xl bg-primary/10 flex items-center justify-center">
            <Settings className="h-6 w-6 text-primary" />
          </div>
          <div>
            <h1 className="text-2xl font-bold text-foreground">KAOS System</h1>
            <p className="text-sm text-muted-foreground">
              Operator installation and configuration
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {editingNamespace ? (
            <div className="flex items-center gap-2">
              <Input
                value={tempNamespace}
                onChange={(e) => setTempNamespace(e.target.value)}
                className="w-40 h-8 text-sm"
                placeholder="Namespace"
              />
              <Button size="sm" onClick={handleSaveNamespace}>Save</Button>
              <Button size="sm" variant="outline" onClick={() => {
                setEditingNamespace(false);
                setTempNamespace(kaosNamespace);
              }}>Cancel</Button>
            </div>
          ) : (
            <Button variant="outline" size="sm" onClick={() => setEditingNamespace(true)}>
              <span className="text-xs text-muted-foreground mr-2">Namespace:</span>
              <code className="text-xs">{kaosNamespace}</code>
            </Button>
          )}
          <Button variant="outline" size="sm" onClick={fetchKAOSResources} disabled={loading}>
            <RefreshCw className={`h-4 w-4 mr-2 ${loading ? 'animate-spin' : ''}`} />
            Refresh
          </Button>
        </div>
      </div>

      {showNotInstalled ? (
        <Alert>
          <AlertCircle className="h-4 w-4" />
          <AlertTitle>KAOS Not Found</AlertTitle>
          <AlertDescription className="space-y-3">
            <p>
              No KAOS operator installation found in namespace <code className="bg-muted px-1 rounded">{kaosNamespace}</code>.
            </p>
            <p>
              Please install KAOS or configure the correct namespace using the button above.
            </p>
            <Button variant="outline" size="sm" asChild>
              <a href="https://axsaucedo.github.io/kaos/" target="_blank" rel="noopener noreferrer">
                <ExternalLink className="h-4 w-4 mr-2" />
                View Installation Docs
              </a>
            </Button>
          </AlertDescription>
        </Alert>
      ) : (
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
              {/* Operator Status */}
              <Card>
                <CardHeader>
                  <CardTitle className="text-base">Operator Status</CardTitle>
                  <CardDescription>KAOS controller manager health</CardDescription>
                </CardHeader>
                <CardContent className="space-y-4">
                  {operatorDeployments.map((deployment) => (
                    <div key={deployment.metadata.name} className="p-3 bg-muted/50 rounded-lg">
                      <div className="flex items-center justify-between mb-2">
                        <span className="font-medium">{deployment.metadata.name}</span>
                        <Badge variant={
                          deployment.status?.readyReplicas === deployment.status?.replicas ? 'success' : 'warning'
                        }>
                          {deployment.status?.readyReplicas || 0}/{deployment.status?.replicas || 0} Ready
                        </Badge>
                      </div>
                      <p className="text-xs text-muted-foreground">
                        Replicas: {deployment.spec.replicas}
                      </p>
                    </div>
                  ))}
                  {operatorDeployments.length === 0 && (
                    <p className="text-sm text-muted-foreground italic">No deployments found</p>
                  )}
                </CardContent>
              </Card>

              {/* Pods Summary */}
              <Card>
                <CardHeader>
                  <CardTitle className="text-base">Running Pods</CardTitle>
                  <CardDescription>KAOS system pods in {kaosNamespace}</CardDescription>
                </CardHeader>
                <CardContent className="space-y-2">
                  {operatorPods.map((pod) => (
                    <div
                      key={pod.metadata.name}
                      className={`p-3 rounded-lg cursor-pointer transition-colors ${
                        selectedPod?.metadata.name === pod.metadata.name
                          ? 'bg-primary/10 border border-primary/20'
                          : 'bg-muted/50 hover:bg-muted'
                      }`}
                      onClick={() => setSelectedPod(pod)}
                    >
                      <div className="flex items-center justify-between">
                        <span className="font-mono text-sm">{pod.metadata.name}</span>
                        <Badge variant={pod.status?.phase === 'Running' ? 'success' : 'warning'}>
                          {pod.status?.phase}
                        </Badge>
                      </div>
                    </div>
                  ))}
                </CardContent>
              </Card>

              {/* Operator Configuration ConfigMap */}
              <Card className="lg:col-span-2">
                <CardHeader>
                  <CardTitle className="text-base flex items-center gap-2">
                    <FileText className="h-4 w-4 text-muted-foreground" />
                    Operator Configuration
                  </CardTitle>
                  <CardDescription>kaos-operator-config ConfigMap</CardDescription>
                </CardHeader>
                <CardContent>
                  {operatorConfig && operatorConfig.data ? (
                    <div className="bg-muted/30 rounded-lg overflow-hidden">
                      <table className="w-full text-xs">
                        <thead>
                          <tr className="border-b border-border">
                            <th className="text-left p-2 font-medium text-muted-foreground w-1/3">Key</th>
                            <th className="text-left p-2 font-medium text-muted-foreground">Value</th>
                          </tr>
                        </thead>
                        <tbody>
                          {Object.entries(operatorConfig.data).map(([key, value]) => (
                            <tr key={key} className="border-b border-border/50 last:border-0">
                              <td className="p-2 font-mono font-medium">{key}</td>
                              <td className="p-2 font-mono text-muted-foreground break-all">
                                <span className="text-foreground">
                                  {value.length > 100 ? value.substring(0, 100) + '...' : value}
                                </span>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  ) : (
                    <p className="text-sm text-muted-foreground italic">
                      ConfigMap kaos-operator-config not found
                    </p>
                  )}
                </CardContent>
              </Card>

              {/* MCP Runtimes ConfigMap */}
              <Card className="lg:col-span-2">
                <CardHeader>
                  <CardTitle className="text-base flex items-center gap-2">
                    <FileText className="h-4 w-4 text-muted-foreground" />
                    MCP Runtimes
                  </CardTitle>
                  <CardDescription>kaos-mcp-runtimes ConfigMap - Available runtime configurations</CardDescription>
                </CardHeader>
                <CardContent>
                  {mcpRuntimes && mcpRuntimes.data && Object.keys(mcpRuntimes.data).length > 0 ? (
                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                      {Object.entries(mcpRuntimes.data).map(([runtimeName, runtimeConfig]) => {
                        // Try to parse the runtime config
                        let parsed: Record<string, unknown> = {};
                        try {
                          parsed = JSON.parse(runtimeConfig);
                        } catch {
                          // Not JSON, might be YAML - display raw
                        }
                        
                        return (
                          <Card key={runtimeName} className="bg-muted/30 border-muted">
                            <CardHeader className="pb-2">
                              <CardTitle className="text-sm font-mono">{runtimeName}</CardTitle>
                            </CardHeader>
                            <CardContent className="text-xs space-y-2">
                              {parsed.image && (
                                <div>
                                  <span className="text-muted-foreground">Image: </span>
                                  <span className="font-mono text-foreground break-all">{String(parsed.image)}</span>
                                </div>
                              )}
                              {parsed.command && Array.isArray(parsed.command) && (
                                <div>
                                  <span className="text-muted-foreground">Command: </span>
                                  <span className="font-mono text-foreground">{parsed.command.join(' ')}</span>
                                </div>
                              )}
                              {parsed.args && Array.isArray(parsed.args) && (
                                <div>
                                  <span className="text-muted-foreground">Args: </span>
                                  <span className="font-mono text-foreground">{parsed.args.join(' ')}</span>
                                </div>
                              )}
                              {parsed.ports && Array.isArray(parsed.ports) && parsed.ports.length > 0 && (
                                <div>
                                  <span className="text-muted-foreground">Ports: </span>
                                  <span className="font-mono text-foreground">
                                    {(parsed.ports as Array<{ containerPort?: number }>).map(p => p.containerPort).join(', ')}
                                  </span>
                                </div>
                              )}
                              {!parsed.image && !parsed.command && (
                                <ScrollArea className="h-24">
                                  <pre className="font-mono text-foreground whitespace-pre-wrap break-all">
                                    {runtimeConfig.length > 200 ? runtimeConfig.substring(0, 200) + '...' : runtimeConfig}
                                  </pre>
                                </ScrollArea>
                              )}
                            </CardContent>
                          </Card>
                        );
                      })}
                    </div>
                  ) : (
                    <p className="text-sm text-muted-foreground italic">
                      ConfigMap kaos-mcp-runtimes not found or empty
                    </p>
                  )}
                </CardContent>
              </Card>

              {/* Environment Variables */}
              {selectedPod && (
                <Card className="lg:col-span-2">
                  <CardHeader>
                    <CardTitle className="text-base">Environment Variables</CardTitle>
                    <CardDescription>Configuration for {selectedPod.metadata.name}</CardDescription>
                  </CardHeader>
                  <CardContent>
                    <ScrollArea className="h-[400px]">
                      <div className="space-y-4">
                        {selectedPod.spec.containers.map((container) => {
                          const envVars = container.env || [];
                          
                          return (
                            <div key={container.name} className="space-y-2">
                              <p className="text-sm font-medium text-muted-foreground">{container.name}</p>
                              {envVars.length > 0 ? (
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
                                              <span className="text-foreground">
                                                {env.value.length > 80 ? env.value.substring(0, 80) + '...' : env.value}
                                              </span>
                                            ) : env.valueFrom?.secretKeyRef ? (
                                              <Badge variant="outline" className="text-xs">
                                                Secret: {env.valueFrom.secretKeyRef.name}/{env.valueFrom.secretKeyRef.key}
                                              </Badge>
                                            ) : (
                                              <span className="italic">-</span>
                                            )}
                                          </td>
                                        </tr>
                                      ))}
                                    </tbody>
                                  </table>
                                </div>
                              ) : (
                                <p className="text-sm text-muted-foreground italic">No environment variables</p>
                              )}
                            </div>
                          );
                        })}
                      </div>
                    </ScrollArea>
                  </CardContent>
                </Card>
              )}
            </div>
          </TabsContent>

          {/* Logs Tab */}
          <TabsContent value="logs" className="space-y-4">
            {/* Logs Controls */}
            <div className="flex items-center justify-between gap-4 flex-wrap">
              <div className="flex items-center gap-2">
                {/* Pod selector */}
                <Select 
                  value={selectedPod?.metadata.name || ''} 
                  onValueChange={(name) => {
                    const pod = operatorPods.find(p => p.metadata.name === name);
                    if (pod) setSelectedPod(pod);
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
          </TabsContent>

          {/* YAML Tab */}
          <TabsContent value="yaml" className="space-y-4">
            {selectedPod && (
              <YamlViewer 
                resource={selectedPod} 
                title={`${selectedPod.metadata.name} YAML`} 
              />
            )}
            {!selectedPod && (
              <p className="text-muted-foreground">Select a pod to view its YAML</p>
            )}
          </TabsContent>
        </Tabs>
      )}
    </div>
  );
}
