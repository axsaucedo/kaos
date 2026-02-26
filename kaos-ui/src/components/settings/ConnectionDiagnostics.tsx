import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Loader2, CheckCircle, XCircle, AlertTriangle, Info } from 'lucide-react';

interface TestResult {
  name: string;
  status: 'pending' | 'running' | 'success' | 'error' | 'warning';
  message: string;
  details?: string;
}

export function ConnectionDiagnostics() {
  const [proxyUrl, setProxyUrl] = useState('');
  const [isRunning, setIsRunning] = useState(false);
  const [results, setResults] = useState<TestResult[]>([]);

  const updateResult = (index: number, update: Partial<TestResult>) => {
    setResults(prev => prev.map((r, i) => i === index ? { ...r, ...update } : r));
  };

  const runDiagnostics = async () => {
    if (!proxyUrl) return;

    const cleanUrl = proxyUrl.replace(/\/$/, '');
    setIsRunning(true);

    // Initialize all tests
    const initialResults: TestResult[] = [
      { name: 'URL Format', status: 'pending', message: 'Checking URL format...' },
      { name: 'Simple GET Request', status: 'pending', message: 'Testing connection to proxy...' },
      { name: 'CORS Headers Check', status: 'pending', message: 'Checking if CORS headers are present...' },
      { name: 'K8s API Response', status: 'pending', message: 'Validating Kubernetes API response...' },
    ];
    setResults(initialResults);

    // Test 1: URL Format
    await new Promise(r => setTimeout(r, 200));
    try {
      const url = new URL(cleanUrl);
      if (url.protocol !== 'https:' && url.protocol !== 'http:') {
        updateResult(0, { status: 'error', message: 'Invalid protocol', details: 'URL must start with http:// or https://' });
        setIsRunning(false);
        return;
      }
      updateResult(0, { 
        status: 'success', 
        message: 'Valid URL', 
        details: url.hostname 
      });
    } catch (e) {
      updateResult(0, { status: 'error', message: 'Invalid URL format', details: String(e) });
      setIsRunning(false);
      return;
    }

    // Test 2: Simple GET request
    updateResult(1, { status: 'running', message: 'Testing connection...' });
    await new Promise(r => setTimeout(r, 200));
    
    let getWorked = false;
    let responseData: any = null;
    
    try {
      const response = await fetch(`${cleanUrl}/version`);
      
      if (response.ok) {
        responseData = await response.json();
        getWorked = true;
        updateResult(1, { 
          status: 'success', 
          message: 'Connection successful!', 
          details: `K8s ${responseData.gitVersion || 'responded'}` 
        });
      } else {
        const text = await response.text();
        updateResult(1, { 
          status: 'error', 
          message: `HTTP ${response.status}`, 
          details: text.slice(0, 200) 
        });
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : 'Unknown';
      updateResult(1, { 
        status: 'error', 
        message: 'Request failed', 
        details: msg 
      });
    }

    // Test 3: Check CORS headers
    updateResult(2, { status: 'running', message: 'Checking CORS configuration...' });
    await new Promise(r => setTimeout(r, 200));
    
    try {
      const response = await fetch(`${cleanUrl}/version`, {
        method: 'OPTIONS',
      });
      
      const corsOrigin = response.headers.get('Access-Control-Allow-Origin');
      const corsMethods = response.headers.get('Access-Control-Allow-Methods');
      const corsHeaders = response.headers.get('Access-Control-Allow-Headers');
      
      if (response.status === 405) {
        updateResult(2, { 
          status: 'warning', 
          message: 'OPTIONS returns 405', 
          details: `kubectl proxy doesn't handle OPTIONS. CORS Origin: ${corsOrigin || 'not set'}. Use kaos ui for CORS support.` 
        });
      } else if (corsOrigin) {
        updateResult(2, { 
          status: 'success', 
          message: 'CORS headers present', 
          details: `Origin: ${corsOrigin}, Methods: ${corsMethods || 'not set'}, Headers: ${corsHeaders || 'not set'}` 
        });
      } else {
        updateResult(2, { 
          status: 'warning', 
          message: 'No CORS headers in OPTIONS response', 
          details: `Status: ${response.status}` 
        });
      }
    } catch (e) {
      updateResult(2, { 
        status: 'error', 
        message: 'OPTIONS request failed', 
        details: e instanceof Error ? e.message : 'Unknown' 
      });
    }

    // Test 4: Validate K8s response
    updateResult(3, { status: 'running', message: 'Validating response...' });
    await new Promise(r => setTimeout(r, 200));
    
    if (getWorked) {
      if (responseData && responseData.gitVersion) {
        updateResult(3, { 
          status: 'success', 
          message: 'Valid Kubernetes API', 
          details: `Version: ${responseData.gitVersion}, Platform: ${responseData.platform || 'unknown'}` 
        });
      } else {
        updateResult(3, { 
          status: 'warning', 
          message: 'Response received but format unexpected', 
          details: JSON.stringify(responseData).slice(0, 100) 
        });
      }
    } else {
      updateResult(3, { 
        status: 'error', 
        message: 'Could not validate', 
        details: 'No successful response received' 
      });
    }

    setIsRunning(false);
  };

  const getStatusIcon = (status: TestResult['status']) => {
    switch (status) {
      case 'success': return <CheckCircle className="h-4 w-4 text-green-500" />;
      case 'error': return <XCircle className="h-4 w-4 text-red-500" />;
      case 'warning': return <AlertTriangle className="h-4 w-4 text-yellow-500" />;
      case 'running': return <Loader2 className="h-4 w-4 text-blue-500 animate-spin" />;
      default: return <Info className="h-4 w-4 text-muted-foreground" />;
    }
  };

  const getStatusBadge = (status: TestResult['status']) => {
    switch (status) {
      case 'success': return <Badge className="bg-green-600">Pass</Badge>;
      case 'error': return <Badge variant="destructive">Fail</Badge>;
      case 'warning': return <Badge className="bg-yellow-600">Warning</Badge>;
      case 'running': return <Badge variant="secondary">Running</Badge>;
      default: return <Badge variant="outline">Pending</Badge>;
    }
  };

  const anySuccess = results.some(r => r.status === 'success' && r.name.includes('GET'));

  return (
    <Card>
      <CardHeader>
        <CardTitle>Connection Diagnostics</CardTitle>
        <CardDescription>
          Test connectivity to your Kubernetes cluster via proxy
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="space-y-2">
          <Label htmlFor="test-url">Kubernetes Proxy URL</Label>
          <div className="flex gap-2">
            <Input
              id="test-url"
              placeholder="http://localhost:8010 or https://your-tunnel.loca.lt"
              value={proxyUrl}
              onChange={(e) => setProxyUrl(e.target.value)}
              disabled={isRunning}
            />
            <Button onClick={runDiagnostics} disabled={isRunning || !proxyUrl}>
              {isRunning ? (
                <>
                  <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                  Testing...
                </>
              ) : (
                'Run Tests'
              )}
            </Button>
          </div>
        </div>

        {results.length > 0 && (
          <div className="space-y-2 border rounded-lg p-4">
            {results.map((result, index) => (
              <div key={index} className="flex items-start gap-3 py-2 border-b last:border-0">
                {getStatusIcon(result.status)}
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="font-medium text-sm">{result.name}</span>
                    {getStatusBadge(result.status)}
                  </div>
                  <p className="text-sm text-muted-foreground">{result.message}</p>
                  {result.details && (
                    <p className="text-xs text-muted-foreground/70 mt-1 break-all">
                      {result.details}
                    </p>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}

        {anySuccess && (
          <div className="p-4 rounded-lg bg-green-500/10 border border-green-500/30 space-y-2">
            <h4 className="font-medium text-green-600 flex items-center gap-2">
              <CheckCircle className="h-4 w-4" />
              Connection Successful!
            </h4>
            <p className="text-sm text-muted-foreground">
              Your Kubernetes cluster is accessible. You can now use the Connect button above.
            </p>
          </div>
        )}
      </CardContent>
    </Card>
  );
}