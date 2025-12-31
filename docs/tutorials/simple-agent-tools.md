# Tutorial: Simple Agent with Tools

This tutorial shows how to create a simple agent with MCP tool access.

## Prerequisites

- Agentic operator installed
- kubectl configured
- Ollama running (locally or in-cluster)

## Step 1: Create the Resources

Create a file `agent-with-tools.yaml`:

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: tool-demo

---
# ModelAPI: LLM backend
apiVersion: ethical.institute/v1alpha1
kind: ModelAPI
metadata:
  name: ollama
  namespace: tool-demo
spec:
  mode: Hosted
  serverConfig:
    model: "smollm2:135m"

---
# MCPServer: Calculator tools
apiVersion: ethical.institute/v1alpha1
kind: MCPServer
metadata:
  name: calculator
  namespace: tool-demo
spec:
  type: python-runtime
  config:
    toolsString: |
      def add(a: int, b: int) -> int:
          """Add two numbers together."""
          return a + b
      
      def subtract(a: int, b: int) -> int:
          """Subtract b from a."""
          return a - b
      
      def multiply(a: int, b: int) -> int:
          """Multiply two numbers."""
          return a * b
      
      def divide(a: int, b: int) -> str:
          """Divide a by b. Returns error if b is zero."""
          if b == 0:
              return "Error: Cannot divide by zero"
          return str(a / b)

---
# MCPServer: String utilities
apiVersion: ethical.institute/v1alpha1
kind: MCPServer
metadata:
  name: string-tools
  namespace: tool-demo
spec:
  type: python-runtime
  config:
    toolsString: |
      def uppercase(text: str) -> str:
          """Convert text to uppercase."""
          return text.upper()
      
      def lowercase(text: str) -> str:
          """Convert text to lowercase."""
          return text.lower()
      
      def reverse(text: str) -> str:
          """Reverse the input text."""
          return text[::-1]
      
      def word_count(text: str) -> int:
          """Count the number of words in text."""
          return len(text.split())

---
# Agent with tool access
apiVersion: ethical.institute/v1alpha1
kind: Agent
metadata:
  name: tool-agent
  namespace: tool-demo
spec:
  modelAPI: ollama
  mcpServers:
  - calculator
  - string-tools
  config:
    description: "An agent with calculator and string tools"
    instructions: |
      You are a helpful assistant with access to tools.
      
      Available tools:
      - Calculator: add, subtract, multiply, divide
      - String utilities: uppercase, lowercase, reverse, word_count
      
      When asked to perform calculations or text operations,
      use the appropriate tool instead of computing yourself.
      
      Always show your reasoning and the tool you're using.
    agenticLoop:
      maxSteps: 5
      enableTools: true
  agentNetwork:
    expose: true
```

## Step 2: Deploy

```bash
kubectl apply -f agent-with-tools.yaml
```

## Step 3: Wait for Resources

```bash
kubectl get agent,modelapi,mcpserver -n tool-demo -w
```

Wait until all resources show `Ready: true`.

## Step 4: Test the Agent

Port-forward to the agent:

```bash
kubectl port-forward -n tool-demo svc/tool-agent 8000:80
```

### Test Calculator

```bash
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "tool-agent",
    "messages": [{"role": "user", "content": "What is 15 multiplied by 7?"}]
  }' | jq -r '.choices[0].message.content'
```

The agent should use the `multiply` tool and respond with "105".

### Test String Tools

```bash
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "tool-agent",
    "messages": [{"role": "user", "content": "Convert \"hello world\" to uppercase"}]
  }' | jq -r '.choices[0].message.content'
```

### Check Memory Events

```bash
curl http://localhost:8000/memory/events | jq
```

You should see `tool_call` and `tool_result` events in the response.

## Understanding the Agentic Loop

When the agent receives a request:

1. **Builds System Prompt**: Includes tool descriptions
2. **Sends to LLM**: Gets response with tool call
3. **Parses Response**: Detects `tool_call` block
4. **Executes Tool**: Calls MCP server
5. **Adds Result**: Feeds result back to conversation
6. **Continues**: LLM generates final response

Example response from LLM (step 3):
```
I'll use the multiply tool to calculate this.

```tool_call
{"tool": "multiply", "arguments": {"a": 15, "b": 7}}
```
```

## Adding More Tools

You can add more MCPServers and reference them:

```yaml
spec:
  mcpServers:
  - calculator
  - string-tools
  - weather-api     # Add new tools
  - database-tools
```

## Tool Best Practices

1. **Clear Names**: Use descriptive function names
2. **Good Docstrings**: LLM uses these to understand the tool
3. **Type Hints**: Required for parameter schema generation
4. **Error Handling**: Return error messages gracefully
5. **Simple Returns**: Return strings or simple types

## Cleanup

```bash
kubectl delete namespace tool-demo
```

## Next Steps

- [Custom MCP Tools](custom-mcp-tools.md) - Advanced tool creation
- [Multi-Agent Coordination](multi-agent.md) - Add delegation
