# CLI Command Reference

Complete reference for all KAOS CLI commands.

## Command Structure

```
kaos <subcommand> <action> [OPTIONS]
```

Subcommands:
- `system` - Operator and cluster management
- `mcp` - MCPServer management
- `agent` - Agent management  
- `modelapi` - ModelAPI management
- `memory` - MemoryStore recall and erasure
- `samples` - Example deployment management
- `ui` - Web UI

---

## kaos system

Operator installation and cluster management.

### kaos system install

Install the KAOS operator.

```bash
kaos system install [OPTIONS]
```

| Option | Short | Default | Description |
|--------|-------|---------|-------------|
| `--namespace` | `-n` | `kaos-system` | Installation namespace |
| `--release-name` | | `kaos` | Helm release name |
| `--version` | | latest | Chart version |
| `--set` | | | Helm values |
| `--wait` | | false | Wait for ready |
| `--monitoring-enabled` | | | Install monitoring stack (`signoz` or `jaeger`) |
| `--gateway-enabled` | | false | Install Gateway API (Envoy Gateway) and configure routing |
| `--metallb-enabled` | | false | Install MetalLB for LoadBalancer support (KIND/bare-metal) |
| `--chart-path` | | | Path to local Helm chart directory (for development) |

### kaos system uninstall

Uninstall the KAOS operator.

```bash
kaos system uninstall [OPTIONS]
```

| Option | Default | Description |
|--------|---------|-------------|
| `--namespace` | `kaos-system` | Namespace to uninstall from |
| `--release-name` | `kaos` | Helm release name |
| `--monitoring-enabled` | | Also uninstall monitoring (`signoz` or `jaeger`) |
| `--gateway-enabled` | false | Also uninstall Gateway API (Envoy Gateway) |
| `--metallb-enabled` | false | Also uninstall MetalLB |

### kaos system status

Show cluster status.

```bash
kaos system status
```

Shows operator health, CRDs, resources, and gateway status.

### kaos system runtimes

List registered MCP runtimes.

```bash
kaos system runtimes [OPTIONS]
```

| Option | Short | Default | Description |
|--------|-------|---------|-------------|
| `--namespace` | `-n` | `kaos-system` | Operator namespace |

### kaos system create-rbac

Generate RBAC YAML for MCPServer ServiceAccounts.

```bash
kaos system create-rbac [OPTIONS]
```

| Option | Short | Description |
|--------|-------|-------------|
| `--name` | `-n` | ServiceAccount name (required) |
| `--namespace` | `-ns` | Namespace(s) to access |
| `--read-only` | | Read-only permissions |
| `--cluster-wide` | | ClusterRole instead of Role |
| `--output` | `-o` | Output file (default: stdout) |

**Example:**
```bash
kaos system create-rbac --name k8s-mcp-sa --namespace my-ns > rbac.yaml
kubectl apply -f rbac.yaml
```

---

## kaos mcp

MCPServer lifecycle management.

### kaos mcp init

Scaffold a new FastMCP server project.

```bash
kaos mcp init [DIRECTORY] [OPTIONS]
```

| Option | Description |
|--------|-------------|
| `--force` | Overwrite existing files |

Creates: `server.py`, `requirements.txt`, `README.md`

### kaos mcp build

Build a Docker image from FastMCP server.

```bash
kaos mcp build [OPTIONS]
```

| Option | Short | Default | Description |
|--------|-------|---------|-------------|
| `--name` | `-n` | (required) | Image name |
| `--tag` | `-t` | `latest` | Image tag |
| `--dir` | `-d` | `.` | Source directory |
| `--entry` | `-e` | `server.py` | Entry point |
| `--kind-load` | | | Load to KIND cluster |
| `--create-dockerfile` | | | Generate Dockerfile |
| `--platform` | | | Docker platform |

**Example:**
```bash
kaos mcp build --name my-mcp --tag v1 --kind-load
```

### kaos mcp deploy

Deploy an MCPServer.

```bash
kaos mcp deploy [NAME] [OPTIONS]
```

| Option | Short | Description |
|--------|-------|-------------|
| `NAME` | | MCPServer name (auto-inferred from pyproject.toml) |
| `--image` | `-i` | Custom image |
| `--runtime` | `-r` | Registered runtime |
| `--namespace` | `-n` | Target namespace |
| `--params` | `-p` | Runtime parameters |
| `--sa` | | ServiceAccount name |

