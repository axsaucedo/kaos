import React, { useState } from 'react';
import { RefreshCw, Settings, AlertCircle, ExternalLink, Info, FileCode, Terminal } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { useKubernetesConnection } from '@/contexts/KubernetesConnectionContext';
import { YamlViewer } from '@/components/shared/YamlViewer';
import NamespaceManager from './system/NamespaceManager';
import SystemOverview from './system/SystemOverview';
import OperatorConfig from './system/OperatorConfig';
import SystemLogs from './system/SystemLogs';
import { useKAOSResources } from './system/useKAOSResources';

const KAOS_NAMESPACE_KEY = 'kaos-system-namespace';
const DEFAULT_KAOS_NAMESPACE = 'kaos-system';

export default function KAOSSystemPage() {
  const { connected, baseUrl } = useKubernetesConnection();
  
  const [kaosNamespace, setKaosNamespace] = useState(() => 
    localStorage.getItem(KAOS_NAMESPACE_KEY) || DEFAULT_KAOS_NAMESPACE
  );
  const [editingNamespace, setEditingNamespace] = useState(false);
  const [tempNamespace, setTempNamespace] = useState(kaosNamespace);
  const [currentTab, setCurrentTab] = useState('overview');

  const {
    operatorPods, operatorDeployments, operatorConfig, mcpRuntimes,
    loading, error, selectedPod, setSelectedPod, fetchKAOSResources,
  } = useKAOSResources(connected, baseUrl, kaosNamespace);

  const handleSaveNamespace = () => {
    localStorage.setItem(KAOS_NAMESPACE_KEY, tempNamespace);
    setKaosNamespace(tempNamespace);
    setEditingNamespace(false);
    setSelectedPod(null);
  };

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
          <NamespaceManager
            kaosNamespace={kaosNamespace}
            editingNamespace={editingNamespace}
            tempNamespace={tempNamespace}
            onEditStart={() => setEditingNamespace(true)}
            onEditCancel={() => {
              setEditingNamespace(false);
              setTempNamespace(kaosNamespace);
            }}
            onTempNamespaceChange={setTempNamespace}
            onSave={handleSaveNamespace}
          />
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

          <TabsContent value="overview" className="space-y-6">
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              <SystemOverview
                operatorDeployments={operatorDeployments}
                operatorPods={operatorPods}
                selectedPod={selectedPod}
                onSelectPod={setSelectedPod}
                kaosNamespace={kaosNamespace}
              />
              <OperatorConfig
                operatorConfig={operatorConfig}
                mcpRuntimes={mcpRuntimes}
                selectedPod={selectedPod}
              />
            </div>
          </TabsContent>

          <TabsContent value="logs" className="space-y-4">
            <SystemLogs
              selectedPod={selectedPod}
              operatorPods={operatorPods}
              onSelectPod={setSelectedPod}
              active={currentTab === 'logs'}
            />
          </TabsContent>

          <TabsContent value="yaml" className="space-y-4">
            {selectedPod ? (
              <YamlViewer 
                resource={selectedPod} 
                title={`${selectedPod.metadata.name} YAML`} 
              />
            ) : (
              <p className="text-muted-foreground">Select a pod to view its YAML</p>
            )}
          </TabsContent>
        </Tabs>
      )}
    </div>
  );
}
