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

### Sidebar Structure

The sidebar is organized into 5 sections:

| Section | Items |
|---------|-------|
| **OVERVIEW** | Summary (id: `overview`), Visual Map (id: `visual-map`) |
| **KAOS RESOURCES** | Model APIs, MCP Servers, Agents |
| **KUBERNETES** | Pods, Secrets |
| **MONITORING** | KAOS System, KAOS Observability (id: `kaos-monitoring`) |
| **CONFIG** | Settings |

### Visual Map (`VisualMap.tsx` → `visual-map/`)

Interactive topology view using `@xyflow/react` with a custom zero-dependency layout engine:
- **3-tier column layout**: ModelAPIs (left), Agents (middle, multi-column by dependency depth), MCPServers (right)
- **Agent-to-agent edges**: derived from `agent.spec.agentNetwork.access[]` — each entry names a target agent the source can communicate with
- **Clustered layout**: union-find groups interconnected components; disconnected clusters are vertically separated using a global Y offset
- **Manual compact toggle**: Full Card ↔ Compact Pill via toolbar button (no zoom-based triggers)
- **Dynamic edge anchors**: `DynamicEdge.tsx` uses `getSmoothStepPath` with 4-point closest-anchor selection (top/bottom/left/right)
- **ModelAPI edge dimming**: toolbar eye toggle dims gray ModelAPI edges to reduce visual noise
- **Graph-aware filtering**: toggle by resource kind, status; search highlights + auto-pans to nodes
- **Status overlays**: colored status dots on nodes, edge labels (`model`/`tools`/`a2a`), animated edges
- **Context menus**: right-click for View Overview/YAML/Pods/Chat/Tools/Diagnostics, Focus in Graph, Edit
- **Draggable nodes**: controlled `useNodesState` with drag-to-lock positioning
- Edges derived from `agent.spec.modelAPI`, `agent.spec.mcpServers[]`, and `agent.spec.agentNetwork.access[]`
- `VisualMap.tsx` is a thin re-export; all logic lives in `visual-map/`
- **Always-mounted** with CSS `hidden` class to preserve pan/zoom state across tab switches

### Agent Chat Client (`src/lib/agent-client.ts`)

Dedicated streaming client for agent chat completions, separated from the general K8s CRUD client:
- Calls K8s service proxy directly: `/api/v1/namespaces/{ns}/services/{name}:8000/proxy/v1/chat/completions`
- Sets SSE headers (`Accept: text/event-stream`, `Cache-Control: no-cache`) to prevent proxy buffering
- Parses SSE `data:` lines inline via `ReadableStream` reader
- Detects progress blocks (`type: 'progress'`) and routes to `onProgress` callback
- Filters artifacts: standalone `{}`, markdown-wrapped `{}` blocks, `**Final Response to User:**` headers
- Used by `useAgentChat` hook; the general `kubernetes-client.ts` has no streaming code

### Component Naming

- PascalCase file names: `AgentOverview.tsx`
- Pattern: `{Resource}{Feature}.tsx`
- Examples: `AgentChat.tsx`, `MCPToolsDebug.tsx`, `ModelAPIDiagnostics.tsx`

## shadcn/ui Usage

### Import Pattern

```typescript
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { ScrollArea } from '@/components/ui/scroll-area';
```

### Badge Variants

```typescript
// Resource-specific
<Badge variant="agent">Agent</Badge>
<Badge variant="mcpserver">MCP Server</Badge>
<Badge variant="modelapi">Model API</Badge>

// Status
<Badge variant="success">Ready</Badge>
<Badge variant="warning">Pending</Badge>
<Badge variant="destructive">Failed</Badge>
<Badge variant="secondary">Unknown</Badge>
```

## Resource Detail Pages

### Standard Tab Structure

1. **Overview** - General info, status, configuration
2. **Chat** (Agent only) - Streaming chat with reasoning steps display; kept always-mounted via CSS visibility to preserve SSE streams across tab switches
3. **Memory** (Agent only) - Session history and events
4. **Pods** - Associated pods and their status
5. **YAML** - Raw resource definition (read-only)
6. Resource-specific tabs (Tools, Diagnostics)

### Example Pattern

