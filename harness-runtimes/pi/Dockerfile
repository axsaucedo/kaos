# `pi` harness runtime — the KAOS Agent HTTP contract in front of `pi`.
#
# `pi` is MIT-licensed and speaks OpenAI chat completions, so KAOS may ship this
# image and it works against a KAOS ModelAPI with no wire-format work.
#
# Build from the harness-runtimes/ directory:
#     docker build -f pi/Dockerfile -t kaos-harness-pi:latest .
FROM node:22-bookworm-slim

# `pi` is a Node CLI, the driver is Python — this image needs both runtimes.
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-pip python3-venv git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Pin the harness: an unpinned coding agent changes its event stream under you,
# and the driver parses that stream.
ARG PI_VERSION=0.84.2
RUN npm install -g @earendil-works/pi-coding-agent@${PI_VERSION} \
    && npm cache clean --force

WORKDIR /app

# Install driver dependencies first so the layer caches across source changes.
ENV VIRTUAL_ENV=/opt/venv PATH=/opt/venv/bin:$PATH
RUN python3 -m venv /opt/venv
COPY pyproject.toml README.md ./
RUN pip install --no-cache-dir uv \
    && uv pip compile pyproject.toml -o requirements.txt \
    && uv pip install -r requirements.txt

COPY kaos_harness/ kaos_harness/
RUN uv pip install --no-deps .

# Workspace (per-session subdirectories) and harness state (provider config,
# session transcripts). Both are mount points in the pod.
ENV HARNESS_DRIVER=pi \
    HARNESS_WORKSPACE=/workspace \
    HARNESS_STATE_DIR=/state \
    AGENT_PORT=8000 \
    PYTHONUNBUFFERED=1

RUN useradd -m -u 65532 agentic \
    && mkdir -p /workspace /state \
    && chown -R agentic:agentic /app /workspace /state
USER agentic

HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD python3 -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

EXPOSE 8000

CMD ["kaos-harness", "serve", "--host", "0.0.0.0", "--port", "8000"]