**Examples:**
```bash
# From custom image
kaos mcp deploy my-mcp --image my-image:v1

# From registered runtime
kaos mcp deploy slack-mcp --runtime slack

# Auto-infer from pyproject.toml
kaos mcp deploy
```

### kaos mcp list

List MCPServers.

```bash
kaos mcp list [OPTIONS]
```

| Option | Short | Default | Description |
|--------|-------|---------|-------------|
| `--namespace` | `-n` | all | Filter by namespace |
| `--output` | `-o` | `wide` | Output format |

### kaos mcp get

Get MCPServer details.

```bash
kaos mcp get NAME [OPTIONS]
```

### kaos mcp logs

View MCPServer logs.

```bash
kaos mcp logs NAME [OPTIONS]
```

| Option | Short | Description |
|--------|-------|-------------|
| `--follow` | `-f` | Stream logs |
| `--tail` | | Number of lines |

### kaos mcp invoke

Invoke an MCP tool.

```bash
kaos mcp invoke NAME [OPTIONS]
```

| Option | Short | Description |
|--------|-------|-------------|
| `--tool` | `-t` | Tool name (required) |
| `--args` | `-a` | JSON arguments |
| `--port` | `-p` | Local port (default: 9000) |

**Example:**
```bash
kaos mcp invoke echo-mcp --tool echo --args '{"message": "hello"}'
```

### kaos mcp delete

Delete an MCPServer.

```bash
kaos mcp delete NAME [OPTIONS]
```

---

## kaos agent

Agent lifecycle management.

### kaos agent deploy

Deploy an Agent.

```bash
kaos agent deploy NAME --modelapi MODELAPI --model MODEL [OPTIONS]
```

| Option | Short | Description |
|--------|-------|-------------|
| `NAME` | | Agent name (required) |
| `--modelapi` | `-a` | ModelAPI reference (required) |
| `--model` | `-m` | Model name (required) |
| `--namespace` | `-n` | Target namespace |
| `--instructions` | `-i` | Agent instructions |
| `--mcp` | | MCP server references (multiple) |
| `--sub-agent` | | Sub-agent references (multiple) |

**Examples:**
```bash
# Basic agent
kaos agent deploy my-agent --modelapi my-api --model gpt-4o

# With instructions and MCP tools
kaos agent deploy my-agent -a my-api -m gpt-4o -i "You are a helpful assistant" --mcp calculator
```

### kaos agent list

List Agents.

```bash
kaos agent list [OPTIONS]
```

### kaos agent get

Get Agent details.

```bash
kaos agent get NAME [OPTIONS]
```

### kaos agent logs

View Agent logs.

```bash
kaos agent logs NAME [OPTIONS]
```

### kaos agent invoke

Send a message to an Agent.

```bash
kaos agent invoke NAME [OPTIONS]
```

| Option | Short | Description |
|--------|-------|-------------|
| `--message` | `-m` | Message (required) |
| `--namespace` | `-n` | Namespace of the Agent |
| `--port` | `-p` | Local port (default: 9001) |
| `--stream` | `-s` | Stream response |
| `--session` | | Conversation session ID, sent as `X-Session-ID` |

**Example:**
```bash
kaos agent invoke my-agent -n my-namespace --session ticket-42 --message "Hello, how are you?"
```

User identity is not selectable with an invoke flag. On OIDC-enabled clusters it comes from the verified bearer token presented through the gateway.

### kaos agent delete

Delete an Agent.

```bash
kaos agent delete NAME [OPTIONS]
```

### kaos agent tools

Show the tool names and JSON schemas an Agent presents to its model. This includes the entitled `level` enum on `search_memory`.

```bash
kaos agent tools NAME [-n NAMESPACE] [--json]
```

### kaos agent a2a send

Send a message to an Agent via A2A JSON-RPC protocol.

```bash
kaos agent a2a send NAME --message "Hello" [OPTIONS]
```

