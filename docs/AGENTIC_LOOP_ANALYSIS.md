# KAOS Agentic Loop Assessment Report

This report analyzes the KAOS agentic loop implementation against state-of-the-art frameworks including Google ADK, LangChain/LangGraph, CrewAI, and others. It identifies gaps and opportunities for extension.

## Current KAOS Implementation

### Architecture Overview

KAOS implements a **two-phase agentic loop**:

1. **Phase 1 (Action Collection)**: Non-streaming model calls to iteratively collect tool/delegation actions
2. **Phase 2 (Final Response)**: Streaming model call for user-visible response

### Key Features

| Feature | Status | Description |
|---------|--------|-------------|
| Tool Calling | ✅ | MCP-based tool execution |
| Agent Delegation | ✅ | A2A protocol-based sub-agent invocation |
| Context Accumulation | ✅ | Results appended to conversation history |
| Step Metadata | ✅ | Step X/Y context in result messages |
| Progress Blocks | ✅ | JSON progress events during execution |
| True Streaming | ✅ | Model streaming for final response |
| Flexible JSON Parsing | ✅ | Context-aware action extraction |
| OpenTelemetry | ✅ | Tracing and metrics instrumentation |
| Memory | ✅ | Session-based event storage |
| Max Steps | ✅ | Configurable iteration limit |

### Action Format

```json
{"tool": "name", "arguments": {...}}   // Tool call
{"agent": "name", "task": "..."}       // Delegation
{}                                      // No action (proceed to final)
```

---

## Framework Comparison

### Google ADK (Agent Development Kit)

**Architecture:**
- Three agent types: LLM Agents, Workflow Agents (Sequential/Parallel/Loop), Custom Agents
- Hierarchical multi-agent systems with explicit routing
- State management with template variables (`{var}`, `{artifact.var}`)

**Strengths:**
- Strong typing with multiple language support (Python, TypeScript, Go, Java)
- Built-in workflow agents for deterministic patterns
- Artifact system for persisting outputs between steps
- Native tool-calling via function schemas

**Gaps in KAOS:**
- ❌ No workflow agents (sequential/parallel/loop patterns)
- ❌ No artifact/state persistence between agents
- ❌ No template variable substitution in instructions

### LangChain / LangGraph

**Architecture:**
- Graph-based agent execution with nodes and edges
- Persistent checkpointing for durable execution
- Human-in-the-loop interruption points
- Tool calling via model-native function calling API

**Strengths:**
- Fine-grained control over execution flow
- Built-in persistence and resume capability
- Streaming at multiple granularities (tokens, steps, events)
- Rich ecosystem of tools and integrations

**Gaps in KAOS:**
- ❌ No graph-based workflow definition
- ❌ No checkpointing/resume capability
- ❌ No human-in-the-loop breakpoints
- ❌ No model-native function calling (uses prompt-based)

### CrewAI

**Architecture:**
- Role-based agents with goal/backstory prompting
- Task-based execution with expected outputs
- Crew orchestration patterns
- Built-in reasoning mode for strategic planning

**Strengths:**
- Rich agent personality system (role, goal, backstory)
- Step callbacks for monitoring each action
- Code execution mode (safe via Docker)
- Context window management with summarization
- Reasoning mode for reflective planning before execution

**Gaps in KAOS:**
- ❌ No role/goal/backstory agent personality
- ❌ No step callbacks for external monitoring
- ❌ No code execution sandbox
- ❌ No context window management/summarization
- ❌ No reasoning/planning phase before execution

### Anthropic Claude (Native)

**Architecture:**
- Model-native tool calling with structured outputs
- Extended thinking for complex reasoning
- Streaming with tool use events

**Strengths:**
- Native JSON schema-based tool calling
- Extended thinking tokens for reasoning
- Robust parallel tool calling

**Gaps in KAOS:**
- ❌ No native tool calling API usage (prompt-based instead)
- ❌ No extended thinking/reasoning tokens
- ❌ No parallel tool execution

---

## Gap Analysis Summary

### High Priority Gaps

| Gap | Impact | Effort | Description |
|-----|--------|--------|-------------|
| Native Tool Calling | High | Medium | Use model-native function calling instead of prompt-based JSON |
| Checkpointing | High | High | Persist loop state for resume after failures |
| Parallel Tool Execution | Medium | Medium | Execute independent tools concurrently |
| Human-in-the-Loop | Medium | Medium | Breakpoints for user approval of actions |

### Medium Priority Gaps

| Gap | Impact | Effort | Description |
|-----|--------|--------|-------------|
| Workflow Patterns | Medium | Medium | Sequential/Parallel/Loop agent orchestration |
| Reasoning Phase | Medium | Low | Pre-execution planning step |
| Step Callbacks | Low | Low | External monitoring hooks for each step |
| Context Management | Medium | Medium | Summarization when context exceeds limits |

### Lower Priority Gaps

| Gap | Impact | Effort | Description |
|-----|--------|--------|-------------|
| Agent Personality | Low | Low | Role/goal/backstory templating |
| Artifact System | Low | Medium | Persistent outputs between agent calls |
| Code Execution | Low | High | Sandboxed code execution capability |

