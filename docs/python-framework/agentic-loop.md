# Agentic Loop

The agentic loop is the two-phase reasoning mechanism that enables agents to collect tool results and delegation responses, then produce a final streamed response.

## How It Works

```mermaid
flowchart TB
    subgraph phase1["Phase 1: Action Collection"]
        start["1. Build System Prompt<br/>• Base instructions<br/>• Available tools<br/>• Available agents"]
        
        llm["2. Send to LLM (non-streaming)"]
        
        parse["3. Parse JSON Action"]
        
        tool{"Tool Action?<br/>{\"tool\": ...}"}
        delegate{"Delegate Action?<br/>{\"agent\": ...}"}
        
        exec_tool["Execute tool"]
        exec_delegate["Invoke agent"]
        
        add["4. Add Result to Conversation"]
        
        noaction{"Empty JSON {}?"}
    end
    
    subgraph phase2["Phase 2: Final Response"]
        final["5. Send to LLM (streaming)<br/>Produce final user response"]
    end
    
    start --> llm
    llm --> parse
    parse --> tool
    tool -->|Yes| exec_tool
    tool -->|No| delegate
    delegate -->|Yes| exec_delegate
    delegate -->|No| noaction
    exec_tool --> add
    exec_delegate --> add
    add --> llm
    noaction -->|Yes| final
    noaction -->|No| llm
```

## Configuration

The agentic loop is controlled by the `max_steps` parameter passed to the Agent:

```python
agent = Agent(
    name="my-agent",
    model_api=model_api,
    max_steps=5  # Maximum action collection iterations
)
```

### max_steps

Prevents infinite loops in Phase 1. When reached, returns message:
```
"Reached maximum reasoning steps (5)"
```

**Guidelines:**
- Simple queries: 2-3 steps
- Tool-using tasks: 5 steps (default)
- Complex multi-step tasks: 10+ steps

## Action Format (JSON)

Actions are simple JSON objects. The agent recognizes three action types. The model can include reasoning context before or after the JSON action.

### Tool Call

```json
{"tool": "calculator", "arguments": {"expression": "2 + 2"}}
```

### Delegation

```json
{"agent": "researcher", "task": "Find information about quantum computing"}
```

### No Action (Proceed to Final Response)

```json
{}
```

### Context with Actions

The model can include reasoning alongside actions:

```
I need to calculate this sum first.
{"tool": "calculator", "arguments": {"a": 5, "b": 3}}
I'll wait for the result.
```

The agent extracts the JSON action from the response regardless of surrounding text.

## System Prompt Construction

The agent builds an enhanced system prompt with action instructions:

```python
async def _build_system_prompt(self) -> str:
    parts = [self.instructions]
    
    if self.mcp_clients:
        tools_info = await self._get_tools_description()
        parts.append("\n## Available Tools\n" + tools_info)
        parts.append(TOOLS_INSTRUCTIONS)
    
    if self.sub_agents:
        agents_info = await self._get_agents_description()
        parts.append("\n## Available Agents for Delegation\n" + agents_info)
        parts.append(AGENT_INSTRUCTIONS)
    
    if self.mcp_clients or self.sub_agents:
        parts.append(NO_ACTION_INSTRUCTIONS)
    
    return "\n".join(parts)
```

### Tool Instructions Template

```
To use a tool, include this JSON in your response:
{"tool": "tool_name", "arguments": {"arg1": "value1"}}

You may include reasoning or context before/after the JSON.
Wait for the tool result before providing your final answer.
```

### Delegation Instructions Template

```
To delegate a task to another agent, include this JSON in your response:
{"agent": "agent_name", "task": "task description"}

You may include reasoning or context before/after the JSON.
Wait for the agent's response before providing your final answer.
```

### No Action Instructions Template

```
When you have all the information needed to provide a final answer, respond with ONLY:
{}

Then the system will ask you to provide your final response.
```

## Response Parsing

```python
def _parse_action(self, content: str) -> Dict[str, Any]:
    """Parse JSON action from model response."""
    content = content.strip()
    
    # Try parsing entire content as JSON
    try:
        parsed = json.loads(content)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass
    
    # Look for JSON on a line by itself
    for line in content.split("\n"):
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue
    
    return {}  # No action found
```

## Progress Blocks

During Phase 1, the agent emits progress blocks when starting tool/delegation execution:

```json
{"type": "progress", "step": 1, "action": "tool_call", "target": "calculator"}
{"type": "progress", "step": 2, "action": "delegate", "target": "researcher"}
```

## Execution Flow

### Tool Execution

1. Parse `tool` and `arguments` from JSON action
2. Emit progress block
3. Log `tool_call` event to memory
4. Execute tool via MCP client
5. Log `tool_result` event to memory
6. Add result to conversation
7. Continue to next action loop iteration

### Delegation Execution

1. Parse `agent` and `task` from JSON action
2. Emit progress block
3. Log `delegation_request` event to memory
4. Invoke remote agent via A2A protocol
5. Log `delegation_response` event to memory
6. Add response to conversation
7. Continue to next action loop iteration

### Final Response (Phase 2)

1. When `{}` or no action detected, exit action loop
2. Add "provide your final response" prompt
3. Call model with streaming enabled
4. Stream tokens directly to client
5. Log `agent_response` event to memory

## Memory Events

The loop logs events for debugging and verification:

```python
# After tool execution
events = await agent.memory.get_session_events(session_id)
# Events: [user_message, tool_call, tool_result, agent_response]

# After delegation
events = await agent.memory.get_session_events(session_id)
# Events: [user_message, delegation_request, delegation_response, agent_response]
```

## Testing with Mock Responses

Set `DEBUG_MOCK_RESPONSES` environment variable to test loop behavior deterministically.

The two-phase pattern requires:
1. Action responses (tool/delegate JSON or `{}` for no action)
2. Final response text

```bash
# Test tool calling (action -> no-action -> final)
export DEBUG_MOCK_RESPONSES='["{\"tool\": \"echo\", \"arguments\": {\"text\": \"hello\"}}", "{}", "The echo returned: hello"]'

# Test delegation (action -> no-action -> final)
export DEBUG_MOCK_RESPONSES='["{\"agent\": \"researcher\", \"task\": \"Find quantum info\"}", "{}", "Based on the research, quantum computing uses qubits."]'

# Simple response (no-action -> final)
export DEBUG_MOCK_RESPONSES='["{}", "Hello! How can I help you?"]'
```

For Kubernetes E2E tests, configure via the Agent CRD:
```yaml
spec:
  container:
    env:
    - name: DEBUG_MOCK_RESPONSES
      value: '["{\"agent\": \"worker\", \"task\": \"process data\"}", "{}", "Done."]'
```

## Best Practices

1. **Set appropriate max_steps** - Too low may truncate reasoning, too high wastes resources
2. **Clear instructions** - Tell the LLM when to use tools vs. respond directly
3. **Test with mocks** - Include `{}` to signal end of action phase
4. **Monitor events** - Use memory endpoints to debug complex flows
5. **Handle errors gracefully** - Tool failures are fed back to the loop for recovery
