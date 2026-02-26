# Kubernetes Types Instructions

Guidelines for managing KAOS CRD type definitions in the UI.

## Overview

The KAOS-UI TypeScript types in `src/types/kubernetes.ts` must stay in sync with the KAOS operator Go types.

## Current CRD Structure (v1alpha1)

### ModelAPI

```typescript
interface ModelAPISpec {
  mode: 'Proxy' | 'Hosted';
  
  // Proxy mode (LiteLLM)
  proxyConfig?: {
    models: string[];          // REQUIRED: ["openai/gpt-4o", "*", "openai/*"]
    provider?: string;         // LiteLLM provider prefix
    apiBase?: string;          // Backend LLM URL
    apiKey?: ApiKeySource;     // API key for authentication
    configYaml?: ConfigYamlSource; // Advanced LiteLLM config
    env?: EnvVar[];            // DEPRECATED
  };
  
  // Hosted mode (Ollama)
  hostedConfig?: {
    model: string;             // Ollama model to run
    env?: EnvVar[];            // DEPRECATED
  };
  
  // Common
  container?: {                // NEW: container overrides
    image?: string;
    env?: EnvVar[];            // Use this for env vars
    resources?: Record<string, unknown>;
  };
  gatewayRoute?: GatewayRoute;
  podSpec?: Record<string, unknown>;
}

interface ModelAPIStatus {
  phase?: string;              // Pending, Ready, Failed
  ready?: boolean;
  endpoint?: string;
  message?: string;
  supportedModels?: string[];  // Models this API supports
  deployment?: DeploymentStatusInfo;
}
```

### MCPServer

```typescript
interface MCPServerSpec {
  // New format (preferred)
  runtime?: string;            // "python-string", "kubernetes", "pctx", "custom"
  params?: string;             // Runtime-specific config (YAML or JSON for pctx)
  serviceAccountName?: string; // For RBAC
  
  // Legacy format (backward compatible)
  type?: 'python-runtime' | 'node-runtime';
  config?: {
    tools?: MCPToolsConfig;
    env?: EnvVar[];            // DEPRECATED
  };
  
  // Common
  container?: {                // NEW: container overrides
    image?: string;
    env?: EnvVar[];
    resources?: Record<string, unknown>;
  };
  telemetry?: {
    enabled?: boolean;
    endpoint?: string;
  };
  gatewayRoute?: GatewayRoute;
  podSpec?: Record<string, unknown>;
}

interface MCPServerStatus {
  phase?: string;
  ready?: boolean;
  endpoint?: string;
  availableTools?: string[];
  message?: string;
  deployment?: DeploymentStatusInfo;
}
```

### Agent

```typescript
interface AgentSpec {
  modelAPI: string;            // REQUIRED: Reference to ModelAPI
  model: string;               // REQUIRED: Model identifier
  mcpServers?: string[];
  config?: {
    description?: string;
    instructions?: string;
    reasoningLoopMaxSteps?: number; // 1-20, default 5
    memory?: AgentMemoryConfig;
    env?: EnvVar[];            // DEPRECATED
  };
  agentNetwork?: AgentNetworkConfig;
  container?: {                // NEW: container overrides
    image?: string;
    env?: EnvVar[];
    resources?: Record<string, unknown>;
  };
  waitForDependencies?: boolean;
  gatewayRoute?: GatewayRoute;
  podSpec?: Record<string, unknown>;
}

interface AgentMemoryConfig {
  enabled?: boolean;           // Default: true
  type?: 'local';              // Only local supported
  contextLimit?: number;       // Default: 6
  maxSessions?: number;        // Default: 1000
  maxSessionEvents?: number;   // Default: 500
}

interface AgentStatus {
  phase?: string;              // Pending, Ready, Failed, Waiting
  ready?: boolean;
  endpoint?: string;
  model?: string;              // Model being used
  linkedResources?: Record<string, string>;
  message?: string;
  deployment?: DeploymentStatusInfo;
}
```

## Common Types

### ApiKeySource

API keys support direct values or secret references:

```typescript
interface ApiKeySource {
  value?: string;              // Direct value (NOT for production)
  valueFrom?: {
    secretKeyRef?: {
      name: string;
      key: string;
    };
    // Note: configMapKeyRef removed - secrets only
  };
}
```

### EnvVar

Standard Kubernetes environment variable pattern:

```typescript
interface EnvVar {
  name: string;
  value?: string;
  valueFrom?: {
    secretKeyRef?: { name: string; key: string };
    configMapKeyRef?: { name: string; key: string };
  };
}
```

### DeploymentStatusInfo

For rolling update visibility:

```typescript
interface DeploymentStatusInfo {
  replicas?: number;
  readyReplicas?: number;
  availableReplicas?: number;
  updatedReplicas?: number;
  conditions?: {
    type: string;
    status: string;
    reason?: string;
    message?: string;
  }[];
}
```

## Type Mapping: Go → TypeScript

| Go Type | TypeScript Type |
|---------|-----------------|
| `string` | `string` |
| `[]string` | `string[]` |
| `*string` | `string \| undefined` or optional |
| `map[string]string` | `Record<string, string>` |
| `bool` | `boolean` |
| `int32` | `number` |
| `struct { ... }` | `interface { ... }` |
| `*SomeType` | `SomeType?` |

## Adding New Fields

1. **Update TypeScript interface** in `src/types/kubernetes.ts`
2. **Update Overview component** to display the field
3. **Update Create/Edit dialogs** if field is editable
4. **Add tests** for the new field

Example:

```typescript
// 1. Add to type
interface ProxyConfig {
  models: string[];
  provider?: string;  // NEW FIELD
  // ...
}

// 2. Display in Overview
{modelAPI.spec.proxyConfig?.provider && (
  <InfoRow label="Provider" value={modelAPI.spec.proxyConfig.provider} />
)}

// 3. Add to form
<Input
  {...register('provider')}
  placeholder="e.g., openai"
/>
```

## Breaking Changes (Alpha)

The project is in alpha, so breaking changes are permitted:

- `config.env` → `container.env` for all CRDs
- `proxyConfig.model` → `proxyConfig.models` (array)
- `apiKeySource.valueFrom.configMapKeyRef` → removed (secrets only)
- `spec.model` added as required field on Agent

## Validation

```bash
npm run build   # Catches type errors
npm run dev     # Visual verification
```
