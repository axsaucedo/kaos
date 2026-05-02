import type { Page, Route } from '@playwright/test';

export const VISUAL_NAMESPACE = 'kaos-visual';
export const VISUAL_K8S_BASE = '/__k8s';

type Scenario = 'populated' | 'empty';
type K8sResource = {
  apiVersion: string;
  kind: string;
  metadata: {
    name: string;
    namespace: string;
    uid?: string;
    creationTimestamp?: string;
    labels?: Record<string, string>;
    annotations?: Record<string, string>;
  };
  spec?: Record<string, unknown>;
  status?: Record<string, unknown>;
  type?: string;
  dataKeys?: string[];
};

const timestamp = '2025-01-15T12:00:00.000Z';

function metadata(name: string, labels: Record<string, string> = {}): K8sResource['metadata'] {
  return {
    name,
    namespace: VISUAL_NAMESPACE,
    uid: `uid-${name}`,
    creationTimestamp: timestamp,
    labels,
  };
}

const modelAPIs: K8sResource[] = [
  {
    apiVersion: 'kaos.tools/v1alpha1',
    kind: 'ModelAPI',
    metadata: metadata('primary-model-api', { 'app.kubernetes.io/name': 'kaos-modelapi' }),
    spec: {
      mode: 'Proxy',
      proxyConfig: {
        models: ['openai/gpt-4o-mini', 'anthropic/claude-haiku'],
        provider: 'openai',
        apiBase: 'https://api.openai.com/v1',
      },
      container: {
        env: [{ name: 'LOG_LEVEL', value: 'INFO' }],
      },
    },
    status: {
      phase: 'Ready',
      ready: true,
      endpoint: `http://modelapi-primary-model-api.${VISUAL_NAMESPACE}.svc.cluster.local:8000`,
      supportedModels: ['openai/gpt-4o-mini', 'anthropic/claude-haiku'],
      deployment: { replicas: 1, readyReplicas: 1, availableReplicas: 1 },
    },
  },
  {
    apiVersion: 'kaos.tools/v1alpha1',
    kind: 'ModelAPI',
    metadata: metadata('local-ollama'),
    spec: {
      mode: 'Hosted',
      hostedConfig: { model: 'smollm2:135m' },
    },
    status: {
      phase: 'Pending',
      ready: false,
      message: 'Pulling model image',
      deployment: { replicas: 1, readyReplicas: 0, availableReplicas: 0 },
    },
  },
];

const mcpServers: K8sResource[] = [
  {
    apiVersion: 'kaos.tools/v1alpha1',
    kind: 'MCPServer',
    metadata: metadata('toolbox-server', { 'app.kubernetes.io/name': 'kaos-mcpserver' }),
    spec: {
      runtime: 'python-string',
      params: 'def echo(message: str) -> str:\n    return message',
      container: {
        env: [{ name: 'LOG_LEVEL', value: 'DEBUG' }],
      },
    },
    status: {
      phase: 'Ready',
      ready: true,
      endpoint: `http://mcpserver-toolbox-server.${VISUAL_NAMESPACE}.svc.cluster.local:8000`,
      availableTools: ['echo', 'summarize'],
      deployment: { replicas: 1, readyReplicas: 1, availableReplicas: 1 },
    },
  },
  {
    apiVersion: 'kaos.tools/v1alpha1',
    kind: 'MCPServer',
    metadata: metadata('cluster-tools'),
    spec: {
      runtime: 'kubernetes',
      serviceAccountName: 'kaos-agent',
    },
    status: {
      phase: 'Failed',
      ready: false,
      message: 'RBAC permissions are missing',
      availableTools: [],
      deployment: { replicas: 1, readyReplicas: 0, availableReplicas: 0 },
    },
  },
];

