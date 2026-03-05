# pctx-codemode MCP Server - Unified MCP aggregator with Code Mode
# Based on https://github.com/portofcontext/pctx
FROM node:22-slim

WORKDIR /app

# Install system dependencies (libssl required by pctx Rust binary)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libssl3 \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install pctx globally
RUN npm install -g @portofcontext/pctx

# Copy entrypoint script
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

# Default port for MCP HTTP transport
EXPOSE 8000

# Run the entrypoint which writes config and starts pctx
ENTRYPOINT ["/app/entrypoint.sh"]
