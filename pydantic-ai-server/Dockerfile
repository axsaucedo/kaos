FROM python:3.12-slim

WORKDIR /app

# Install UV for dependency management
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install uv

# Copy only dependency files first for better layer caching
COPY pyproject.toml ./

# Install dependencies using UV with cache mount
# This layer is cached unless pyproject.toml changes
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip compile pyproject.toml -o requirements.txt && \
    uv pip install --system -r requirements.txt

# Copy source code (changes frequently, so copied last)
COPY pais/ pais/

# Install package (no deps - already installed above) for importlib.metadata
RUN uv pip install --system --no-deps .

# Create non-root user
RUN useradd -m -u 65532 agentic && chown -R agentic:agentic /app
USER agentic

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:8000/health').raise_for_status()" || exit 1

# Expose port
EXPOSE 8000

# Run the agent server using factory pattern
# Access logs are controlled by OTEL_INCLUDE_HTTP_SERVER env var in Python code
CMD ["python", "-m", "uvicorn", "pais.server:get_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