const agents: K8sResource[] = [
  {
    apiVersion: 'kaos.tools/v1alpha1',
    kind: 'Agent',
    metadata: metadata('planner-agent', {
      'app.kubernetes.io/name': 'kaos-agent',
      'kaos.tools/role': 'planner',
    }),
    spec: {
      modelAPI: 'primary-model-api',
      model: 'openai/gpt-4o-mini',
      mcpServers: ['toolbox-server', 'cluster-tools'],
      waitForDependencies: true,
      agentNetwork: { expose: true, access: ['worker-agent'] },
      config: {
        description: 'Plans multi-step Kubernetes operations.',
        instructions: 'Plan work, delegate execution, and summarize results.',
        memory: { enabled: true, type: 'local', contextLimit: 6 },
        taskConfig: { maxIterations: 8, maxRuntimeSeconds: 240, maxToolCalls: 25 },
      },
      container: {
        env: [{ name: 'LOG_LEVEL', value: 'INFO' }],
      },
    },
    status: {
      phase: 'Running',
      ready: true,
      endpoint: `http://agent-planner-agent.${VISUAL_NAMESPACE}.svc.cluster.local:8000`,
      model: 'openai/gpt-4o-mini',
      linkedResources: { modelAPI: 'primary-model-api', mcpServers: 'toolbox-server,cluster-tools' },
      deployment: { replicas: 1, readyReplicas: 1, availableReplicas: 1 },
    },
  },
  {
    apiVersion: 'kaos.tools/v1alpha1',
    kind: 'Agent',
    metadata: metadata('worker-agent', {
      'app.kubernetes.io/name': 'kaos-agent',
      'kaos.tools/role': 'worker',
    }),
    spec: {
      modelAPI: 'primary-model-api',
      model: 'openai/gpt-4o-mini',
      mcpServers: ['toolbox-server'],
      agentNetwork: { expose: true, access: [] },
      config: {
        description: 'Executes delegated tasks.',
        instructions: 'Execute the task and return a concise result.',
        autonomous: { goal: 'Monitor cluster drift', intervalSeconds: 300, maxIterRuntimeSeconds: 60 },
      },
    },
    status: {
      phase: 'Ready',
      ready: true,
      endpoint: `http://agent-worker-agent.${VISUAL_NAMESPACE}.svc.cluster.local:8000`,
      model: 'openai/gpt-4o-mini',
      deployment: { replicas: 1, readyReplicas: 1, availableReplicas: 1 },
    },
  },
];

const pods: K8sResource[] = [
  {
    apiVersion: 'v1',
    kind: 'Pod',
    metadata: metadata('agent-planner-agent-7d6f9b9d7c-abcde', {
      'app.kubernetes.io/instance': 'planner-agent',
      'kaos.tools/resource-kind': 'Agent',
      'kaos.tools/resource-name': 'planner-agent',
    }),
    spec: {
      nodeName: 'kind-worker',
      containers: [
        {
          name: 'agent',
          image: 'axsauze/kaos-agent:0.4.4-dev',
          ports: [{ containerPort: 8000 }],
          env: [{ name: 'LOG_LEVEL', value: 'INFO' }],
        },
      ],
    },
    status: {
      phase: 'Running',
      podIP: '10.244.0.12',
      hostIP: '172.18.0.2',
      containerStatuses: [
        { name: 'agent', ready: true, restartCount: 0, state: { running: { startedAt: timestamp } } },
      ],
    },
  },
  {
    apiVersion: 'v1',
    kind: 'Pod',
    metadata: metadata('mcpserver-toolbox-server-69c8c99dbf-fghij', {
      'app.kubernetes.io/instance': 'toolbox-server',
      'kaos.tools/resource-kind': 'MCPServer',
      'kaos.tools/resource-name': 'toolbox-server',
    }),
    spec: {
      nodeName: 'kind-worker',
      containers: [
        { name: 'mcpserver', image: 'axsauze/kaos-mcp-python-string:0.4.4-dev', ports: [{ containerPort: 8000 }] },
      ],
    },
    status: {
      phase: 'Running',
      podIP: '10.244.0.18',
      containerStatuses: [
        { name: 'mcpserver', ready: true, restartCount: 1, state: { running: { startedAt: timestamp } } },
      ],
    },
  },
  {
    apiVersion: 'v1',
    kind: 'Pod',
    metadata: metadata('modelapi-primary-model-api-5c44d9b6f8-klmno', {
      'app.kubernetes.io/instance': 'primary-model-api',
      'kaos.tools/resource-kind': 'ModelAPI',
      'kaos.tools/resource-name': 'primary-model-api',
    }),
    spec: {
      nodeName: 'kind-worker2',
      containers: [
        { name: 'proxy', image: 'ghcr.io/berriai/litellm:main-stable', ports: [{ containerPort: 4000 }] },
      ],
    },
    status: {
      phase: 'Running',
      podIP: '10.244.1.9',
      containerStatuses: [
        { name: 'proxy', ready: true, restartCount: 0, state: { running: { startedAt: timestamp } } },
      ],
    },
  },
];

