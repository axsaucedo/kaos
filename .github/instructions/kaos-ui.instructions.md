---
applyTo: "kaos-ui/**"
---

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
kaos-ui/src/
├── components/          # React components
│   ├── agent/           # Agent-specific (Chat, Memory, Overview, Pods)
│   ├── mcp/             # MCPServer components (Overview, Pods, ToolsDebug)
│   ├── modelapi/        # ModelAPI components (Overview, Pods, Diagnostics)
│   ├── dashboard/       # Dashboard widgets (OverviewDashboard, VisualMap)
│   ├── kubernetes/      # K8s resources (PodsList, SecretsList)
│   ├── layout/          # Layout (MainLayout, Sidebar, Header)
│   ├── resources/       # Resource CRUD (List, CreateDialog, EditDialog)
│   │   └── shared/      # Shared editors (EnvVarEditor, LabelsAnnotationsEditor)
│   ├── settings/        # Settings components
│   ├── shared/          # Reusable (DeploymentStatusCard, YamlViewer)
│   └── ui/              # shadcn/ui base components (DO NOT MODIFY)
├── contexts/            # React contexts (KubernetesConnectionContext)
├── hooks/               # Custom hooks (useAgentChat, useRealKubernetesAPI)
├── lib/                 # Utilities (kubernetes-client.ts, agent-client.ts)
├── pages/               # Route pages
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
// API operations
const { createAgent, updateAgent, deleteAgent, refreshAll } = useKubernetesConnection();
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

See `kaos-ui-testing.instructions.md` for Playwright test patterns.

```bash
npm run dev              # UI at http://localhost:8081
kaos ui --no-browser     # Proxy at http://localhost:8010
npm run test:e2e         # All tests
```

## Additional Instruction Files
- `kaos-ui-components.instructions.md` — UI component patterns, Visual Map
- `kaos-ui-testing.instructions.md` — Playwright test patterns
- `kaos-ui-kubernetes-types.instructions.md` — CRD type sync guidelines
