---
paths:
  - "kaos-ui/src/components/**"
---

# UI Component Guidelines

Instructions for developing UI components in KAOS-UI.

## Component Architecture

### Folder Structure

```
src/components/
├── agent/           # Agent-specific (Chat, Memory, Overview, ChatMessage, ReasoningSteps)
├── mcp/             # MCPServer (Overview, ToolsDebug sub-components + useMCPTools hook)
│   ├── MCPToolsDebug.tsx      # Main tools debug container
│   ├── MCPToolsList.tsx       # Tool listing panel
│   ├── MCPToolExecutor.tsx    # Tool execution form
│   ├── MCPToolResult.tsx      # Result display
│   ├── JsonSyntaxHighlight.tsx # JSON highlighting
│   ├── useMCPTools.ts         # Tools state hook
│   └── mcpToolsUtils.ts      # Utility functions
├── modelapi/        # ModelAPI (Overview, Diagnostics)
├── dashboard/       # Dashboard widgets (OverviewDashboard, VisualMap)
│   └── visual-map/  # Enhanced visual topology module
│       ├── index.tsx              # ReactFlow orchestration + providers
│       ├── ResourceNode.tsx       # Custom node with semantic zoom, quick-action icons, context menu
│       ├── ColumnHeaderNode.tsx   # Column header label node
│       ├── DynamicEdge.tsx        # Custom edge with 4-point closest-anchor selection
│       ├── ResourceStatusLegend.tsx # Status legend overlay
│       ├── VisualMapToolbar.tsx   # Filter bar, search, layout controls (Fit, Re-layout, Lock)
│       ├── VisualMapContextMenu.tsx # Right-click context menu for nodes
│       ├── useVisualMapLayout.ts  # Dagre auto-layout hook + locked-positions state
│       ├── useVisualMapFilters.ts # Graph-aware filter/search hook
│       ├── layout-engine.ts      # Dagre wrapper for computing node positions
│       └── types.ts              # Shared types (ResourceNodeData, filter state, etc.)
├── kubernetes/      # K8s resources (PodsList, SecretsList, CreateSecretDialog, PodOverviewTab, PodLogsTab, ContainerSelector)
├── layout/          # Layout (MainLayout, Sidebar, Header, ConnectionStatus, GlobalSearch, AutoRefreshControl)
├── resources/       # Resource CRUD
│   ├── AgentList.tsx, AgentCreateDialog.tsx, AgentEditDialog.tsx
│   ├── MCPServerList.tsx, MCPServerCreateDialog.tsx, ...
│   ├── ModelAPIList.tsx, ModelAPICreateDialog.tsx, ...
│   ├── ResourceList.tsx           # Shared list component
│   ├── ResourceDetailDrawer.tsx   # Consolidated detail drawer (replaces per-resource drawers)
│   └── shared/      # EnvVarEditor, LabelsAnnotationsEditor, NameField, ApiKeySecretPicker
├── settings/        # Settings page components
├── shared/          # Cross-cutting (DeploymentStatusCard, ResourcePods, YamlViewer)
├── theme/           # Theme (ThemeProvider, ThemeToggle)
└── ui/              # shadcn/ui base components (DO NOT MODIFY)
```

### Visual Map (`visual-map/`)

Interactive topology view using `@xyflow/react`:
- **3-tier column layout**: ModelAPIs (left), Agents (middle), MCPServers (right)
- **Agent-to-agent edges**: from `agent.spec.agentNetwork.access[]`
- **Clustered layout**: union-find groups interconnected components
- **Manual compact toggle**: Full Card ↔ Compact Pill via toolbar button
- **Dynamic edge anchors**: `DynamicEdge.tsx` with 4-point closest-anchor selection
- **Graph-aware filtering**: toggle by resource kind, status; search highlights + auto-pans
- **Always-mounted** with CSS `hidden` class to preserve pan/zoom state

### Agent Chat Client (`src/lib/agent-client.ts`)

