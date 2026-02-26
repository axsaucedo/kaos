import { useState, useEffect } from 'react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Loader2, CheckCircle, XCircle, RefreshCw, Wifi, WifiOff } from 'lucide-react';
import { k8sClient } from '@/lib/kubernetes-client';
import { useToast } from '@/hooks/use-toast';
import { ConnectionDiagnostics } from './ConnectionDiagnostics';
import { CRUDTestPanel } from './CRUDTestPanel';
import { useKubernetesConnection } from '@/contexts/KubernetesConnectionContext';

export function ConnectionSettings() {
  const { toast } = useToast();
  const k8sConnection = useKubernetesConnection();
  
  const DEFAULT_URL = 'http://localhost:8010';
  
  const [baseUrl, setBaseUrl] = useState(DEFAULT_URL);
  const [namespace, setNamespace] = useState('default');
  const [namespaces, setNamespaces] = useState<string[]>([]);
  const [version, setVersion] = useState<string | null>(null);

  // Load saved config on mount (or use default)
  useEffect(() => {
    const savedConfig = localStorage.getItem('k8s-config');
    if (savedConfig) {
      try {
        const config = JSON.parse(savedConfig);
        setBaseUrl(config.baseUrl || DEFAULT_URL);
        setNamespace(config.namespace || 'default');
      } catch (e) {
        console.error('Failed to parse saved config:', e);
        setBaseUrl(DEFAULT_URL);
      }
    } else {
      setBaseUrl(DEFAULT_URL);
    }
  }, []);

  // Sync connection state
  useEffect(() => {
    if (k8sConnection.connected) {
      setBaseUrl(k8sConnection.baseUrl);
      setNamespace(k8sConnection.namespace);
    }
  }, [k8sConnection.connected, k8sConnection.baseUrl, k8sConnection.namespace]);

  const handleConnect = async () => {
    if (!baseUrl) {
      toast({
        title: 'Error',
        description: 'Please enter a Kubernetes API URL',
        variant: 'destructive',
      });
      return;
    }

    const cleanUrl = baseUrl.replace(/\/$/, '');
    const success = await k8sConnection.connect(cleanUrl, namespace);

    if (success) {
      // Save config
      localStorage.setItem('k8s-config', JSON.stringify({ baseUrl: cleanUrl, namespace }));
      
      // Get version
      const result = await k8sClient.testConnection();
      if (result.version) {
        setVersion(result.version);
      }
      
      // Fetch namespaces
      try {
        const nsList = await k8sClient.listNamespaces();
        setNamespaces(nsList.map(ns => ns.metadata.name));
      } catch (e) {
        console.warn('Could not fetch namespaces:', e);
      }
      
      toast({
        title: 'Connected',
        description: `Connected to Kubernetes ${result.version || ''}`,
      });
    } else {
      toast({
        title: 'Connection Failed',
        description: k8sConnection.error || 'Unable to connect',
        variant: 'destructive',
      });
    }
  };

  const handleDisconnect = () => {
    k8sConnection.disconnect();
    localStorage.removeItem('k8s-config');
    setVersion(null);
    setNamespaces([]);
    toast({
      title: 'Disconnected',
      description: 'Disconnected from Kubernetes cluster',
    });
  };

  const handleNamespaceChange = async (value: string) => {
    setNamespace(value);
    // Reconnect with new namespace
    if (k8sConnection.connected && baseUrl) {
      await k8sConnection.connect(baseUrl, value);
      localStorage.setItem('k8s-config', JSON.stringify({ baseUrl, namespace: value }));
    }
  };

  const handleRefresh = async () => {
    await k8sConnection.refreshAll();
    toast({
      title: 'Refreshed',
      description: 'Resources synced from cluster',
    });
  };

  const connectionStatus = k8sConnection.connecting 
    ? 'connecting' 
    : k8sConnection.connected 
      ? 'connected' 
      : k8sConnection.error 
        ? 'error' 
        : 'disconnected';

  return (
    <div className="space-y-6 max-w-2xl">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            {connectionStatus === 'connected' ? (
              <Wifi className="h-5 w-5 text-green-500" />
            ) : (
              <WifiOff className="h-5 w-5 text-muted-foreground" />
            )}
            Kubernetes Connection
          </CardTitle>
          <CardDescription>
            Connect to your Kubernetes cluster via kubectl proxy
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {/* Status Badge */}
          <div className="flex items-center gap-2">
            <span className="text-sm text-muted-foreground">Status:</span>
            {connectionStatus === 'connected' && (
              <Badge variant="default" className="bg-green-600">
                <CheckCircle className="h-3 w-3 mr-1" />
                Connected {version && `(${version})`}
              </Badge>
            )}
            {connectionStatus === 'connecting' && (
              <Badge variant="secondary">
                <Loader2 className="h-3 w-3 mr-1 animate-spin" />
                Connecting...
              </Badge>
            )}
            {connectionStatus === 'error' && (
              <Badge variant="destructive">
                <XCircle className="h-3 w-3 mr-1" />
                Error
              </Badge>
            )}
            {connectionStatus === 'disconnected' && (
              <Badge variant="secondary">Disconnected</Badge>
            )}
          </div>

          {k8sConnection.error && (
            <div className="p-3 rounded-md bg-destructive/10 text-destructive text-sm">
              {k8sConnection.error}
            </div>
          )}

          {/* Last refresh */}
          {k8sConnection.lastRefresh && (
            <div className="text-xs text-muted-foreground">
              Last synced: {k8sConnection.lastRefresh.toLocaleTimeString()}
            </div>
          )}

          {/* API URL Input */}
          <div className="space-y-2">
            <Label htmlFor="baseUrl">Kubernetes API URL</Label>
            <Input
              id="baseUrl"
              placeholder="http://localhost:8010"
              value={baseUrl}
              onChange={(e) => setBaseUrl(e.target.value)}
              disabled={connectionStatus === 'connected'}
            />
            <p className="text-xs text-muted-foreground">
              Run <code className="bg-muted px-1 py-0.5 rounded">kaos ui</code> or{' '}
              <code className="bg-muted px-1 py-0.5 rounded">kaos ui --port=8010</code>
            </p>
          </div>

          {/* Namespace Selector */}
          <div className="space-y-2">
            <Label htmlFor="namespace">Namespace</Label>
            {namespaces.length > 0 ? (
              <Select value={namespace} onValueChange={handleNamespaceChange}>
                <SelectTrigger>
                  <SelectValue placeholder="Select namespace" />
                </SelectTrigger>
                <SelectContent>
                  {namespaces.map((ns) => (
                    <SelectItem key={ns} value={ns}>
                      {ns}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            ) : (
              <Input
                id="namespace"
                placeholder="default"
                value={namespace}
                onChange={(e) => setNamespace(e.target.value)}
              />
            )}
          </div>

          {/* Action Buttons */}
          <div className="flex gap-2">
            {connectionStatus !== 'connected' ? (
              <Button onClick={handleConnect} disabled={k8sConnection.connecting}>
                {k8sConnection.connecting ? (
                  <>
                    <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                    Connecting...
                  </>
                ) : (
                  'Connect'
                )}
              </Button>
            ) : (
              <>
                <Button variant="outline" onClick={handleRefresh}>
                  <RefreshCw className="h-4 w-4 mr-2" />
                  Refresh
                </Button>
                <Button variant="outline" onClick={handleConnect}>
                  <RefreshCw className="h-4 w-4 mr-2" />
                  Reconnect
                </Button>
                <Button variant="destructive" onClick={handleDisconnect}>
                  Disconnect
                </Button>
              </>
            )}
          </div>
        </CardContent>
      </Card>

      {/* Diagnostics Card */}
      <ConnectionDiagnostics />

      {/* CRUD Test Panel */}
      <CRUDTestPanel />

      {/* Instructions Card */}
      <Card>
        <CardHeader>
          <CardTitle>Setup Instructions</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <h4 className="font-medium">1. Start the UI with proxy</h4>
            <pre className="bg-muted p-3 rounded-md text-sm overflow-x-auto">
              kaos ui
            </pre>
            <p className="text-xs text-muted-foreground">
              Or specify a custom port: <code className="bg-muted px-1 py-0.5 rounded">kaos ui --port=8010</code>
            </p>
          </div>
          <div className="space-y-2">
            <h4 className="font-medium">2. Connect</h4>
            <p className="text-sm text-muted-foreground">
              Enter the Kubernetes proxy URL above (default: <code className="bg-muted px-1 py-0.5 rounded">http://localhost:8010</code>) 
              and click Connect.
            </p>
          </div>
          <div className="p-4 rounded-lg bg-amber-500/10 border border-amber-500/20 mt-4">
            <h4 className="font-medium text-amber-600 mb-2">⚠️ CORS Limitation</h4>
            <p className="text-sm text-muted-foreground">
              <code>kubectl proxy</code> doesn't handle CORS preflight requests, so direct browser 
              connections may fail. Use the <code className="bg-muted px-1 py-0.5 rounded">kaos ui</code> CLI which includes CORS support.
            </p>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
