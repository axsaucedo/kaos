"""KAOS MCP invoke command."""

import json
import subprocess
import sys
import time
import typer
import signal


def invoke_command(
    name: str,
    namespace: str | None,
    tool: str,
    args: str | None,
    port: int,
) -> None:
    """Invoke an MCP tool via port-forward."""
    import httpx

    # Find the service for this MCPServer
    cmd = [
        "kubectl",
        "get",
        "svc",
        f"mcpserver-{name}",
        "-o",
        "jsonpath={.spec.ports[0].port}",
    ]
    if namespace:
        cmd.extend(["-n", namespace])
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        typer.echo(f"Error: MCPServer '{name}' not found", err=True)
        sys.exit(1)

    svc_port = result.stdout.strip() or "8000"

    typer.echo(f"Port-forwarding to mcpserver-{name}:{svc_port}...")

    # Start port-forward in background
    pf_cmd = ["kubectl", "port-forward", f"svc/mcpserver-{name}", f"{port}:{svc_port}"]
    if namespace:
        pf_cmd.extend(["-n", namespace])
    pf_process = subprocess.Popen(
        pf_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )

    # Handle cleanup
    def cleanup():
        pf_process.terminate()
        pf_process.wait()

    signal.signal(signal.SIGINT, lambda s, f: (cleanup(), sys.exit(0)))

    # Wait for port-forward to be ready
    time.sleep(2)

    if pf_process.poll() is not None:
        stderr = pf_process.stderr.read().decode() if pf_process.stderr else ""
        typer.echo(f"Error: Port-forward failed: {stderr}", err=True)
        sys.exit(1)

    try:
        # Parse tool arguments
        tool_args = {}
        if args:
            try:
                tool_args = json.loads(args)
            except json.JSONDecodeError:
                typer.echo("Error: --args must be valid JSON", err=True)
                cleanup()
                sys.exit(1)

        # Call the MCP tool
        typer.echo(f"Calling tool '{tool}' with args: {tool_args}")

        try:
            response = httpx.post(
                f"http://localhost:{port}/mcp",
                json={
                    "jsonrpc": "2.0",
                    "method": "tools/call",
                    "params": {"name": tool, "arguments": tool_args},
                    "id": 1,
                },
                timeout=30.0,
            )

            if response.status_code == 200:
                result = response.json()
                if "result" in result:
                    typer.echo("\n✅ Result:")
                    typer.echo(json.dumps(result["result"], indent=2))
                elif "error" in result:
                    typer.echo(f"\n❌ Error: {result['error']}", err=True)
                else:
                    typer.echo(json.dumps(result, indent=2))
            else:
                typer.echo(
                    f"Error: HTTP {response.status_code}: {response.text}", err=True
                )
        except httpx.ConnectError:
            typer.echo("Error: Could not connect to MCP server", err=True)
        except Exception as e:
            typer.echo(f"Error: {e}", err=True)
    finally:
        cleanup()
