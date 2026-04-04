"""KAOS Agent A2A commands — interact via A2A JSON-RPC protocol."""

import json
import subprocess
import sys
import time
import signal
import typer

app = typer.Typer(
    help="A2A protocol commands (send, get, cancel).",
    no_args_is_help=True,
)


def _port_forward_and_call(
    name: str,
    namespace: str | None,
    port: int,
    payload: dict,
) -> dict:
    """Port-forward to agent and send JSON-RPC request."""
    import httpx

    cmd = [
        "kubectl", "get", "svc", f"agent-{name}",
        "-o", "jsonpath={.spec.ports[0].port}",
    ]
    if namespace:
        cmd.extend(["-n", namespace])
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        typer.echo(f"Error: Agent '{name}' not found", err=True)
        sys.exit(1)

    svc_port = result.stdout.strip() or "8000"

    pf_cmd = ["kubectl", "port-forward", f"svc/agent-{name}", f"{port}:{svc_port}"]
    if namespace:
        pf_cmd.extend(["-n", namespace])
    pf_process = subprocess.Popen(
        pf_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )

    def cleanup():
        pf_process.terminate()
        pf_process.wait()

    signal.signal(signal.SIGINT, lambda s, f: (cleanup(), sys.exit(0)))
    time.sleep(2)

    if pf_process.poll() is not None:
        stderr = pf_process.stderr.read().decode() if pf_process.stderr else ""
        typer.echo(f"Error: Port-forward failed: {stderr}", err=True)
        sys.exit(1)

    try:
        response = httpx.post(
            f"http://localhost:{port}/",
            json=payload,
            timeout=120.0,
        )
        if response.status_code != 200:
            typer.echo(f"Error: HTTP {response.status_code}: {response.text}", err=True)
            sys.exit(1)
        return response.json()
    except httpx.ConnectError:
        typer.echo("Error: Could not connect to Agent", err=True)
        sys.exit(1)
    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        sys.exit(1)
    finally:
        cleanup()


def _format_task(task: dict) -> None:
    """Pretty-print a task response."""
    task_id = task.get("id", "unknown")
    state = task.get("status", {}).get("state", "unknown")
    message = task.get("status", {}).get("message", "")

    typer.echo(f"Task ID: {task_id}")
    typer.echo(f"State:   {state}")
    if message:
        typer.echo(f"Message: {message}")

    output = task.get("output")
    if output:
        typer.echo(f"\n📤 Output:\n{output}")

    artifacts = task.get("artifacts", [])
    if artifacts:
        typer.echo("\n📎 Artifacts:")
        for artifact in artifacts:
            parts = artifact.get("parts", [])
            for part in parts:
                if part.get("type") == "text":
                    typer.echo(part.get("text", ""))

    history = task.get("history", [])
    if history:
        typer.echo(f"\n💬 History ({len(history)} messages)")


@app.command(name="send")
def send_message(
    name: str = typer.Argument(..., help="Name of the Agent."),
    message: str = typer.Option(
        ..., "--message", "-m", help="Message to send."
    ),
    mode: str = typer.Option(
        None, "--mode", help="Execution mode (e.g., 'autonomous')."
    ),
    session_id: str = typer.Option(
        None, "--session-id", "-s", help="Session/context ID."
    ),
    namespace: str = typer.Option(
        None, "--namespace", "-n", help="Namespace of the Agent."
    ),
    port: int = typer.Option(
        9004, "--port", "-p", help="Local port for port-forwarding."
    ),
    output_json: bool = typer.Option(
        False, "--json", help="Output raw JSON response."
    ),
) -> None:
    """Send a message to an Agent via A2A SendMessage."""
    params: dict = {
        "message": {
            "role": "user",
            "parts": [{"type": "text", "text": message}],
        },
    }
    if session_id:
        params["contextId"] = session_id
    if mode:
        params["configuration"] = {"mode": mode}

    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "SendMessage",
        "params": params,
    }

    typer.echo(f"Sending A2A message to {name}...", err=output_json)
    response = _port_forward_and_call(name, namespace, port, payload)

    if output_json:
        typer.echo(json.dumps(response, indent=2))
        return

    if "error" in response:
        err = response["error"]
        typer.echo(f"Error [{err.get('code')}]: {err.get('message')}", err=True)
        sys.exit(1)

    task = response.get("result", {})
    _format_task(task)


@app.command(name="get")
def get_task(
    name: str = typer.Argument(..., help="Name of the Agent."),
    task_id: str = typer.Option(
        ..., "--task-id", "-t", help="Task ID to retrieve."
    ),
    namespace: str = typer.Option(
        None, "--namespace", "-n", help="Namespace of the Agent."
    ),
    port: int = typer.Option(
        9004, "--port", "-p", help="Local port for port-forwarding."
    ),
    output_json: bool = typer.Option(
        False, "--json", help="Output raw JSON response."
    ),
) -> None:
    """Get task status from an Agent via A2A GetTask."""
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "GetTask",
        "params": {"id": task_id},
    }

    typer.echo(f"Getting task {task_id} from {name}...", err=output_json)
    response = _port_forward_and_call(name, namespace, port, payload)

    if output_json:
        typer.echo(json.dumps(response, indent=2))
        return

    if "error" in response:
        err = response["error"]
        typer.echo(f"Error [{err.get('code')}]: {err.get('message')}", err=True)
        sys.exit(1)

    task = response.get("result", {})
    _format_task(task)


@app.command(name="cancel")
def cancel_task(
    name: str = typer.Argument(..., help="Name of the Agent."),
    task_id: str = typer.Option(
        ..., "--task-id", "-t", help="Task ID to cancel."
    ),
    namespace: str = typer.Option(
        None, "--namespace", "-n", help="Namespace of the Agent."
    ),
    port: int = typer.Option(
        9004, "--port", "-p", help="Local port for port-forwarding."
    ),
    output_json: bool = typer.Option(
        False, "--json", help="Output raw JSON response."
    ),
) -> None:
    """Cancel a task on an Agent via A2A CancelTask."""
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "CancelTask",
        "params": {"id": task_id},
    }

    typer.echo(f"Canceling task {task_id} on {name}...", err=output_json)
    response = _port_forward_and_call(name, namespace, port, payload)

    if output_json:
        typer.echo(json.dumps(response, indent=2))
        return

    if "error" in response:
        err = response["error"]
        typer.echo(f"Error [{err.get('code')}]: {err.get('message')}", err=True)
        sys.exit(1)

    task = response.get("result", {})
    _format_task(task)
