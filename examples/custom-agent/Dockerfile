FROM python:3.12-slim

WORKDIR /app

# Install UV for dependency management
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install uv

# Install kaos-runtime from the base framework
COPY data-plane/pai-server/pyproject.toml /tmp/pai-server/pyproject.toml
RUN --mount=type=cache,target=/root/.cache/uv \
    cd /tmp/pai-server && \
    uv pip compile pyproject.toml -o requirements.txt && \
    uv pip install --system -r requirements.txt

# Copy the kaos framework source
COPY data-plane/pai-server/pai_server/ /app/pai_server/

# Copy custom agent server
COPY examples/custom-agent/server.py /app/custom_server.py

# Create non-root user
RUN useradd -m -u 65532 agentic && chown -R agentic:agentic /app
USER agentic

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "custom_server:get_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