- Calls K8s service proxy: `/api/v1/namespaces/{ns}/services/{name}:8000/proxy/v1/chat/completions`
- SSE streaming with progress blocks and artifact filtering
- Used by `useAgentChat` hook

### Kubernetes Client (`src/lib/k8s/`)

The monolithic `kubernetes-client.ts` has been split into focused modules:
- `core.ts` — Base K8s API functions (fetch wrapper, error handling)
- `resources.ts` — CRUD operations for KAOS CRDs (Agent, MCPServer, ModelAPI)
- `proxy.ts` — Service proxy and port-forward utilities
- `client.ts` — High-level client class composing core/resources/proxy
- `index.ts` — Re-exports for backward compatibility

The legacy `kubernetes-client.ts` still exists as a re-export shim.

### Shared Components

#### ResourceDetailDrawer (`src/components/resources/ResourceDetailDrawer.tsx`)
Consolidated detail drawer replacing the three per-resource drawers (AgentDetail, MCPServerDetail, ModelAPIDetail). Uses generics to handle all resource types with shared tab structure.

#### ResourcePods (`src/components/shared/ResourcePods.tsx`)
Consolidated pod listing component replacing per-resource pod tabs. Shows pods filtered by resource type and name.

#### NameField (`src/components/resources/shared/NameField.tsx`)
Shared form field for Kubernetes resource names with built-in validation (`validateKubernetesName` from `src/lib/utils.ts`).

### Status Utilities (`src/lib/status-utils.ts`)
Extracted status badge/color logic used across components. Provides consistent status rendering for all resource types.

### System Page (`src/pages/system/`)
`KAOSSystemPage.tsx` split into sub-components:
- `SystemOverview.tsx` — Cluster overview panel
- `OperatorConfig.tsx` — Operator configuration
- `NamespaceManager.tsx` — Namespace management
- `SystemLogs.tsx` — System log viewer
- `useKAOSResources.ts` — Data fetching hook

### Component Naming

- PascalCase file names: `AgentOverview.tsx`
- Pattern: `{Resource}{Feature}.tsx`

## shadcn/ui Usage

```typescript
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
```

### Badge Variants
```typescript
<Badge variant="agent">Agent</Badge>
<Badge variant="mcpserver">MCP Server</Badge>
<Badge variant="modelapi">Model API</Badge>
<Badge variant="success">Ready</Badge>
<Badge variant="destructive">Failed</Badge>
```

## Resource Detail Pages

### Standard Tab Structure
1. **Overview** — General info, status, configuration
2. **Chat** (Agent only) — Always-mounted via CSS visibility for SSE preservation
3. **Memory** (Agent only) — Session history and events
4. **Pods** — Associated pods
5. **YAML** — Raw resource definition

## Form Patterns

### React Hook Form + Zod
```tsx
const schema = z.object({
  name: z.string().min(1).regex(/^[a-z0-9]([-a-z0-9]*[a-z0-9])?$/),
  model: z.string().min(1),
});
```

### EnvVar Editor
```tsx
import { EnvVarEditorWithSecrets, envVarEntriesToK8sEnvVars } from './shared/EnvVarEditorWithSecrets';
// Use container.env (not config.env)
```

## Icons (Lucide React)
Bot (Agent), Server (MCP), Box (ModelAPI), Boxes (Pods), KeyRound (Secrets), Settings, Activity (Status)

## Styling

### Resource Colors
```css
:root {
  --agent: 142 76% 36%;    /* Green */
  --mcp: 262 83% 58%;      /* Purple */
  --modelapi: 45 93% 47%;  /* Yellow/Orange */
}
```

## Error Handling
```typescript
import { toast } from 'sonner';
toast.success('Agent created successfully');
toast.error('Failed to create agent', { description: error.message });
```

## Data-TestID Conventions

Systematic `data-testid` attributes are applied throughout the codebase for reliable test targeting.

```tsx
<Button data-testid="create-agent-button">Create</Button>
<tr data-testid={`agent-row-${agent.metadata.name}`}>
```