const deployments: K8sResource[] = [
  {
    apiVersion: 'apps/v1',
    kind: 'Deployment',
    metadata: metadata('kaos-operator-controller-manager'),
    spec: {
      replicas: 1,
      selector: { matchLabels: { 'app.kubernetes.io/name': 'kaos-operator' } },
      template: { spec: { containers: [{ name: 'manager', image: 'axsauze/kaos-operator:0.4.4-dev' }] } },
    },
    status: { replicas: 1, readyReplicas: 1, availableReplicas: 1 },
  },
];

const services: K8sResource[] = [
  {
    apiVersion: 'v1',
    kind: 'Service',
    metadata: metadata('agent-planner-agent'),
    spec: { type: 'ClusterIP', ports: [{ name: 'http', port: 8000, targetPort: 8000, protocol: 'TCP' }] },
  },
  {
    apiVersion: 'v1',
    kind: 'Service',
    metadata: metadata('mcpserver-toolbox-server'),
    spec: { type: 'ClusterIP', ports: [{ name: 'http', port: 8000, targetPort: 8000, protocol: 'TCP' }] },
  },
  {
    apiVersion: 'v1',
    kind: 'Service',
    metadata: metadata('modelapi-primary-model-api'),
    spec: { type: 'ClusterIP', ports: [{ name: 'http', port: 8000, targetPort: 8000, protocol: 'TCP' }] },
  },
];

const secrets: K8sResource[] = [
  {
    apiVersion: 'v1',
    kind: 'Secret',
    metadata: metadata('openai-api-key'),
    type: 'Opaque',
    dataKeys: ['api-key'],
  },
  {
    apiVersion: 'v1',
    kind: 'Secret',
    metadata: metadata('default-token-visual'),
    type: 'kubernetes.io/service-account-token',
    dataKeys: ['token', 'ca.crt'],
  },
];

const pvcs: K8sResource[] = [
  {
    apiVersion: 'v1',
    kind: 'PersistentVolumeClaim',
    metadata: metadata('agent-memory'),
    spec: { accessModes: ['ReadWriteOnce'], resources: { requests: { storage: '1Gi' } } },
    status: { phase: 'Bound', capacity: { storage: '1Gi' } },
  },
];

function scenarioData(scenario: Scenario) {
  if (scenario === 'empty') {
    return {
      modelAPIs: [],
      mcpServers: [],
      agents: [],
      pods: [],
      deployments: [],
      services: [],
      secrets: [],
      pvcs: [],
    };
  }

  return { modelAPIs, mcpServers, agents, pods, deployments, services, secrets, pvcs };
}

function listResponse(items: K8sResource[]) {
  return {
    apiVersion: 'v1',
    kind: 'List',
    metadata: { resourceVersion: '1' },
    items,
  };
}