```tsx
export default function AgentDetail() {
  const { namespace, name } = useParams();
  const [editDialogOpen, setEditDialogOpen] = useState(false);
  const { agents, refreshAll } = useKubernetesStore();
  
  const agent = agents.find(a => 
    a.metadata.name === name && a.metadata.namespace === namespace
  );

  const handleEditDialogClose = async () => {
    setEditDialogOpen(false);
    await refreshAll(); // Refresh after edit
  };

  return (
    <div className="space-y-6">
      {/* Header with actions */}
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">{agent.metadata.name}</h1>
        <Button onClick={() => setEditDialogOpen(true)}>Edit</Button>
      </div>

      {/* Tabs */}
      <Tabs defaultValue="overview">
        <TabsList>
          <TabsTrigger value="overview">Overview</TabsTrigger>
          <TabsTrigger value="chat">Chat</TabsTrigger>
          <TabsTrigger value="memory">Memory</TabsTrigger>
          <TabsTrigger value="pods">Pods</TabsTrigger>
          <TabsTrigger value="yaml">YAML</TabsTrigger>
        </TabsList>
        
        <TabsContent value="overview">
          <AgentOverview agent={agent} />
        </TabsContent>

        {/* Chat always mounted to preserve streaming state */}
        <div className={currentTab === 'chat' ? 'h-[calc(100vh-320px)]' : 'hidden'}>
          <AgentChat agent={agent} ... />
        </div>

        {/* ... other tabs */}
      </Tabs>

      {/* Edit Dialog */}
      <AgentEditDialog 
        agent={agent} 
        open={editDialogOpen} 
        onClose={handleEditDialogClose} 
      />
    </div>
  );
}
```

## Form Patterns

### React Hook Form + Zod

```tsx
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';

const schema = z.object({
  name: z.string().min(1, 'Name is required')
    .regex(/^[a-z0-9]([-a-z0-9]*[a-z0-9])?$/, 'Invalid K8s name'),
  model: z.string().min(1, 'Model is required'),
  modelAPI: z.string().min(1, 'ModelAPI is required'),
});

function AgentCreateDialog({ open, onClose }) {
  const { register, handleSubmit, watch, setValue, reset, formState: { errors } } = useForm({
    resolver: zodResolver(schema),
    defaultValues: { name: '', model: '', modelAPI: '' },
  });

  const onSubmit = async (data) => {
    await createAgent(data);
    reset();
    onClose();
  };

  return (
    <Dialog open={open} onOpenChange={onClose}>
      <DialogContent>
        <form onSubmit={handleSubmit(onSubmit)}>
          <div className="space-y-4">
            <div>
              <Label htmlFor="name">Name</Label>
              <Input id="name" {...register('name')} />
              {errors.name && <p className="text-sm text-destructive">{errors.name.message}</p>}
            </div>
            {/* ... */}
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
```

### EnvVar Editor Usage

```tsx
import { EnvVarEditorWithSecrets, EnvVarEntry, envVarEntriesToK8sEnvVars } from './shared/EnvVarEditorWithSecrets';

function MyForm() {
  const [envVars, setEnvVars] = useState<EnvVarEntry[]>([]);

  const onSubmit = async (data) => {
    const k8sEnvVars = envVarEntriesToK8sEnvVars(envVars);
    const resource = {
      // ...
      spec: {
        container: {
          env: k8sEnvVars,  // Use container.env (not config.env)
        },
      },
    };
  };

  return (
    <EnvVarEditorWithSecrets
      fields={envVars}
      onChange={setEnvVars}
      label="Environment Variables"
    />
  );
}
```

## Icons

Use Lucide React icons:

```typescript
import { 
  Bot,        // Agent
  Server,     // MCPServer
  Box,        // ModelAPI
  Boxes,      // Pods
  KeyRound,   // Secrets
  Settings,   // Settings
  Activity,   // Status
  Brain,      // Memory
  Send,       // Chat
  Wrench,     // Tools
} from 'lucide-react';
```

## Styling

### Resource Colors

```css
/* index.css tokens */
:root {
  --agent: 142 76% 36%;    /* Green */
  --mcp: 262 83% 58%;      /* Purple */
  --modelapi: 45 93% 47%;  /* Yellow/Orange */
}
```

```tsx
// Usage
<div className="text-agent">Agent text</div>
<div className="bg-modelapi/20">ModelAPI background</div>
<Badge variant="mcpserver">MCP Server</Badge>
```

### Layouts

```tsx
// Two-column grid
<div className="grid gap-6 md:grid-cols-2">

// Full-width card
<Card className="md:col-span-2">

// Info row
<div className="flex items-start justify-between gap-4">
  <span className="text-sm text-muted-foreground">{label}</span>
  <span className="text-sm font-medium">{value}</span>
</div>
```

## Error Handling

### Toast Notifications

```typescript
import { toast } from 'sonner';

// Success
toast.success('Agent created successfully');

// Error
toast.error('Failed to create agent', {
  description: error.message,
});
```

### Error States

```tsx
{error && (
  <Alert variant="destructive">
    <AlertCircle className="h-4 w-4" />
    <AlertDescription>{error}</AlertDescription>
  </Alert>
)}
```

## Responsive Design

- Use `md:` prefix for tablet+: `md:grid-cols-2`
- Use `lg:` prefix for desktop+: `lg:grid-cols-3`
- Mobile-first approach
- Sidebar collapses on mobile (handled by MainLayout)

## Data-TestID Conventions

Add test IDs for Playwright tests:

```tsx
<Button data-testid="create-agent-button">Create</Button>
<Input data-testid="agent-name-input" {...register('name')} />
<tr data-testid={`agent-row-${agent.metadata.name}`}>
```
