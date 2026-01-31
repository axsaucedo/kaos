FROM python:3.12-slim

WORKDIR /app

# Install dependencies
COPY pyproject.toml ./
RUN pip install --no-cache-dir .

# Copy server code
COPY server.py ./

# Run with streamable HTTP transport on port 8000
CMD ["fastmcp", "run", "server:mcp", "--transport", "streamable-http", "--port", "8000", "--host", "0.0.0.0"]
