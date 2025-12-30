FROM python:3.12-slim

WORKDIR /app

# Install UV for dependency management
RUN pip install --no-cache-dir uv

# Copy project files
COPY pyproject.toml pyproject.toml

# Install dependencies using UV
RUN uv pip compile pyproject.toml -o requirements.txt && \
    uv pip install --system -r requirements.txt

# Copy source code
COPY agent/ agent/
COPY mcptools/ mcptools/
COPY modelapi/ modelapi/

# Create non-root user
RUN useradd -m -u 65532 agentic && chown -R agentic:agentic /app
USER agentic

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:8000/health').raise_for_status()" || exit 1

# Expose port
EXPOSE 8000

# Run the agent server using factory pattern
CMD ["python", "-m", "uvicorn", "agent.server:get_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
