FROM python:3.12-slim

WORKDIR /app

# Install dependencies
COPY pyproject.toml README.md ./
RUN pip install --no-cache-dir .

# Copy server code
COPY server.py ./

# Run with uvicorn (includes health endpoint wrapper)
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]
