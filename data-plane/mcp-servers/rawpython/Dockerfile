FROM python:3.12-slim

WORKDIR /app

# Install dependencies
COPY pyproject.toml README.md ./
RUN pip install --no-cache-dir .

# Copy server code
COPY server.py ./

# Run with streamable HTTP transport on port 8000
CMD ["fastmcp", "run", "server.py:mcp", "--transport", "streamable-http", "--port", "8000", "--host", "0.0.0.0"]