function jsonRpcResult(method: string) {
  if (method === 'initialize') {
    return { protocolVersion: '2024-11-05', capabilities: {}, serverInfo: { name: 'visual-mcp', version: '1.0.0' } };
  }

  if (method === 'tools/list') {
    return {
      tools: [
        {
          name: 'echo',
          description: 'Echo a message for deterministic visual tests.',
          inputSchema: {
            type: 'object',
            properties: { message: { type: 'string', default: 'hello kaos' } },
            required: ['message'],
          },
        },
        {
          name: 'summarize',
          description: 'Summarize a Kubernetes resource.',
          inputSchema: {
            type: 'object',
            properties: { resource: { type: 'string', default: 'pods' } },
          },
        },
      ],
    };
  }

  if (method === 'tools/call') {
    return { content: [{ type: 'text', text: 'Tool executed successfully in the visual fixture.' }] };
  }

  return {};
}

async function fulfillJson(route: Route, json: unknown, status = 200, headers: Record<string, string> = {}) {
  await route.fulfill({
    status,
    headers: {
      'access-control-allow-origin': '*',
      'content-type': 'application/json',
      ...headers,
    },
    body: JSON.stringify(json),
  });
}

async function fulfillText(route: Route, body: string, status = 200) {
  await route.fulfill({
    status,
    headers: {
      'access-control-allow-origin': '*',
      'content-type': 'text/plain',
    },
    body,
  });
}

