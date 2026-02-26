# KAOS-UI Copilot Instructions

Context and guidelines for GitHub Copilot and AI coding assistants working with the KAOS-UI codebase.

## Project Overview

**KAOS-UI** is a React-based web dashboard for the Kubernetes Agent Orchestration System (KAOS). It provides real-time visibility and management of AI agents, MCP servers, and Model APIs running on Kubernetes.

### Technology Stack

| Technology | Purpose |
|------------|---------|
| React 18 | UI framework |
| TypeScript | Type safety |
| Vite | Build tooling |
| Tailwind CSS | Styling |
| shadcn/ui | Component library |
| Zustand | State management |
| TanStack Query | Server state caching |
| React Router | Client-side routing |
| Playwright | End-to-end testing |

## Architecture

```
┌─────────────┐     ┌──────────────┐     ┌─────────────────┐
│   Browser   │────▶│  KAOS Proxy  │────▶│  Kubernetes API │
│  (KAOS UI)  │     │  (kaos ui)   │     │    (cluster)    │
└─────────────┘     └──────────────┘     └─────────────────┘
```

The UI is a static SPA that connects to Kubernetes via a CORS proxy (`kaos ui --no-browser`).

## Directory Structure

```
src/
├── components/          # React components
│   ├── agent/           # Agent-specific (Chat, ChatMessage, ReasoningSteps, Memory, Overview, Pods)
│   ├── mcp/             # MCPServer components (Overview, Pods, ToolsDebug)
│   ├── modelapi/        # ModelAPI components (Overview, Pods, Diagnostics)
│   ├── dashboard/       # Dashboard widgets (OverviewDashboard)
│   ├── kubernetes/      # K8s resources (PodsList, SecretsList, DeploymentsList)
│   ├── layout/          # Layout (MainLayout, Sidebar, Header, ConnectionStatus)
│   ├── resources/       # Resource CRUD (List, CreateDialog, EditDialog, DetailDrawer)
│   │   └── shared/      # Shared editors (EnvVarEditor, LabelsAnnotationsEditor)
│   ├── settings/        # Settings (ConnectionSettings, AppearanceSettings)
│   ├── shared/          # Reusable (DeploymentStatusCard, YamlViewer)
│   └── ui/              # shadcn/ui base components (do NOT modify directly)
├── contexts/            # React contexts (KubernetesConnectionContext)
├── hooks/               # Custom hooks (useAgentChat, useRealKubernetesAPI)
├── lib/                 # Utilities
│   ├── kubernetes-client.ts  # K8s API client with CRD CRUD
│   └── utils.ts              # General utilities
├── pages/               # Route pages (Index, AgentDetail, etc.)
├── stores/              # Zustand stores (kubernetesStore)
└── types/               # TypeScript types
    ├── kubernetes.ts    # KAOS CRD types (Agent, MCPServer, ModelAPI)
    └── mcp.ts           # MCP protocol types
```

## KAOS Custom Resources (CRDs)

### 1. ModelAPI

Provides LLM API endpoints. Two modes:
- **Proxy**: Routes to external LLM providers via LiteLLM
- **Hosted**: Runs Ollama locally in the cluster

```typescript
interface ModelAPISpec {
  mode: 'Proxy' | 'Hosted';
  proxyConfig?: {
    models: string[];           // REQUIRED: e.g., ["openai/gpt-4o", "*"]
    provider?: string;          // LiteLLM provider prefix
    apiBase?: string;           // Backend URL
    apiKey?: ApiKeySource;      // API key (value or secretKeyRef)
    configYaml?: ConfigYamlSource;
    env?: EnvVar[];             // DEPRECATED: use container.env
  };
  hostedConfig?: {
    model: string;              // Single Ollama model
    env?: EnvVar[];             // DEPRECATED: use container.env
  };
  container?: {                 // NEW: container overrides
    image?: string;
    env?: EnvVar[];
    resources?: Record<string, unknown>;
  };
  gatewayRoute?: GatewayRoute;
  podSpec?: Record<string, unknown>;
}
```

### 2. MCPServer

Model Context Protocol servers providing tools to agents.

```typescript
interface MCPServerSpec {
  // New format (preferred)
  runtime?: string;              // e.g., "python-string", "kubernetes", "custom"
  params?: string;               // Runtime-specific config (YAML string)
  serviceAccountName?: string;
  container?: {
    image?: string;
    env?: EnvVar[];
    resources?: Record<string, unknown>;
  };
  telemetry?: { enabled?: boolean; endpoint?: string };
  
  // Legacy format (backward compatible)
  type?: 'python-runtime' | 'node-runtime';
  config?: {
    tools?: { fromPackage?: string; fromString?: string; fromSecretKeyRef?: {...} };
    env?: EnvVar[];              // DEPRECATED: use container.env
  };
  
  gatewayRoute?: GatewayRoute;
  podSpec?: Record<string, unknown>;
}
```

### 3. Agent

AI agents with memory, tools, and multi-agent capabilities.

```typescript
interface AgentSpec {
  modelAPI: string;              // REQUIRED: Reference to ModelAPI name
  model: string;                 // REQUIRED: Model identifier (must be supported by ModelAPI)
  mcpServers?: string[];         // References to MCPServer names
  config?: {
    description?: string;
    instructions?: string;
    reasoningLoopMaxSteps?: number;
    memory?: {
      enabled?: boolean;         // Default: true
      type?: 'local';
      contextLimit?: number;     // Default: 6
      maxSessions?: number;      // Default: 1000
      maxSessionEvents?: number; // Default: 500
    };
    env?: EnvVar[];              // DEPRECATED: use container.env
  };
  agentNetwork?: {
    expose?: boolean;
    access?: string[];
  };
  container?: {                  // NEW: container overrides
    image?: string;
    env?: EnvVar[];
    resources?: Record<string, unknown>;
  };
  waitForDependencies?: boolean;
  gatewayRoute?: GatewayRoute;
  podSpec?: Record<string, unknown>;
}
```

