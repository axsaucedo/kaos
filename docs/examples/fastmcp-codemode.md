---
jupyter:
  jupytext:
    cell_metadata_filter: -all
    text_representation:
      extension: .md
      format_name: markdown
      format_version: '1.3'
      jupytext_version: 1.19.1
  kernelspec:
    display_name: Python 3 (ipykernel)
    language: python
    name: python3
---

# FastMCP Code Mode

> **Try it yourself!** This example is available as an executable [Jupyter notebook](/examples/fastmcp-codemode.ipynb).

This example demonstrates the **fastmcp-codemode** runtime, which aggregates multiple KAOS MCP servers and wraps them with FastMCP's [CodeMode](https://gofastmcp.com/servers/transforms/code-mode) transform. Instead of exposing individual tools from each server, agents get meta-tools (`search`, `get_schema`, `execute`) that enable discovering and chaining cross-server tool calls via Python code execution in a sandbox.

## Understanding FastMCP Code Mode

With traditional MCP, each tool call is a round-trip through the LLM:

```
LLM: "I'll call add(42, 8)"      -> Tool executes -> Result
LLM: "Now I'll call multiply"    -> Tool executes -> Result
LLM: "Now I'll call uppercase"   -> Tool executes -> Result
LLM: "Here's the final answer"
```

With FastMCP Code Mode, the agent writes Python code that chains operations across multiple servers in one call:

```python .noeval
# The LLM generates Python code that runs in a sandbox:
result_add = await call_tool("calc_add", {"a": 42, "b": 8})
result_mul = await call_tool("calc_multiply", {"x": result_add, "y": 2})
result_upper = await call_tool("text_uppercase", {"text": f"answer is {result_mul}"})
return result_upper
```

This reduces:
- **LLM round-trips**: From N+1 to ~3 (search → execute → final response)
- **Token usage**: Only schemas for needed tools are loaded
- **Latency**: Multi-step operations complete in a single sandbox execution

## Architecture

```mermaid
graph LR
    A[User Request] --> B[Agent]
    B --> C[FastMCP CodeMode Gateway]
    C --> D[Calculator MCP]
    C --> E[Text Utils MCP]
```

### How it works
The `fastmcp-codemode` runtime uses FastMCP's `create_proxy()` and `mount()` to connect to upstream KAOS MCP servers via HTTP. Each server's tools are namespaced (e.g., `calc_add`, `text_uppercase`), and the CodeMode transform wraps everything into three meta-tools.

The config lists upstream server endpoints:
```json .noeval
{
  "servers": [
    {"name": "calc", "url": "http://mcpserver-calculator:8000/mcp"},
    {"name": "text", "url": "http://mcpserver-textutils:8000/mcp"}
  ]
}
```

## Prerequisites

- KAOS operator installed ([Installation Guide](/getting-started/installation))
- `kaos-cli` installed
- Access to a Kubernetes cluster

## Setup

```python
import os
os.environ['NAMESPACE'] = 'fastmcp-codemode-example'
```

```bash
kubectl create namespace $NAMESPACE 2>/dev/null || true
kubectl config set-context --current --namespace=$NAMESPACE
```

## Step 1: Create a ModelAPI

Create a ModelAPI in Proxy mode:

```bash
kaos modelapi deploy codemode-api --mode Proxy --wait
```

## Step 2: Create Upstream MCP Servers

Deploy two MCP servers that the CodeMode gateway will aggregate.

### Calculator MCP Server

```bash
export CALC_FUNCS='
def add(a: int, b: int) -> int:
    """Add two numbers together."""
    return a + b

def multiply(x: int, y: int) -> int:
    """Multiply two numbers."""
    return x * y

def power(base: int, exponent: int) -> int:
    """Raise base to the power of exponent."""
    return base ** exponent
'

kaos mcp deploy calculator \
    --runtime python-string \
    --params "$CALC_FUNCS" \
    --wait
```

