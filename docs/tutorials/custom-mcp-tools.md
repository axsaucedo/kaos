# Tutorial: Custom MCP Tools

This tutorial covers advanced patterns for creating custom MCP tools.

## Basic Tool Anatomy

Every MCP tool is a Python function with:
- Type annotations for parameters
- A docstring describing what it does
- A return value

```python
def my_tool(param1: str, param2: int) -> str:
    """Description of what this tool does.
    
    Args:
        param1: Description of param1
        param2: Description of param2
    
    Returns:
        Description of return value
    """
    return f"Result: {param1} - {param2}"
```

## Tool Types

### Simple Tools

Basic transformations:

```yaml
toolsString: |
  def echo(text: str) -> str:
      """Echo back the input text."""
      return text
  
  def greet(name: str) -> str:
      """Greet someone by name."""
      return f"Hello, {name}!"
```

### Calculation Tools

Mathematical operations:

```yaml
toolsString: |
  import math
  
  def calculate(expression: str) -> str:
      """Safely evaluate a math expression."""
      try:
          # Only allow safe math operations
          allowed = {"__builtins__": {}, "math": math}
          result = eval(expression, allowed)
          return str(result)
      except Exception as e:
          return f"Error: {e}"
  
  def factorial(n: int) -> int:
      """Calculate factorial of n."""
      if n < 0:
          return -1  # Error indicator
      return math.factorial(n)
```

### Data Processing Tools

Working with structured data:

```yaml
toolsString: |
  import json
  
  def parse_json(data: str) -> dict:
      """Parse a JSON string into a dictionary."""
      try:
          return json.loads(data)
      except json.JSONDecodeError as e:
          return {"error": str(e)}
  
  def format_json(data: dict) -> str:
      """Format a dictionary as pretty JSON."""
      return json.dumps(data, indent=2)
  
  def extract_field(json_str: str, field: str) -> str:
      """Extract a field from JSON data."""
      try:
          data = json.loads(json_str)
          return str(data.get(field, "Field not found"))
      except:
          return "Invalid JSON"
```

### API Integration Tools

Calling external services:

```yaml
toolsString: |
  import urllib.request
  import json
  import os
  
  def fetch_url(url: str) -> str:
      """Fetch content from a URL."""
      try:
          with urllib.request.urlopen(url, timeout=10) as response:
              return response.read().decode('utf-8')[:1000]  # Limit size
      except Exception as e:
          return f"Error: {e}"
  
  def call_api(endpoint: str, method: str) -> str:
      """Call an API endpoint."""
      api_key = os.environ.get("API_KEY", "")
      try:
          req = urllib.request.Request(
              endpoint,
              headers={"Authorization": f"Bearer {api_key}"}
          )
          with urllib.request.urlopen(req) as response:
              return response.read().decode('utf-8')
      except Exception as e:
          return f"Error: {e}"
```

## Environment Variables

Pass secrets via environment variables:

```yaml
apiVersion: ethical.institute/v1alpha1
kind: MCPServer
metadata:
  name: api-tools
spec:
  type: python-runtime
  config:
    toolsString: |
      import os
      
      def get_secret_data() -> str:
          """Retrieve data using API key."""
          api_key = os.environ.get("MY_API_KEY", "")
          # Use api_key...
          return "Data retrieved"
    
    env:
    - name: MY_API_KEY
      valueFrom:
        secretKeyRef:
          name: my-secrets
          key: api-key
```

## Multiple Related Tools

Group related functionality:

```yaml
toolsString: |
  # Date/Time utilities
  from datetime import datetime, timedelta
  
  def current_time() -> str:
      """Get the current date and time."""
      return datetime.now().isoformat()
  
  def add_days(date_str: str, days: int) -> str:
      """Add days to a date. Format: YYYY-MM-DD."""
      try:
          date = datetime.strptime(date_str, "%Y-%m-%d")
          new_date = date + timedelta(days=days)
          return new_date.strftime("%Y-%m-%d")
      except ValueError as e:
          return f"Error: {e}"
  
  def days_between(date1: str, date2: str) -> int:
      """Calculate days between two dates."""
      try:
          d1 = datetime.strptime(date1, "%Y-%m-%d")
          d2 = datetime.strptime(date2, "%Y-%m-%d")
          return abs((d2 - d1).days)
      except ValueError:
          return -1
```

## Error Handling Patterns

Robust error handling:

```yaml
toolsString: |
  def safe_operation(data: str) -> str:
      """Perform operation with error handling."""
      try:
          # Validate input
          if not data:
              return "Error: Empty input"
          
          if len(data) > 10000:
              return "Error: Input too large"
          
          # Perform operation
          result = process(data)
          
          return f"Success: {result}"
          
      except ValueError as e:
          return f"Validation error: {e}"
      except RuntimeError as e:
          return f"Runtime error: {e}"
      except Exception as e:
          return f"Unexpected error: {e}"
```

## Type Annotations

Supported types:

```yaml
toolsString: |
  def string_tool(text: str) -> str:
      """Accepts and returns string."""
      return text
  
  def int_tool(number: int) -> int:
      """Accepts and returns integer."""
      return number * 2
  
  def dict_tool(data: dict) -> dict:
      """Accepts and returns dictionary."""
      return {**data, "processed": True}
  
  def list_tool(items: list) -> list:
      """Accepts and returns list."""
      return sorted(items)
```

## Testing Tools Locally

Test your tool code before deploying:

```python
# test_tools.py
tools_string = '''
def my_tool(x: str) -> str:
    """My tool."""
    return x.upper()
'''

# Execute the string
namespace = {}
exec(tools_string, {}, namespace)

# Test the function
my_tool = namespace['my_tool']
assert my_tool("hello") == "HELLO"
print("Tool works correctly!")
```

Run with:
```bash
python test_tools.py
```

## Debugging Tools

### Check Tool Registration

```bash
kubectl exec -it deploy/my-mcp -n my-namespace -- \
  curl http://localhost:8000/ready | jq
```

### View Tool Descriptions

```bash
kubectl exec -it deploy/my-agent -n my-namespace -- \
  curl http://my-mcp/mcp/tools | jq
```

### Check Logs

```bash
kubectl logs -l app=my-mcp -n my-namespace
```

## Best Practices

1. **Keep Tools Simple**: One function, one purpose
2. **Validate Input**: Check for invalid/malicious input
3. **Handle Errors**: Return error messages, don't throw
4. **Limit Output**: Truncate large responses
5. **Use Timeouts**: For external calls
6. **Log Important Events**: For debugging
7. **Document Well**: LLM uses docstrings to understand tools

## Security Considerations

1. **No exec/eval on user input**: Avoid arbitrary code execution
2. **Validate URLs**: Check before fetching
3. **Use environment variables for secrets**: Never hardcode
4. **Limit resource usage**: Memory, network, time
5. **Sandbox when possible**: Restrict file system access