### Common Types

```typescript
// API key with secret reference
interface ApiKeySource {
  value?: string;                    // Direct value (not for production)
  valueFrom?: {
    secretKeyRef?: { name: string; key: string };
  };
}

// Environment variable
interface EnvVar {
  name: string;
  value?: string;
  valueFrom?: {
    secretKeyRef?: { name: string; key: string };
    configMapKeyRef?: { name: string; key: string };
  };
}
```

## Code Patterns

### Component Structure

```tsx
// Standard component pattern
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import type { Agent } from '@/types/kubernetes';

interface AgentOverviewProps {
  agent: Agent;
}

export function AgentOverview({ agent }: AgentOverviewProps) {
  // Component logic
}
```

### State Management

```typescript
// Zustand store access
import { useKubernetesStore } from '@/stores/kubernetesStore';

function MyComponent() {
  const { agents, modelAPIs, activeTab, setActiveTab } = useKubernetesStore();
}

// API operations via context
import { useKubernetesConnection } from '@/contexts/KubernetesConnectionContext';

function MyForm() {
  const { createAgent, updateAgent, deleteAgent, refreshAll } = useKubernetesConnection();
}
```

### K8s Client Usage

```typescript
import { k8sClient } from '@/lib/kubernetes-client';

// Direct API calls
const agents = await k8sClient.listAgents(namespace);
const agent = await k8sClient.getAgent(name, namespace);

// Service proxy (for chat, tools, etc.)
const response = await k8sClient.proxyServiceRequest(
  'agent-my-agent', '/chat/completions', { method: 'POST', body: '...' }, namespace
);

// Chat completion with SSE streaming (two-phase agentic loop)
// Phase 1: Progress blocks (tool_call, delegate actions)
// Phase 2: Streamed final response tokens
await k8sClient.streamChatCompletion(serviceName, messages, {
  namespace,
  stream: true,
  onProgress: (progress) => { /* { type: 'progress', step, max_steps, action, target } */ },
  onChunk: (content) => { /* streamed content token */ },
  onDone: (metadata) => { /* { sessionId? } */ },
  onError: (error) => { /* Error */ },
  signal: abortController.signal,
});
```

### Form Patterns

```typescript
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';

const schema = z.object({
  name: z.string().min(1).regex(/^[a-z0-9]([-a-z0-9]*[a-z0-9])?$/),
  model: z.string().min(1),
});

function CreateForm() {
  const { register, handleSubmit, formState: { errors } } = useForm({
    resolver: zodResolver(schema),
  });
  
  const onSubmit = async (data) => { /* ... */ };
}
```

## UI Conventions

### Badge Variants for Status

```typescript
const getStatusVariant = (phase?: string) => {
  switch (phase) {
    case 'Running':
    case 'Ready': return 'success';
    case 'Pending':
    case 'Waiting': return 'warning';
    case 'Error':
    case 'Failed': return 'destructive';
    default: return 'secondary';
  }
};
```

### Resource Color Tokens

```css
/* Defined in index.css */
:root {
  --agent: 142 76% 36%;    /* Green */
  --mcp: 262 83% 58%;      /* Purple */
  --modelapi: 45 93% 47%;  /* Yellow/Orange */
}
```

### Data-TestId Conventions

Add `data-testid` to interactive elements for Playwright tests:
- `data-testid="create-agent-button"`
- `data-testid="agent-list-row-{name}"`
- `data-testid="save-button"`

## Testing

### Prerequisites

```bash
npm run dev              # UI at http://localhost:8081
kaos ui --no-browser     # Proxy at http://localhost:8010
# KIND cluster with KAOS resources in kaos-hierarchy namespace
```

### Running Tests

```bash
npm run test:e2e                     # All tests
npm run test:e2e:ui                  # Interactive UI mode
npm run test:e2e -- tests/crud/      # CRUD tests only
npm run test:e2e -- --headed         # Visible browser
```

### Test Structure

```typescript
import { test, expect } from '@playwright/test';
import { setupConnection, TEST_CONFIG } from '../fixtures/test-utils';

test.describe('Feature', () => {
  test.beforeEach(async ({ page }) => {
    await setupConnection(page, {
      proxyUrl: TEST_CONFIG.proxyUrl,
      namespace: TEST_CONFIG.namespace,
    });
  });

  test('should do something', async ({ page }) => {
    await page.getByRole('button', { name: /agents/i }).click();
    await expect(page.getByText('Agent List')).toBeVisible();
  });
});
```

## Common Tasks

### Adding a New CRD Field

1. Update type in `src/types/kubernetes.ts`
2. Update Overview component to display field
3. Update Create/Edit dialogs if editable
4. Sync with KAOS operator types

### Adding a New Test

1. Create file in appropriate `tests/` subdirectory
2. Use fixtures from `tests/fixtures/test-utils.ts`
3. Use unique names: `test-{resource}-${Date.now()}`
4. Clean up resources after tests

## Additional Guidelines

See specific instruction files:
- `.github/instructions/components.instructions.md` - UI patterns
- `.github/instructions/testing.instructions.md` - Test patterns
- `.github/instructions/kubernetes-types.instructions.md` - CRD sync
