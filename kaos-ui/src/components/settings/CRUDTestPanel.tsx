import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Loader2, Play, CheckCircle, XCircle, AlertCircle } from 'lucide-react';
import { k8sClient } from '@/lib/kubernetes-client';
import { useKubernetesConnection } from '@/contexts/KubernetesConnectionContext';
import type { ModelAPI, MCPServer, Agent } from '@/types/kubernetes';

interface TestResult {
  name: string;
  status: 'pending' | 'running' | 'passed' | 'failed' | 'skipped';
  message?: string;
  duration?: number;
}

interface TestSuite {
  name: string;
  tests: TestResult[];
  status: 'pending' | 'running' | 'passed' | 'failed';
}

export function CRUDTestPanel() {
  const { connected, namespace } = useKubernetesConnection();
  const [running, setRunning] = useState(false);
  const [suites, setSuites] = useState<TestSuite[]>([]);

  const updateTest = (suiteName: string, testName: string, update: Partial<TestResult>) => {
    setSuites(prev => prev.map(suite => 
      suite.name === suiteName 
        ? { 
            ...suite, 
            tests: suite.tests.map(test => 
              test.name === testName ? { ...test, ...update } : test
            )
          }
        : suite
    ));
  };

  const updateSuite = (suiteName: string, update: Partial<TestSuite>) => {
    setSuites(prev => prev.map(suite => 
      suite.name === suiteName ? { ...suite, ...update } : suite
    ));
  };

  const runTest = async (
    suiteName: string, 
    testName: string, 
    testFn: () => Promise<void>
  ): Promise<boolean> => {
    updateTest(suiteName, testName, { status: 'running' });
    const start = Date.now();
    
    try {
      await testFn();
      updateTest(suiteName, testName, { 
        status: 'passed', 
        duration: Date.now() - start,
        message: 'Success'
      });
      return true;
    } catch (error) {
      updateTest(suiteName, testName, { 
        status: 'failed', 
        duration: Date.now() - start,
        message: error instanceof Error ? error.message : String(error)
      });
      return false;
    }
  };

  const runModelAPITests = async () => {
    const suiteName = 'ModelAPI CRUD';
    updateSuite(suiteName, { status: 'running' });
    
    const testName = `crud-test-modelapi-${Date.now()}`;
    let createdResource: ModelAPI | null = null;

    // Create
    const createPassed = await runTest(suiteName, 'Create ModelAPI', async () => {
      const newModelAPI: Omit<ModelAPI, 'status'> = {
        apiVersion: 'kaos.tools/v1alpha1',
        kind: 'ModelAPI',
        metadata: {
          name: testName,
          namespace: namespace,
        },
        spec: {
          mode: 'Proxy',
          proxyConfig: {
            models: ['*'],
            env: [
              { name: 'TEST_KEY', value: 'test-value' }
            ]
          }
        }
      };
      createdResource = await k8sClient.createModelAPI(newModelAPI);
      if (!createdResource?.metadata?.name) {
        throw new Error('Created resource missing name');
      }
    });

    if (!createPassed) {
      updateSuite(suiteName, { status: 'failed' });
      return;
    }

    // Read
    let latestResource: ModelAPI | null = null;
    const readPassed = await runTest(suiteName, 'Read ModelAPI', async () => {
      latestResource = await k8sClient.getModelAPI(testName);
      if (latestResource.metadata.name !== testName) {
        throw new Error('Fetched name does not match');
      }
    });

    // Update (use latestResource from read to get current resourceVersion)
    const updatePassed = await runTest(suiteName, 'Update ModelAPI', async () => {
      if (!latestResource) throw new Error('No resource to update');
      const updated: ModelAPI = {
        ...latestResource,
        spec: {
          ...latestResource.spec,
          proxyConfig: {
            models: ['*'],
            env: [
              { name: 'TEST_KEY', value: 'updated-value' },
              { name: 'NEW_KEY', value: 'new-value' }
            ]
          }
        }
      };
      const result = await k8sClient.updateModelAPI(updated);
      const newEnv = result.spec.proxyConfig?.env?.find(e => e.name === 'NEW_KEY');
      if (!newEnv) {
        throw new Error('Update did not apply');
      }
    });

    // Delete
    const deletePassed = await runTest(suiteName, 'Delete ModelAPI', async () => {
      await k8sClient.deleteModelAPI(testName);
      // Verify deletion
      try {
        await k8sClient.getModelAPI(testName);
        throw new Error('Resource still exists after delete');
      } catch (e) {
        // Expected - resource should not exist
        if (e instanceof Error && e.message.includes('still exists')) {
          throw e;
        }
      }
    });

    updateSuite(suiteName, { 
      status: createPassed && readPassed && updatePassed && deletePassed ? 'passed' : 'failed' 
    });
  };

  const runMCPServerTests = async () => {
    const suiteName = 'MCPServer CRUD';
    updateSuite(suiteName, { status: 'running' });
    
    const testName = `crud-test-mcpserver-${Date.now()}`;
    let createdResource: MCPServer | null = null;

    // Create
    const createPassed = await runTest(suiteName, 'Create MCPServer', async () => {
      const newMCPServer: Omit<MCPServer, 'status'> = {
        apiVersion: 'kaos.tools/v1alpha1',
        kind: 'MCPServer',
        metadata: {
          name: testName,
          namespace: namespace,
        },
        spec: {
          type: 'python-runtime',
          config: {
            tools: {
              fromPackage: 'test-mcp-server'
            }
          }
        }
      };
      createdResource = await k8sClient.createMCPServer(newMCPServer);
      if (!createdResource?.metadata?.name) {
        throw new Error('Created resource missing name');
      }
    });

    if (!createPassed) {
      updateSuite(suiteName, { status: 'failed' });
      return;
    }

    // Read
    let latestResource: MCPServer | null = null;
    const readPassed = await runTest(suiteName, 'Read MCPServer', async () => {
      latestResource = await k8sClient.getMCPServer(testName);
      if (latestResource.metadata.name !== testName) {
        throw new Error('Fetched name does not match');
      }
    });

    // Update (use latestResource from read to get current resourceVersion)
    const updatePassed = await runTest(suiteName, 'Update MCPServer', async () => {
      if (!latestResource) throw new Error('No resource to update');
      const updated: MCPServer = {
        ...latestResource,
        spec: {
          ...latestResource.spec,
          config: {
            ...latestResource.spec.config,
            tools: {
              fromPackage: 'updated-mcp-server'
            }
          }
        }
      };
      const result = await k8sClient.updateMCPServer(updated);
      if (result.spec.config?.tools?.fromPackage !== 'updated-mcp-server') {
        throw new Error('Update did not apply');
      }
    });

    // Delete
    const deletePassed = await runTest(suiteName, 'Delete MCPServer', async () => {
      await k8sClient.deleteMCPServer(testName);
      try {
        await k8sClient.getMCPServer(testName);
        throw new Error('Resource still exists after delete');
      } catch (e) {
        if (e instanceof Error && e.message.includes('still exists')) {
          throw e;
        }
      }
    });

    updateSuite(suiteName, { 
      status: createPassed && readPassed && updatePassed && deletePassed ? 'passed' : 'failed' 
    });
  };

  const runAgentTests = async () => {
    const suiteName = 'Agent CRUD';
    updateSuite(suiteName, { status: 'running' });
    
    const testName = `crud-test-agent-${Date.now()}`;
    let createdResource: Agent | null = null;

    // Create
    const createPassed = await runTest(suiteName, 'Create Agent', async () => {
      const newAgent: Omit<Agent, 'status'> = {
        apiVersion: 'kaos.tools/v1alpha1',
        kind: 'Agent',
        metadata: {
          name: testName,
          namespace: namespace,
        },
        spec: {
          modelAPI: 'multi-agent-api',
          model: 'ollama/smollm2:135m',
          config: {
            description: 'Test agent for CRUD testing',
            instructions: 'You are a test agent.',
            env: [
              { name: 'TEST_VAR', value: 'test-value' }
            ]
          },
          agentNetwork: {
            expose: false
          }
        }
      };
      createdResource = await k8sClient.createAgent(newAgent);
      if (!createdResource?.metadata?.name) {
        throw new Error('Created resource missing name');
      }
    });

    if (!createPassed) {
      updateSuite(suiteName, { status: 'failed' });
      return;
    }

    // Read
    let latestResource: Agent | null = null;
    const readPassed = await runTest(suiteName, 'Read Agent', async () => {
      latestResource = await k8sClient.getAgent(testName);
      if (latestResource.metadata.name !== testName) {
        throw new Error('Fetched name does not match');
      }
    });

    // Update (use latestResource from read to get current resourceVersion)
    const updatePassed = await runTest(suiteName, 'Update Agent', async () => {
      if (!latestResource) throw new Error('No resource to update');
      const updated: Agent = {
        ...latestResource,
        spec: {
          ...latestResource.spec,
          config: {
            ...latestResource.spec.config,
            description: 'Updated test agent description'
          }
        }
      };
      const result = await k8sClient.updateAgent(updated);
      if (result.spec.config?.description !== 'Updated test agent description') {
        throw new Error('Update did not apply');
      }
    });

    // Delete
    const deletePassed = await runTest(suiteName, 'Delete Agent', async () => {
      await k8sClient.deleteAgent(testName);
      try {
        await k8sClient.getAgent(testName);
        throw new Error('Resource still exists after delete');
      } catch (e) {
        if (e instanceof Error && e.message.includes('still exists')) {
          throw e;
        }
      }
    });

    updateSuite(suiteName, { 
      status: createPassed && readPassed && updatePassed && deletePassed ? 'passed' : 'failed' 
    });
  };

  const runAllTests = async () => {
    if (!connected) return;
    
    setRunning(true);
    
    // Initialize test suites
    setSuites([
      {
        name: 'ModelAPI CRUD',
        status: 'pending',
        tests: [
          { name: 'Create ModelAPI', status: 'pending' },
          { name: 'Read ModelAPI', status: 'pending' },
          { name: 'Update ModelAPI', status: 'pending' },
          { name: 'Delete ModelAPI', status: 'pending' },
        ]
      },
      {
        name: 'MCPServer CRUD',
        status: 'pending',
        tests: [
          { name: 'Create MCPServer', status: 'pending' },
          { name: 'Read MCPServer', status: 'pending' },
          { name: 'Update MCPServer', status: 'pending' },
          { name: 'Delete MCPServer', status: 'pending' },
        ]
      },
      {
        name: 'Agent CRUD',
        status: 'pending',
        tests: [
          { name: 'Create Agent', status: 'pending' },
          { name: 'Read Agent', status: 'pending' },
          { name: 'Update Agent', status: 'pending' },
          { name: 'Delete Agent', status: 'pending' },
        ]
      }
    ]);

    // Run tests sequentially by suite
    await runModelAPITests();
    await runMCPServerTests();
    await runAgentTests();

    setRunning(false);
  };

  const getStatusIcon = (status: string) => {
    switch (status) {
      case 'passed':
        return <CheckCircle className="h-4 w-4 text-green-500" />;
      case 'failed':
        return <XCircle className="h-4 w-4 text-destructive" />;
      case 'running':
        return <Loader2 className="h-4 w-4 animate-spin text-blue-500" />;
      case 'skipped':
        return <AlertCircle className="h-4 w-4 text-muted-foreground" />;
      default:
        return <div className="h-4 w-4 rounded-full border-2 border-muted-foreground" />;
    }
  };

  const totalTests = suites.reduce((acc, s) => acc + s.tests.length, 0);
  const passedTests = suites.reduce((acc, s) => acc + s.tests.filter(t => t.status === 'passed').length, 0);
  const failedTests = suites.reduce((acc, s) => acc + s.tests.filter(t => t.status === 'failed').length, 0);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Play className="h-5 w-5" />
          CRUD End-to-End Tests
        </CardTitle>
        <CardDescription>
          Run create, read, update, delete tests against the connected cluster. 
          Test resources are automatically cleaned up.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {!connected && (
          <div className="p-4 rounded-lg bg-amber-500/10 border border-amber-500/20">
            <p className="text-sm text-amber-600">
              Connect to a Kubernetes cluster first to run tests.
            </p>
          </div>
        )}

        <div className="flex items-center gap-4">
          <Button 
            onClick={runAllTests} 
            disabled={!connected || running}
          >
            {running ? (
              <>
                <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                Running Tests...
              </>
            ) : (
              <>
                <Play className="h-4 w-4 mr-2" />
                Run All CRUD Tests
              </>
            )}
          </Button>

          {suites.length > 0 && (
            <div className="flex gap-2">
              <Badge variant="default" className="bg-green-600">
                {passedTests} passed
              </Badge>
              {failedTests > 0 && (
                <Badge variant="destructive">
                  {failedTests} failed
                </Badge>
              )}
              <Badge variant="secondary">
                {totalTests} total
              </Badge>
            </div>
          )}
        </div>

        {suites.length > 0 && (
          <ScrollArea className="h-[400px] rounded-md border p-4">
            <div className="space-y-6">
              {suites.map((suite) => (
                <div key={suite.name} className="space-y-2">
                  <div className="flex items-center gap-2 font-medium">
                    {getStatusIcon(suite.status)}
                    <span>{suite.name}</span>
                    {suite.status === 'passed' && (
                      <Badge variant="default" className="bg-green-600 text-xs">PASS</Badge>
                    )}
                    {suite.status === 'failed' && (
                      <Badge variant="destructive" className="text-xs">FAIL</Badge>
                    )}
                  </div>
                  <div className="ml-6 space-y-1">
                    {suite.tests.map((test) => (
                      <div 
                        key={test.name} 
                        className="flex items-center gap-2 text-sm py-1"
                      >
                        {getStatusIcon(test.status)}
                        <span className={test.status === 'failed' ? 'text-destructive' : ''}>
                          {test.name}
                        </span>
                        {test.duration !== undefined && (
                          <span className="text-xs text-muted-foreground">
                            ({test.duration}ms)
                          </span>
                        )}
                        {test.status === 'failed' && test.message && (
                          <span className="text-xs text-destructive ml-2">
                            - {test.message}
                          </span>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </ScrollArea>
        )}
      </CardContent>
    </Card>
  );
}
