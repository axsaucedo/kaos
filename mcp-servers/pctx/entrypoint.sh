#!/bin/bash
set -e

# Write pctx config from environment variable
if [ -n "$PCTX_CONFIG" ]; then
    echo "$PCTX_CONFIG" > /app/pctx.json
    echo "pctx config written to /app/pctx.json"
else
    echo "ERROR: PCTX_CONFIG environment variable is required"
    echo "Expected JSON config like:"
    echo '{"name":"unified","version":"1.0.0","servers":[{"name":"echo","url":"http://..."}]}'
    exit 1
fi

# Display config for debugging (redacted secrets)
echo "Starting pctx with config:"
cat /app/pctx.json | sed 's/"token":[^,}]*/"token":"***"/g'

# Start pctx MCP server
# --host 0.0.0.0 binds to all interfaces for container access
# --port 8000 matches KAOS MCP server conventions
exec pctx mcp start --host 0.0.0.0 --port 8000 --config /app/pctx.json
