FROM python:3.12-slim

WORKDIR /app

# Install UV for dependency management
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install uv

# Copy only dependency files first for better layer caching
COPY pyproject.toml ./

# Install dependencies using UV with cache mount (cached unless pyproject.toml changes)
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip compile pyproject.toml -o requirements.txt && \
    uv pip install --system -r requirements.txt

# Copy source code (changes frequently, so copied last)
COPY kaos_memory/ kaos_memory/

# Install package (no deps - already installed above) for importlib.metadata
RUN uv pip install --system --no-deps .

# Default local-mode data directory (Chroma + SQLite + history live here on a PVC)
RUN mkdir -p /data/memory && \
    useradd -m -u 65532 memory && chown -R memory:memory /app /data
USER memory

ENV KAOS_MEMORY_STORAGE_TYPE=local \
    KAOS_MEMORY_LOCAL_PATH=/data/memory \
    KAOS_MEMORY_PORT=8080

# Health check hits liveness (independent of store/model readiness)
HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:8080/healthz').raise_for_status()" || exit 1

EXPOSE 8080

CMD ["python", "-m", "kaos_memory"]
