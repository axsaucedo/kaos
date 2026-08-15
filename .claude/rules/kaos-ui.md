---
paths:
  - "kaos-ui/**"
---

# KAOS-UI Instructions

Context and guidelines for AI coding assistants working with the KAOS-UI codebase.

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
| Vitest | Unit testing |
| Playwright | End-to-end testing |
| ESLint 9 | Linting (no-unused-vars: warn) |

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
kaos-ui/src/
├── components/          # React components
│   ├── agent/           # Agent-specific (Chat, Memory, Overview)
│   ├── mcp/             # MCPServer (Overview, ToolsDebug sub-components + hooks)
│   ├── modelapi/        # ModelAPI (Overview, Diagnostics)
│   ├── dashboard/       # Dashboard widgets (OverviewDashboard, VisualMap)
│   ├── kubernetes/      # K8s resources (PodsList, SecretsList, PodOverviewTab, PodLogsTab)
│   ├── layout/          # Layout (MainLayout, Sidebar, Header, ConnectionStatus)
│   ├── resources/       # Resource CRUD (List, CreateDialog, EditDialog)
│   │   ├── ResourceDetailDrawer.tsx  # Consolidated detail drawer (all resource types)
│   │   └── shared/      # EnvVarEditor, LabelsAnnotationsEditor, NameField
│   ├── settings/        # Settings components
│   ├── shared/          # Cross-cutting (DeploymentStatusCard, ResourcePods, YamlViewer)
│   └── ui/              # shadcn/ui base components (DO NOT MODIFY)
├── contexts/            # React contexts (KubernetesConnectionContext)
├── hooks/               # Custom hooks (useAgentChat, useResourceCrud, usePodLogs)
├── lib/                 # Utilities
│   ├── k8s/             # K8s client modules (client.ts, resources.ts, core.ts, proxy.ts, index.ts)
│   ├── agent-client.ts  # Agent chat SSE client
│   ├── status-utils.ts  # Status badge/color utilities
│   └── utils.ts         # General utils (cn, validateKubernetesName)
├── pages/               # Route pages
│   └── system/          # KAOSSystemPage sub-components (NamespaceManager, OperatorConfig, etc.)
├── stores/              # Zustand stores (kubernetesStore)
└── types/               # TypeScript types (kubernetes.ts, mcp.ts)
```

## KAOS Custom Resources (CRDs)

### ModelAPI
Provides LLM API endpoints. Two modes: **Proxy** (LiteLLM) and **Hosted** (Ollama).

### MCPServer
Model Context Protocol servers providing tools to agents. Uses runtime-based architecture (`python-string`, `kubernetes`, `custom`).

### Agent
AI agents with memory, tools, and multi-agent capabilities. References ModelAPI and MCPServers.

### Common Patterns
- `container.env` for environment variables (not `config.env` — deprecated)
- `ApiKeySource` supports `value` or `valueFrom.secretKeyRef`
- `gatewayRoute` for Gateway API exposure

## Code Patterns

### State Management
```typescript
// Zustand store
const { agents, modelAPIs, activeTab } = useKubernetesStore();
// API operations (via KubernetesConnectionContext)
const { createAgent, updateAgent, deleteAgent, refreshAll } = useKubernetesConnection();
// CRUD operations helper (wraps context with logging + refresh)
const { createResource, updateResource, deleteResource } = useResourceCrud(addLogEntry, refreshAll);
```

### Form Patterns
- React Hook Form + Zod for validation
- K8s name regex: `/^[a-z0-9]([-a-z0-9]*[a-z0-9])?$/`

### Agent Chat (agent-client.ts)
- SSE streaming via K8s service proxy
- Progress blocks (`type: 'progress'`) for tool/delegation actions
- Two-phase: progress events → streamed final response

## UI Conventions

### Badge Variants
- `success` for Ready/Running
- `warning` for Pending/Waiting
- `destructive` for Error/Failed

### Resource Colors
- Agent: green (`--agent: 142 76% 36%`)
- MCP: purple (`--mcp: 262 83% 58%`)
- ModelAPI: yellow (`--modelapi: 45 93% 47%`)

### Icons (Lucide React)
Bot (Agent), Server (MCP), Box (ModelAPI), Boxes (Pods), KeyRound (Secrets)

## Testing

See `kaos-ui-testing.md` for full testing details.
See `kaos-ui-visual-testing.md` before changing visual specs, snapshots, Tailwind/theme CSS, UI components, pages, or the visual CI workflow.

```bash
npm run dev              # UI at http://localhost:8081
kaos ui --no-browser     # Proxy at http://localhost:8010
npm run test:unit        # Vitest unit tests (63 tests)
npm run test:visual      # Offline visual regression tests
npm run test:e2e         # Playwright E2E tests (109 tests)
npm run lint             # ESLint
npm run build            # Type-check + build
```

CI runs automatically via `.github/workflows/kaos-ui-tests.yaml` on PRs touching `kaos-ui/`.

## Additional Instruction Files
- `kaos-ui-components.md` — UI component patterns, Visual Map
- `kaos-ui-testing.md` — Playwright test patterns
- `kaos-ui-visual-testing.md` — visual regression snapshots and CI comments
- `kaos-ui-kubernetes-types.md` — CRD type sync guidelines