### Text Utils MCP Server

```bash
kubectl apply -f - << EOF
apiVersion: kaos.tools/v1alpha1
kind: MCPServer
metadata:
  name: textutils
spec:
  runtime: python-string
  params: |
    def uppercase(text: str) -> str:
        """Convert text to uppercase."""
        return text.upper()

    def word_count(text: str) -> int:
        """Count the number of words in text."""
        return len(text.split())
EOF

kubectl wait mcpserver/textutils --for=jsonpath='{.status.ready}'=true --timeout=180s
```

## Step 3: Create the FastMCP CodeMode Gateway

Create the gateway that aggregates both upstream servers with CodeMode:

```bash
export CODEMODE_CONFIG='
{
  "servers": [
    {
      "name": "calc",
      "url": "http://mcpserver-calculator.'$NAMESPACE'.svc.cluster.local:8000/mcp"
    },
    {
      "name": "text",
      "url": "http://mcpserver-textutils.'$NAMESPACE'.svc.cluster.local:8000/mcp"
    }
  ]
}'

kaos mcp deploy codemode-gateway --runtime fastmcp-codemode --params "$CODEMODE_CONFIG" --wait
```

## Step 4: Create the Agent

Create an agent connected to the CodeMode gateway. The mock responses demonstrate the Code Mode flow — the agent discovers tools via `search`, then writes Python code that chains operations across both upstream servers using the `execute` meta-tool:

```bash
# Mock response: agent calls execute to chain operations across calc and text servers
MOCK_CODE="{\
  \"tool_calls\": [{\
    \"id\": \"call_1\",\
    \"name\": \"execute\",\
    \"arguments\": {\
      \"code\": \"result_add = await call_tool('calc_add', {'a': 42, 'b': 8}); result_mul = await call_tool('calc_multiply', {'x': 50, 'y': 2}); result_upper = await call_tool('text_uppercase', {'text': f'answer is {result_mul}'}); return result_upper\"\
    }\
  }]\
}"

MOCK_FINAL='I executed a cross-server calculation chain using Code Mode: (42+8)=50, 50*2=100, then formatted via text server. The final result is "ANSWER IS 100".'

kaos agent deploy codemode-agent \
    --modelapi codemode-api \
    --model mock-model \
    --mcp codemode-gateway \
    --instructions "You use Code Mode to chain calculations across multiple MCP servers efficiently via Python code execution." \
    --mock-response "$MOCK_CODE" \
    --mock-response "$MOCK_FINAL" \
    --expose \
    --wait
```

## Step 5: Invoke the Agent

Send a request that triggers cross-server tool chaining:

```bash
kaos agent invoke codemode-agent --message "Calculate (42+8)*2, then format the result in uppercase"
```

## Step 6: Verify Agent Status

Check that the agent has discovered the Code Mode meta-tools:

```bash
kaos agent status codemode-agent
```

Verify the output shows A2A capabilities:

```bash
kaos agent status codemode-agent --json | grep -q "streaming" || exit 1
```

## Step 7: Verify Memory Events

Check that tool calls were recorded in memory:

```bash
kaos agent memory codemode-agent
```

Verify a tool_call event exists and no errors occurred:

```bash
# Check tool_call event exists
kaos agent memory codemode-agent --json | grep -q "tool_call" || exit 1
# Check no tool errors occurred
kaos agent memory codemode-agent --json | grep -q "tool_error" && exit 1 || true
```

## Cleanup

```bash
kubectl delete namespace $NAMESPACE --wait=false
```

## Next Steps

- [Unified MCP Gateway](/examples/unified-mcp-gateway) - Aggregate multiple MCP servers with pctx Code Mode (TypeScript sandbox)
- [MCPServer CRD Reference](/operator/mcpserver-crd) - Full runtime documentation
- [FastMCP Code Mode docs](https://gofastmcp.com/servers/transforms/code-mode) - Upstream documentation
