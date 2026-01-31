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

### kaos system uninstall

Uninstall the KAOS operator.

```bash
kaos system uninstall [OPTIONS]
```

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
kaos mcp deploy [FILE] [OPTIONS]
```

| Option | Short | Description |
|--------|-------|-------------|
| `FILE` | | YAML file path |
| `--name` | | MCPServer name (for image/runtime) |
| `--image` | `-i` | Custom image |
| `--runtime` | `-r` | Registered runtime |
| `--namespace` | `-n` | Target namespace |
| `--params` | `-p` | Runtime parameters |
| `--sa` | | ServiceAccount name |

**Examples:**
```bash
# From YAML file
kaos mcp deploy mcpserver.yaml

# From custom image
kaos mcp deploy --name my-mcp --image my-image:v1

# From registered runtime
kaos mcp deploy --name slack-mcp --runtime slack
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

Deploy an Agent from YAML.

```bash
kaos agent deploy FILE [OPTIONS]
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
| `--port` | `-p` | Local port (default: 9001) |
| `--stream` | `-s` | Stream response |

**Example:**
```bash
kaos agent invoke my-agent --message "Hello, how are you?"
```

### kaos agent delete

Delete an Agent.

```bash
kaos agent delete NAME [OPTIONS]
```

---

## kaos modelapi

ModelAPI lifecycle management.

### kaos modelapi deploy

Deploy a ModelAPI from YAML.

```bash
kaos modelapi deploy FILE [OPTIONS]
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
| `--expose-port` | `8080` | Local proxy port |
| `--no-browser` | false | Don't open browser |

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
kaos mcp deploy --name my-tools --image my-tools:v1
```

### Deploy Kubernetes MCP with RBAC

```bash
# 1. Generate RBAC
kaos system create-rbac --name k8s-sa --namespace default > rbac.yaml
kubectl apply -f rbac.yaml

# 2. Deploy
kaos mcp deploy --name k8s-tools --runtime kubernetes --sa k8s-sa
```
