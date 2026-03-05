FROM python:3.12-slim

WORKDIR /app

# Install dependencies from pyproject.toml
COPY pyproject.toml README.md ./
RUN pip install --no-cache-dir .

# Copy server code
COPY server.py ./

EXPOSE 8000

CMD ["fastmcp", "run", "server.py:mcp", "--transport", "streamable-http", "--host", "0.0.0.0", "--port", "8000"]
