---
applyTo: "kaos-ui/src/components/**"
---

# UI Component Guidelines

Instructions for developing UI components in KAOS-UI.

## Component Architecture

### Folder Structure

```
src/components/
├── agent/           # Agent-specific (Chat, Memory, Overview, Pods)
├── mcp/             # MCPServer (Overview, Pods, ToolsDebug)
├── modelapi/        # ModelAPI (Overview, Pods, Diagnostics)
├── dashboard/       # Dashboard widgets (OverviewDashboard, VisualMap)
│   └── visual-map/  # Enhanced visual topology module
│       ├── index.tsx              # ReactFlow orchestration + providers
│       ├── ResourceNode.tsx       # Custom node with semantic zoom, quick-action icons, context menu
│       ├── ColumnHeaderNode.tsx   # Column header label node
│       ├── VisualMapToolbar.tsx   # Filter bar, search, layout controls (Fit, Re-layout, Lock)
│       ├── VisualMapContextMenu.tsx # Right-click context menu for nodes
│       ├── useVisualMapLayout.ts  # Dagre auto-layout hook + locked-positions state
│       ├── useVisualMapFilters.ts # Graph-aware filter/search hook
│       ├── layout-engine.ts      # Dagre wrapper for computing node positions
│       └── types.ts              # Shared types (ResourceNodeData, filter state, etc.)
├── kubernetes/      # K8s resources (PodsList, SecretsList, CreateSecretDialog)
├── layout/          # Layout (MainLayout, Sidebar, Header, ConnectionStatus)
├── resources/       # Resource CRUD
│   ├── AgentList.tsx, AgentCreateDialog.tsx, AgentEditDialog.tsx
│   ├── MCPServerList.tsx, MCPServerCreateDialog.tsx, ...
│   ├── ModelAPIList.tsx, ModelAPICreateDialog.tsx, ...
│   └── shared/      # EnvVarEditor, LabelsAnnotationsEditor
├── settings/        # Settings page components
├── shared/          # Cross-cutting (DeploymentStatusCard, YamlViewer)
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
```tsx
<Button data-testid="create-agent-button">Create</Button>
<tr data-testid={`agent-row-${agent.metadata.name}`}>
```