---

## Opportunities for Extension

### 1. Native Tool Calling API

**Current:** Prompt-based JSON extraction
**Opportunity:** Use model-native function calling (OpenAI/Anthropic tools API)

Benefits:
- More reliable tool invocation
- Structured outputs with guaranteed schema compliance
- Better token efficiency
- Support for parallel tool calls

Implementation:
```python
# Instead of parsing JSON from content
tools = [{"type": "function", "function": {...}}]
response = await model.chat(messages, tools=tools)
if response.tool_calls:
    # Execute each tool call
```

### 2. Planning/Reasoning Phase

**Current:** Direct action execution
**Opportunity:** Add optional pre-execution planning step

Benefits:
- Better handling of complex multi-step tasks
- Explicit reasoning visible in traces
- More predictable behavior

Implementation:
```python
# Phase 0: Planning (optional)
if self.enable_reasoning:
    plan = await self._generate_plan(messages)
    messages.append({"role": "assistant", "content": f"Plan: {plan}"})

# Phase 1: Action Collection
# Phase 2: Final Response
```

### 3. Parallel Tool Execution

**Current:** Sequential tool execution
**Opportunity:** Execute independent tools concurrently

Benefits:
- Faster execution for multi-tool scenarios
- Better resource utilization
- Matches native model behavior (parallel tool calls)

Implementation:
```python
# Collect multiple tool calls from single response
tool_calls = self._parse_multiple_actions(content)
results = await asyncio.gather(*[
    self._execute_tool(tc["tool"], tc["arguments"])
    for tc in tool_calls
])
```

### 4. Checkpointing and Resume

**Current:** Stateless loop execution
**Opportunity:** Persist loop state for durability

Benefits:
- Resume after failures
- Long-running task support
- Audit trail of execution

Implementation:
```python
class LoopCheckpoint:
    step: int
    messages: List[Dict]
    session_id: str
    timestamp: datetime

async def _agentic_loop(self, ...):
    checkpoint = await self._load_checkpoint(session_id)
    start_step = checkpoint.step if checkpoint else 0
    
    for step in range(start_step, self.max_steps):
        # ... execute step ...
        await self._save_checkpoint(session_id, step, messages)
```

### 5. Human-in-the-Loop

**Current:** Fully autonomous execution
**Opportunity:** Add approval breakpoints

Benefits:
- Safety for high-stakes actions
- User control over agent behavior
- Compliance with governance requirements

Implementation:
```python
class AgenticLoopConfig:
    require_approval_for: List[str] = []  # Tool names requiring approval

# In loop:
if tool_name in self.config.require_approval_for:
    yield {"type": "approval_required", "action": action}
    approval = await self._wait_for_approval(session_id)
    if not approval.approved:
        continue
```

### 6. Context Window Management

**Current:** No context limit handling
**Opportunity:** Automatic summarization when context grows large

Benefits:
- Prevents context overflow errors
- Maintains relevant context
- Enables longer conversations

Implementation:
```python
if self._count_tokens(messages) > self.context_limit * 0.8:
    summary = await self._summarize_messages(messages[:-5])
    messages = [{"role": "system", "content": summary}] + messages[-5:]
```

### 7. Workflow Agent Types

**Current:** Single LLM agent type
**Opportunity:** Add deterministic workflow patterns

Benefits:
- Predictable execution for structured tasks
- Lower cost (no LLM for routing)
- Composable agent architectures

Types to add:
- `SequentialAgent`: Execute sub-agents in order
- `ParallelAgent`: Execute sub-agents concurrently
- `LoopAgent`: Repeat sub-agent until condition met

---

## Recommended Roadmap

### Phase 1: Core Improvements (Near-term)
1. **Native Tool Calling** - Higher reliability and efficiency
2. **Step Callbacks** - External monitoring integration
3. **Reasoning Phase** - Optional planning before execution

### Phase 2: Reliability (Mid-term)
4. **Checkpointing** - Durable execution with resume
5. **Context Management** - Automatic summarization
6. **Parallel Tools** - Concurrent tool execution

### Phase 3: Advanced Patterns (Long-term)
7. **Workflow Agents** - Deterministic orchestration
8. **Human-in-the-Loop** - Approval breakpoints
9. **Code Execution** - Sandboxed execution capability

---

## Conclusion

KAOS has a solid foundation with its two-phase agentic loop, MCP tool integration, and OpenTelemetry observability. The main opportunities for improvement are:

1. **Native tool calling** for reliability and efficiency
2. **Checkpointing** for durability in production workloads
3. **Parallel execution** for performance optimization
4. **Human-in-the-loop** for safety-critical applications

The current prompt-based JSON approach works well for simpler models and provides flexibility, but production deployments would benefit from model-native tool calling where available.

The Kubernetes-native deployment model differentiates KAOS from library-based frameworks like LangChain/CrewAI, making it well-suited for cloud-native AI orchestration at scale.

---

# Appendix: CLI Enhancement Report

The following documents CLI enhancements made in a previous iteration.