export async function mockKubernetesApi(page: Page, scenario: Scenario = 'populated') {
  const data = scenarioData(scenario);

  await page.route('**/fonts.googleapis.com/**', async (route) => {
    await route.fulfill({ status: 200, contentType: 'text/css', body: '' });
  });
  await page.route('**/fonts.gstatic.com/**', async (route) => {
    await route.abort();
  });
  await page.route('http://localhost:8011/**', async (route) => {
    await route.abort();
  });

  await page.route(`**${VISUAL_K8S_BASE}/**`, async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname.replace(VISUAL_K8S_BASE, '') || '/';

    if (request.method() === 'OPTIONS') {
      await route.fulfill({
        status: 204,
        headers: {
          'access-control-allow-origin': '*',
          'access-control-allow-methods': 'GET,POST,PUT,DELETE,OPTIONS',
          'access-control-allow-headers': '*',
        },
      });
      return;
    }

    if (path === '/version') {
      await fulfillJson(route, { gitVersion: 'v1.30.0-visual' });
      return;
    }

    if (path === '/api/v1/namespaces') {
      await fulfillJson(route, listResponse([
        { apiVersion: 'v1', kind: 'Namespace', metadata: { name: VISUAL_NAMESPACE, namespace: VISUAL_NAMESPACE } },
        { apiVersion: 'v1', kind: 'Namespace', metadata: { name: 'default', namespace: 'default' } },
      ]));
      return;
    }

    if (path.endsWith(`/namespaces/${VISUAL_NAMESPACE}/modelapis`)) {
      await fulfillJson(route, listResponse(data.modelAPIs));
      return;
    }
    if (path.endsWith(`/namespaces/${VISUAL_NAMESPACE}/mcpservers`)) {
      await fulfillJson(route, listResponse(data.mcpServers));
      return;
    }
    if (path.endsWith(`/namespaces/${VISUAL_NAMESPACE}/agents`)) {
      await fulfillJson(route, listResponse(data.agents));
      return;
    }
    if (path.endsWith(`/namespaces/${VISUAL_NAMESPACE}/pods`)) {
      await fulfillJson(route, listResponse(data.pods));
      return;
    }
    if (path.endsWith(`/namespaces/${VISUAL_NAMESPACE}/deployments`)) {
      await fulfillJson(route, listResponse(data.deployments));
      return;
    }
    if (path.endsWith(`/namespaces/${VISUAL_NAMESPACE}/persistentvolumeclaims`)) {
      await fulfillJson(route, listResponse(data.pvcs));
      return;
    }
    if (path.endsWith(`/namespaces/${VISUAL_NAMESPACE}/services`)) {
      await fulfillJson(route, listResponse(data.services));
      return;
    }
    if (path.endsWith(`/namespaces/${VISUAL_NAMESPACE}/secrets`)) {
      await fulfillJson(route, listResponse(data.secrets));
      return;
    }

    if (path.includes(`/namespaces/${VISUAL_NAMESPACE}/pods/`) && path.includes('/log')) {
      await fulfillText(route, [
        '2025-01-15T12:00:00Z INFO starting KAOS runtime',
        '2025-01-15T12:00:01Z INFO connected to model API',
        '2025-01-15T12:00:02Z INFO health check passed',
      ].join('\n'));
      return;
    }

    if (path.includes(`/namespaces/${VISUAL_NAMESPACE}/services/`) && path.endsWith('/proxy/mcp')) {
      const body = request.postDataJSON() as { id?: string | number; method?: string } | null;
      const method = body?.method || 'tools/list';
      if (method === 'notifications/initialized') {
        await route.fulfill({ status: 202, headers: { 'access-control-allow-origin': '*' }, body: '' });
        return;
      }
      await fulfillJson(route, {
        jsonrpc: '2.0',
        id: body?.id ?? 'visual',
        result: jsonRpcResult(method),
      }, 200, { 'mcp-session-id': 'visual-session' });
      return;
    }

    if (path.includes(`/namespaces/${VISUAL_NAMESPACE}/services/`) && path.endsWith('/proxy/ready')) {
      await fulfillJson(route, { ready: true, tools: ['echo', 'summarize'] });
      return;
    }

    if (path.includes(`/namespaces/${VISUAL_NAMESPACE}/services/`) && path.includes('/proxy/.well-known/agent.json')) {
      await fulfillJson(route, {
        name: 'planner-agent',
        description: 'Visual fixture A2A agent card',
        url: `http://agent-planner-agent.${VISUAL_NAMESPACE}.svc.cluster.local:8000`,
        version: '1.0.0',
        capabilities: { streaming: true, pushNotifications: false },
        skills: [{ id: 'plan', name: 'Plan', description: 'Plan tasks' }],
      });
      return;
    }

    if (path.includes(`/namespaces/${VISUAL_NAMESPACE}/services/`) && path.endsWith('/proxy/')) {
      const body = request.postDataJSON() as { id?: string | number; method?: string } | null;
      await fulfillJson(route, {
        jsonrpc: '2.0',
        id: body?.id ?? 'visual-rpc',
        result: {
          id: 'task-visual-1',
          status: { state: body?.method === 'CancelTask' ? 'canceled' : 'completed' },
          artifacts: [{ parts: [{ type: 'text', text: 'Visual fixture task result.' }] }],
        },
      });
      return;
    }

    if (path.includes(`/namespaces/${VISUAL_NAMESPACE}/services/`) && path.includes('/proxy/memory/sessions')) {
      await fulfillJson(route, {
        sessions: [
          'session-visual-1',
          'session-visual-2',
        ],
        total: 2,
      });
      return;
    }

    if (path.includes(`/namespaces/${VISUAL_NAMESPACE}/services/`) && path.includes('/proxy/memory/events')) {
      await fulfillJson(route, {
        events: [
          { event_id: 'event-1', session_id: 'session-visual-1', event_type: 'user_message', content: 'Summarize cluster status', timestamp },
          { event_id: 'event-2', session_id: 'session-visual-1', event_type: 'tool_call', content: 'Called echo', timestamp },
          { event_id: 'event-3', session_id: 'session-visual-1', event_type: 'agent_response', content: 'Cluster resources are healthy.', timestamp },
        ],
      });
      return;
    }

    if (path.includes(`/namespaces/${VISUAL_NAMESPACE}/services/`) && path.includes('/proxy/v1/chat/completions')) {
      await fulfillJson(route, {
        session_id: 'session-visual-chat',
        choices: [{ message: { content: 'Visual fixture response.' }, delta: { content: 'Visual fixture response.' } }],
      });
      return;
    }

    if (request.method() === 'DELETE') {
      await fulfillJson(route, { apiVersion: 'v1', kind: 'Status', metadata: {}, status: 'Success', code: 200 });
      return;
    }

    await fulfillJson(route, listResponse([]));
  });
}
