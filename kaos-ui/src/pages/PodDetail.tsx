import React, { useState, useEffect } from 'react';
import { useParams, useNavigate, useSearchParams } from 'react-router-dom';
import { ArrowLeft, Boxes, RefreshCw, Info, Terminal, FileCode } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { useKubernetesStore } from '@/stores/kubernetesStore';
import { useKubernetesConnection } from '@/contexts/KubernetesConnectionContext';
import { YamlViewer } from '@/components/shared/YamlViewer';
import { usePodLogs } from '@/hooks/usePodLogs';
import { PodOverviewTab } from '@/components/kubernetes/PodOverviewTab';
import { PodLogsTab } from '@/components/kubernetes/PodLogsTab';

export default function PodDetail() {
  const { namespace, name } = useParams<{ namespace: string; name: string }>();
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  
  const returnPath = searchParams.get('returnTo');
  const initialTab = searchParams.get('tab') || 'overview';
  
  const { pods } = useKubernetesStore();
  const { connected, refreshAll } = useKubernetesConnection();
  
  const [currentTab, setCurrentTab] = useState(initialTab);
  const [selectedContainer, setSelectedContainer] = useState<string>('');
  const [copiedCommand, setCopiedCommand] = useState(false);

  const pod = pods.find(p => p.metadata.name === name && p.metadata.namespace === namespace);
  const containers = pod?.spec?.containers?.map(c => c.name) || [];

  // Set default container when pod is loaded
  useEffect(() => {
    if (containers.length > 0 && !selectedContainer) {
      setSelectedContainer(containers[0]);
    }
  }, [containers, selectedContainer]);

  const {
    logs, logsLoading, logsError,
    tailLines, setTailLines,
    autoRefresh, setAutoRefresh,
    scrollRef, fetchLogs, handleDownload,
  } = usePodLogs({ namespace, podName: name, containerName: selectedContainer, active: currentTab === 'logs' });

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
          <PodOverviewTab
            pod={pod}
            containers={containers}
            namespace={namespace}
            name={name}
            selectedContainer={selectedContainer}
            copiedCommand={copiedCommand}
            onCopyExecCommand={copyExecCommand}
          />
        </TabsContent>

        {/* Logs Tab */}
        <TabsContent value="logs" className="space-y-4">
          <PodLogsTab
            containers={containers}
            selectedContainer={selectedContainer}
            onContainerChange={setSelectedContainer}
            logs={logs}
            logsLoading={logsLoading}
            logsError={logsError}
            tailLines={tailLines}
            onTailLinesChange={setTailLines}
            autoRefresh={autoRefresh}
            onAutoRefreshToggle={() => setAutoRefresh(!autoRefresh)}
            scrollRef={scrollRef}
            onFetchLogs={fetchLogs}
            onDownload={handleDownload}
          />
        </TabsContent>

        {/* YAML Tab */}
        <TabsContent value="yaml" className="space-y-6">
          <YamlViewer resource={pod} title="Pod YAML" maxHeight="calc(100vh - 380px)" />
        </TabsContent>
      </Tabs>
    </div>
  );
}