| Option | Short | Description |
|--------|-------|-------------|
| `NAME` | | Agent name (required) |
| `--message` | `-m` | Message to send (required) |
| `--async` | | Execute as async task (returns task ID for polling) |
| `--session-id` | `-s` | Session/context ID |
| `--namespace` | `-n` | Namespace of the Agent |
| `--port` | `-p` | Local port for port-forwarding (default: 9004) |
| `--json` | | Output raw JSON response |

```bash
# Sync message (waits for response)
kaos agent a2a send my-agent --message "Check status"

# Async task (returns task ID immediately)
kaos agent a2a send my-agent --message "Analyze logs" --async --json
```

### kaos agent a2a get

Get task status from an Agent via A2A GetTask.

```bash
kaos agent a2a get NAME --task-id TASK_ID [OPTIONS]
```

| Option | Short | Description |
|--------|-------|-------------|
| `NAME` | | Agent name (required) |
| `--task-id` | `-t` | Task ID to retrieve (required) |
| `--namespace` | `-n` | Namespace of the Agent |
| `--port` | `-p` | Local port for port-forwarding (default: 9004) |
| `--json` | | Output raw JSON response |

### kaos agent a2a cancel

Cancel a task on an Agent via A2A CancelTask.

```bash
kaos agent a2a cancel NAME --task-id TASK_ID [OPTIONS]
```

| Option | Short | Description |
|--------|-------|-------------|
| `NAME` | | Agent name (required) |
| `--task-id` | `-t` | Task ID to cancel (required) |
| `--namespace` | `-n` | Namespace of the Agent |
| `--port` | `-p` | Local port for port-forwarding (default: 9004) |
| `--json` | | Output raw JSON response |

---

## kaos memory

Inspect or erase a central `MemoryStore` through a temporary Kubernetes port-forward. `--store` can be omitted when the namespace contains exactly one `MemoryStore`.

### kaos memory recall

Use `--query` for semantic recall or `--all` for a complete scoped list. Add `--short-term` to include the current session's verbatim window and rolling summary.

```bash
kaos memory recall --store support-memory --scope session --session SESSION_ID --query TEXT [OPTIONS]
kaos memory recall --store support-memory --scope agent --agent AGENT --all [OPTIONS]
```

| Option | Short | Description |
|--------|-------|-------------|
| `--store` | | MemoryStore name; optional when exactly one exists |
| `--scope` | | `session`, `agent`, `user`, or `group` (required) |
| `--session` | | Session ID; required only for session scope |
| `--agent` | | Agent name; required only for agent scope |
| `--user` | | User principal; required only for user scope. A username with a cached `kaos auth login` session resolves to its verified subject; anything else passes through verbatim |
| `--query` | | Semantic query; mutually exclusive with `--all` |
| `--all` | | List every long-term record visible at the scope |
| `--short-term` | | Include conversational tiers when the scope carries a session |
| `--top-k` | | Maximum semantic results (default: 10) |
| `--namespace` | `-n` | Kubernetes namespace |
| `--json` | | Output JSON |

Agent names are expanded to the stable `kaos://agent/<namespace>/<name>` identity before the service call.

### kaos memory forget

Erase every long-term record and attributed conversational session at a scope. The command prints the resolved scope and prompts for confirmation unless `--yes` is passed.

```bash
kaos memory forget --store support-memory --scope user --user alice [-n NAMESPACE]
kaos memory forget --store support-memory --scope group --yes
```

---

## kaos modelapi

ModelAPI lifecycle management.

### kaos modelapi deploy

Deploy a ModelAPI.

```bash
kaos modelapi deploy NAME [OPTIONS]
```

| Option | Short | Description |
|--------|-------|-------------|
| `NAME` | | ModelAPI name (required) |
| `--mode` | `-m` | Mode: Proxy (LiteLLM) or Hosted (Ollama). Default: Proxy |
| `--model` | | Model name (required for Hosted mode) |
| `--namespace` | `-n` | Target namespace |

**Examples:**
```bash
# Deploy Proxy mode (LiteLLM)
kaos modelapi deploy my-api

# Deploy Hosted mode (Ollama)
kaos modelapi deploy my-api --mode Hosted --model smollm2:135m
```

### kaos modelapi list

List ModelAPIs.

```bash
kaos modelapi list [OPTIONS]
```

### kaos modelapi get

Get ModelAPI details.

```bash
kaos modelapi get NAME [OPTIONS]
```

