import React, { useState, useCallback } from 'react';
import { Send, RefreshCw, AlertCircle, CheckCircle, Copy, Check, Trash2 } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { k8sClient } from '@/lib/kubernetes-client';
import type { ModelAPI } from '@/types/kubernetes';

interface ModelAPIDiagnosticsProps {
  modelAPI: ModelAPI;
}

interface DiagnosticResult {
  timestamp: Date;
  request: {
    model: string;
    messages: { role: string; content: string }[];
    seed?: number;
  };
  response?: {
    status: number;
    data: unknown;
    latency: number;
  };
  error?: string;
}

export function ModelAPIDiagnostics({ modelAPI }: ModelAPIDiagnosticsProps) {
  const [prompt, setPrompt] = useState('Hello, can you tell me a short joke?');
  const [model, setModel] = useState('');
  const [seed, setSeed] = useState<string>('');
  const [isLoading, setIsLoading] = useState(false);
  const [results, setResults] = useState<DiagnosticResult[]>([]);
  const [copiedIndex, setCopiedIndex] = useState<number | null>(null);

  const serviceName = `modelapi-${modelAPI.metadata.name}`;
  const namespace = modelAPI.metadata.namespace || 'default';

  // Derive default model from spec
  const defaultModel = modelAPI.spec.mode === 'Proxy' 
    ? (modelAPI.spec.proxyConfig?.models?.[0] || 'gpt-3.5-turbo')
    : modelAPI.spec.hostedConfig?.model || 'llama2';

  const sendRequest = useCallback(async () => {
    if (!k8sClient.isConfigured()) {
      setResults(prev => [{
        timestamp: new Date(),
        request: { model: model || defaultModel, messages: [{ role: 'user', content: prompt }] },
        error: 'Kubernetes client not configured',
      }, ...prev]);
      return;
    }

    setIsLoading(true);
    const startTime = Date.now();

    // Parse seed if provided
    let seedNum: number | undefined;
    if (seed.trim()) {
      const parsed = parseInt(seed.trim(), 10);
      if (!isNaN(parsed)) {
        seedNum = parsed;
      }
    }

    const requestBody = {
      model: model || defaultModel,
      messages: [{ role: 'user', content: prompt }],
      max_tokens: 256,
      ...(seedNum !== undefined && { seed: seedNum }),
    };

    try {
      const response = await k8sClient.proxyServiceRequest(
        serviceName,
        '/v1/chat/completions',
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(requestBody),
        },
        namespace
      );

      const latency = Date.now() - startTime;
      const data = await response.json();

      setResults(prev => [{
        timestamp: new Date(),
        request: requestBody,
        response: {
          status: response.status,
          data,
          latency,
        },
      }, ...prev]);
    } catch (err) {
      const latency = Date.now() - startTime;
      const errorMessage = err instanceof Error ? err.message : 'Failed to send request';

      setResults(prev => [{
        timestamp: new Date(),
        request: requestBody,
        error: `${errorMessage} (after ${latency}ms)`,
      }, ...prev]);
    } finally {
      setIsLoading(false);
    }
  }, [prompt, model, seed, defaultModel, serviceName, namespace]);

  const copyResult = (index: number) => {
    const result = results[index];
    const text = JSON.stringify(result, null, 2);
    navigator.clipboard.writeText(text);
    setCopiedIndex(index);
    setTimeout(() => setCopiedIndex(null), 2000);
  };

  const clearResults = () => {
    setResults([]);
  };

  const getResponseContent = (result: DiagnosticResult): string => {
    if (result.error) return result.error;
    if (!result.response?.data) return 'No response data';
    
    const data = result.response.data as { choices?: { message?: { content?: string } }[]; error?: { message?: string } };
    if (data.choices?.[0]?.message?.content) {
      return data.choices[0].message.content;
    }
    if (data.error?.message) {
      return `Error: ${data.error.message}`;
    }
    return JSON.stringify(data, null, 2);
  };

  return (
    <div className="space-y-4">
      {/* Request Form */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Send Test Request</CardTitle>
          <CardDescription>
            Send a stateless request to test the ModelAPI endpoint
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div className="space-y-2">
              <Label htmlFor="model">Model (optional)</Label>
              <Input
                id="model"
                placeholder={defaultModel}
                value={model}
                onChange={(e) => setModel(e.target.value)}
              />
              <p className="text-xs text-muted-foreground">
                Leave empty to use: {defaultModel}
              </p>
            </div>
            <div className="space-y-2">
              <Label htmlFor="seed">Seed (optional)</Label>
              <Input
                id="seed"
                type="number"
                placeholder="e.g., 12345"
                value={seed}
                onChange={(e) => setSeed(e.target.value)}
              />
              <p className="text-xs text-muted-foreground">
                For deterministic responses
              </p>
            </div>
            <div className="space-y-2">
              <Label>Endpoint</Label>
              <div className="flex items-center h-10 px-3 rounded-md bg-muted text-sm font-mono overflow-hidden">
                <span className="truncate">{modelAPI.status?.endpoint || `http://${serviceName}.${namespace}.svc.cluster.local:8000`}</span>
              </div>
            </div>
          </div>

          <div className="space-y-2">
            <Label htmlFor="prompt">Prompt</Label>
            <Textarea
              id="prompt"
              placeholder="Enter your test prompt..."
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              rows={3}
            />
          </div>

          <div className="flex items-center justify-between">
            <Button
              onClick={sendRequest}
              disabled={isLoading || !prompt.trim()}
              className="gap-2"
            >
              {isLoading ? (
                <>
                  <RefreshCw className="h-4 w-4 animate-spin" />
                  Sending...
                </>
              ) : (
                <>
                  <Send className="h-4 w-4" />
                  Send Request
                </>
              )}
            </Button>

            {results.length > 0 && (
              <Button variant="ghost" size="sm" onClick={clearResults} className="gap-2">
                <Trash2 className="h-4 w-4" />
                Clear History
              </Button>
            )}
          </div>
        </CardContent>
      </Card>

      {/* Results */}
      {results.length > 0 && (
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base flex items-center justify-between">
              Response History
              <Badge variant="secondary">{results.length} request{results.length !== 1 ? 's' : ''}</Badge>
            </CardTitle>
          </CardHeader>
          <CardContent>
            <ScrollArea className="h-[400px] pr-4">
              <div className="space-y-4">
                {results.map((result, index) => (
                  <div
                    key={index}
                    className={`p-4 rounded-lg border ${
                      result.error 
                        ? 'border-destructive/50 bg-destructive/5' 
                        : 'border-border bg-muted/30'
                    }`}
                  >
                    <div className="flex items-center justify-between mb-3">
                      <div className="flex items-center gap-2">
                        {result.error ? (
                          <AlertCircle className="h-4 w-4 text-destructive" />
                        ) : (
                          <CheckCircle className="h-4 w-4 text-success" />
                        )}
                        <span className="text-xs text-muted-foreground">
                          {result.timestamp.toLocaleTimeString()}
                        </span>
                        {result.response && (
                          <>
                            <Badge 
                              variant={result.response.status >= 200 && result.response.status < 300 ? 'success' : 'destructive'}
                              className="text-xs"
                            >
                              {result.response.status}
                            </Badge>
                            <Badge variant="outline" className="text-xs">
                              {result.response.latency}ms
                            </Badge>
                          </>
                        )}
                      </div>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-6 w-6"
                        onClick={() => copyResult(index)}
                      >
                        {copiedIndex === index ? (
                          <Check className="h-3 w-3 text-success" />
                        ) : (
                          <Copy className="h-3 w-3" />
                        )}
                      </Button>
                    </div>

                    <Tabs defaultValue="response" className="w-full">
                      <TabsList className="h-8">
                        <TabsTrigger value="response" className="text-xs h-7">Response</TabsTrigger>
                        <TabsTrigger value="request" className="text-xs h-7">Request</TabsTrigger>
                        <TabsTrigger value="raw" className="text-xs h-7">Raw</TabsTrigger>
                      </TabsList>

                      <TabsContent value="response" className="mt-2">
                        <div className={`text-sm whitespace-pre-wrap ${result.error ? 'text-destructive' : ''}`}>
                          {getResponseContent(result)}
                        </div>
                      </TabsContent>

                      <TabsContent value="request" className="mt-2">
                        <pre className="text-xs font-mono bg-background/50 p-2 rounded overflow-auto max-h-32">
                          {JSON.stringify(result.request, null, 2)}
                        </pre>
                      </TabsContent>

                      <TabsContent value="raw" className="mt-2">
                        <pre className="text-xs font-mono bg-background/50 p-2 rounded overflow-auto max-h-48">
                          {JSON.stringify(result.response?.data || result.error, null, 2)}
                        </pre>
                      </TabsContent>
                    </Tabs>
                  </div>
                ))}
              </div>
            </ScrollArea>
          </CardContent>
        </Card>
      )}

      {/* Help Card */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Diagnostics Info</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3 text-sm">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <span className="text-muted-foreground">Mode:</span>
              <p className="font-medium">{modelAPI.spec.mode}</p>
            </div>
            <div>
              <span className="text-muted-foreground">Status:</span>
              <p className="font-medium">
                <Badge variant={modelAPI.status?.ready ? 'success' : 'warning'}>
                  {modelAPI.status?.phase || 'Unknown'}
                </Badge>
              </p>
            </div>
          </div>
          
          {!modelAPI.status?.ready && (
            <Alert variant="destructive">
              <AlertCircle className="h-4 w-4" />
              <AlertDescription>
                ModelAPI is not ready. Requests may fail until the service is available.
              </AlertDescription>
            </Alert>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
