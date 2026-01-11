# ModelAPI Client

The ModelAPI class provides an async client for OpenAI-compatible LLM APIs with support for streaming and mock responses.

## Class Definition

```python
class ModelAPI:
    def __init__(
        self,
        model: str,
        api_base: str,
        api_key: Optional[str] = None
    )
```

### Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `model` | str | Yes | Model identifier (e.g., `smollm2:135m`, `gpt-4`) |
| `api_base` | str | Yes | API base URL (e.g., `http://localhost:8000`) |
| `api_key` | str | No | API key for authentication |

## Methods

### complete

Non-streaming chat completion.

```python
async def complete(
    self,
    messages: List[Dict],
    mock_response: str = None
) -> Dict
```

**Parameters:**
- `messages`: OpenAI-format messages list
- `mock_response`: Optional mock response for testing

**Returns:** OpenAI-format response dictionary

**Example:**

```python
response = await model_api.complete([
    {"role": "system", "content": "You are a helpful assistant."},
    {"role": "user", "content": "Hello!"}
])

content = response["choices"][0]["message"]["content"]
print(content)  # "Hello! How can I help you today?"
```

### stream

Streaming chat completion with SSE parsing.

```python
async def stream(
    self,
    messages: List[Dict],
    mock_response: str = None
) -> AsyncIterator[str]
```

**Parameters:**
- `messages`: OpenAI-format messages list
- `mock_response`: Optional mock response for testing

**Yields:** Content chunks as strings

**Example:**

```python
async for chunk in model_api.stream([
    {"role": "user", "content": "Tell me a story"}
]):
    print(chunk, end="", flush=True)
```

### close

Close HTTP client and cleanup resources.

```python
await model_api.close()
```

## Usage Examples

### Basic Completion

```python
from modelapi.client import ModelAPI

model_api = ModelAPI(
    model="smollm2:135m",
    api_base="http://localhost:8000"
)

response = await model_api.complete([
    {"role": "user", "content": "What is 2+2?"}
])

print(response["choices"][0]["message"]["content"])
# "4"

await model_api.close()
```

### With API Key

```python
model_api = ModelAPI(
    model="gpt-4",
    api_base="https://api.openai.com",
    api_key="sk-..."
)
```

### Streaming Response

```python
async for chunk in model_api.stream([
    {"role": "user", "content": "Write a haiku about coding"}
]):
    print(chunk, end="")
# Output streams character by character
```

### Multi-Turn Conversation

```python
messages = [
    {"role": "system", "content": "You are a math tutor."},
    {"role": "user", "content": "What is calculus?"},
    {"role": "assistant", "content": "Calculus is the study of change..."},
    {"role": "user", "content": "Can you give an example?"}
]

response = await model_api.complete(messages)
```

## Mock Responses

Mock responses enable deterministic testing without calling the actual LLM.

### Environment Variable Method (Recommended)

For Agent-level testing, use `DEBUG_MOCK_RESPONSES` environment variable:

```bash
# Single response
export DEBUG_MOCK_RESPONSES='["Hello from mock"]'

# Multi-step agentic loop
export DEBUG_MOCK_RESPONSES='["```tool_call\n{\"tool\": \"echo\", \"arguments\": {}}\n```", "Done."]'
```

This bypasses the ModelAPI entirely and is the recommended approach for E2E testing.

### LiteLLM Mock Feature

LiteLLM servers also support `mock_response` in the request body (useful for direct API testing):

```python
# This works with LiteLLM-based servers
response = await model_api.complete(
    messages=[{"role": "user", "content": "Hello"}],
    mock_response="This is a mock response"
)
# response["choices"][0]["message"]["content"] == "This is a mock response"
```

## Error Handling

```python
import httpx

try:
    response = await model_api.complete(messages)
except httpx.HTTPError as e:
    print(f"HTTP error: {e}")
except ValueError as e:
    print(f"Invalid response: {e}")
```

## Response Format

### Completion Response

```json
{
  "id": "chatcmpl-xxx",
  "object": "chat.completion",
  "created": 1704067200,
  "model": "smollm2:135m",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "Hello! How can I help you?"
      },
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": 10,
    "completion_tokens": 8,
    "total_tokens": 18
  }
}
```

### Streaming Chunks

Each SSE chunk contains:

```json
{
  "id": "chatcmpl-xxx",
  "object": "chat.completion.chunk",
  "created": 1704067200,
  "model": "smollm2:135m",
  "choices": [
    {
      "index": 0,
      "delta": {
        "content": "Hello"
      },
      "finish_reason": null
    }
  ]
}
```

Final chunk has empty delta and `"finish_reason": "stop"`.

## Configuration in Kubernetes

The operator configures ModelAPI via environment variables:

```yaml
spec:
  config:
    env:
    - name: MODEL_API_URL
      value: "http://modelapi-service:8000"
    - name: MODEL_NAME
      value: "smollm2:135m"
```

The agent server reads these and creates the ModelAPI:

```python
# In agent/server.py
model_api = ModelAPI(
    model=settings.model_name,
    api_base=settings.model_api_url
)
```

## Connection Management

ModelAPI uses httpx with connection pooling:

```python
self.client = httpx.AsyncClient(
    base_url=self.api_base,
    headers=headers,
    timeout=60.0  # 60 second timeout for LLM responses
)
```

Always call `close()` when done to release connections:

```python
try:
    response = await model_api.complete(messages)
finally:
    await model_api.close()
```

Or use as context manager in your application lifecycle.
