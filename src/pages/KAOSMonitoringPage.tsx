import React, { useState, useEffect, useCallback } from 'react';
import { RefreshCw, Activity, AlertCircle, ExternalLink } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';

const LOCAL_PORT = 8011;
const LOCALHOST_URL = `http://localhost:${LOCAL_PORT}`;

export default function KAOSMonitoringPage() {
  const [portAvailable, setPortAvailable] = useState<boolean | null>(null);
  const [loading, setLoading] = useState(false);
  const [iframeError, setIframeError] = useState(false);

  const checkPort = useCallback(async () => {
    setLoading(true);
    setIframeError(false);

    try {
      await fetch(LOCALHOST_URL, { mode: 'no-cors', signal: AbortSignal.timeout(3000) });
      setPortAvailable(true);
    } catch {
      setPortAvailable(false);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    checkPort();
  }, [checkPort]);

  return (
    <div className="p-6 space-y-6 h-full flex flex-col">
      {/* Page Header */}
      <div className="flex items-center justify-between flex-shrink-0">
        <div className="flex items-center gap-3">
          <div className="h-12 w-12 rounded-xl bg-chart-1/10 flex items-center justify-center">
            <Activity className="h-6 w-6 text-chart-1" />
          </div>
          <div>
            <h1 className="text-2xl font-bold text-foreground">KAOS Monitoring</h1>
            <p className="text-sm text-muted-foreground">
              Observability dashboard (SigNoz / Jaeger)
            </p>
          </div>
        </div>

        <Button variant="outline" size="sm" onClick={checkPort} disabled={loading}>
          <RefreshCw className={`h-4 w-4 mr-2 ${loading ? 'animate-spin' : ''}`} />
          Refresh
        </Button>
      </div>

      {portAvailable === null ? null : !portAvailable ? (
        <Alert>
          <AlertCircle className="h-4 w-4" />
          <AlertTitle>Monitoring Not Available</AlertTitle>
          <AlertDescription className="space-y-3">
            <p>
              No monitoring dashboard detected on <code className="bg-muted px-1 rounded">localhost:{LOCAL_PORT}</code>.
            </p>
            <p>Start port-forwarding with the KAOS CLI:</p>
            <code className="block bg-muted p-2 rounded text-xs">
              kaos ui --monitoring-enabled signoz
            </code>
            <p className="text-xs text-muted-foreground">
              or use <code>jaeger</code> as the backend. Then refresh this page.
            </p>
            <Button variant="outline" size="sm" asChild>
              <a href="https://axsaucedo.github.io/kaos/" target="_blank" rel="noopener noreferrer">
                <ExternalLink className="h-4 w-4 mr-2" />
                View KAOS Installation Docs
              </a>
            </Button>
          </AlertDescription>
        </Alert>
      ) : iframeError ? (
        <div className="flex flex-col items-center justify-center flex-1 p-8 bg-muted/20 rounded-lg border border-border">
          <AlertCircle className="h-12 w-12 text-muted-foreground mb-4" />
          <h3 className="text-lg font-medium mb-2">Unable to Embed Dashboard</h3>
          <p className="text-sm text-muted-foreground mb-4 text-center max-w-md">
            The monitoring dashboard could not be embedded. This may be due to security restrictions.
          </p>
          <Button asChild>
            <a href={LOCALHOST_URL} target="_blank" rel="noopener noreferrer">
              <ExternalLink className="h-4 w-4 mr-2" />
              Open in New Tab
            </a>
          </Button>
        </div>
      ) : (
        <div className="flex-1 min-h-0 rounded-lg border border-border overflow-hidden">
          <iframe
            src={LOCALHOST_URL}
            className="w-full h-full border-0"
            title="Monitoring Dashboard"
            onError={() => setIframeError(true)}
          />
        </div>
      )}
    </div>
  );
}