### kaos modelapi logs

View ModelAPI logs.

```bash
kaos modelapi logs NAME [OPTIONS]
```

### kaos modelapi invoke

Send a chat completion request.

```bash
kaos modelapi invoke NAME [OPTIONS]
```

| Option | Short | Description |
|--------|-------|-------------|
| `--message` | `-m` | Message (required) |
| `--model` | | Model name (required) |
| `--port` | `-p` | Local port (default: 9002) |

**Example:**
```bash
kaos modelapi invoke my-api --model gpt-4 --message "Hello"
```

### kaos modelapi delete

Delete a ModelAPI.

```bash
kaos modelapi delete NAME [OPTIONS]
```

---

## kaos ui

Start the KAOS web UI.

```bash
kaos ui [OPTIONS]
```

| Option | Default | Description |
|--------|---------|-------------|
| `--k8s-url` | auto | Kubernetes API URL |
| `--expose-port` | `8010` | Local proxy port |
| `--no-browser` | false | Don't open browser |
| `--monitoring-enabled` | | Enable monitoring UI (`signoz` or `jaeger`) |
| `--system-namespace` | `kaos-system` | Namespace where KAOS system and monitoring are installed |

---

## kaos samples

Deploy and manage example configurations from `operator/config/samples/`.

Samples install into the current kubectl context namespace by default. Use `-n` to specify a target namespace. Namespace resources are never created or deleted — the namespace must already exist.

### kaos samples list

List available sample configurations.

```bash
kaos samples list
```

### kaos samples deploy

Deploy a sample configuration with optional overrides.

```bash
kaos samples deploy NAME [OPTIONS]
```

| Option | Short | Description |
|--------|-------|-------------|
| `--namespace` | `-n` | Target namespace (default: current kubectl context) |
| `--wait` | | Wait for deployments to be available |
| `--wait-timeout` | | Timeout in seconds (default: 120) |
| `--dry-run` | | Print YAML instead of deploying |
| `--modelapi` | | Use existing ModelAPI instead of sample's built-in one |
| `--mode` | | Override ModelAPI mode (Proxy/Hosted) |
| `--model` | `-m` | Override model name |
| `--api-secret` | | Override API secret (secretname:key) |
| `--provider` | | Override LiteLLM provider (e.g., openai, nebius) |

When `--modelapi` is used, the sample's ModelAPI resource is skipped (not deployed). Agents reference the specified existing ModelAPI instead.

**Examples:**
```bash
kaos samples deploy 1-simple-echo-agent -n my-ns
kaos samples deploy 3-hierarchical-agents --namespace my-ns
kaos samples deploy 1-simple-echo-agent --model "llama3:8b" --dry-run
kaos samples deploy 1-simple-echo-agent --api-secret nebius-secrets:api-key
kaos samples deploy 1-simple-echo-agent -n my-ns --modelapi my-existing-api
kaos samples deploy 7-memory-agent -n support-demo --model gpt-4o-mini
```

### kaos samples delete

Delete a sample's resources. Does not delete namespaces.

```bash
kaos samples delete NAME [OPTIONS]
```

| Option | Short | Description |
|--------|---------|-------------|
| `--namespace` | `-n` | Namespace override (must match namespace used during deploy) |
| `--modelapi` | | Skip deleting ModelAPI (use when deployed with --modelapi) |

---

## Environment Variables

| Variable | Description |
|----------|-------------|
| `KUBECONFIG` | Path to kubeconfig |
| `KUBERNETES_SERVICE_HOST` | In-cluster API host |

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | Error |

## Common Workflows

### Create and deploy custom MCP server

```bash
# 1. Scaffold project
kaos mcp init my-tools
cd my-tools

# 2. Edit server.py with your tools

# 3. Build and load to KIND
kaos mcp build --name my-tools --tag v1 --kind-load

# 4. Deploy
kaos mcp deploy my-tools --image my-tools:v1
```

### Deploy Kubernetes MCP with RBAC

```bash
# 1. Generate RBAC
kaos system create-rbac --name k8s-sa --namespace default > rbac.yaml
kubectl apply -f rbac.yaml

# 2. Deploy
kaos mcp deploy k8s-tools --runtime kubernetes --sa k8s-sa
```
