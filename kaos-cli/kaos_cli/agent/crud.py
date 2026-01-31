"""KAOS Agent CRUD commands using kubectl."""

import subprocess
import sys
import typer


def run_kubectl(args: list[str], exit_on_error: bool = True) -> subprocess.CompletedProcess:
    """Run kubectl command."""
    cmd = ["kubectl"] + args
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0 and exit_on_error:
        typer.echo(result.stderr or result.stdout, err=True)
        sys.exit(result.returncode)
    return result


def list_command(namespace: str | None, output: str) -> None:
    """List Agent resources."""
    args = ["get", "agents"]
    
    if namespace:
        args.extend(["-n", namespace])
    else:
        args.append("--all-namespaces")
    
    args.extend(["-o", output])
    
    result = run_kubectl(args)
    typer.echo(result.stdout)


def get_command(name: str, namespace: str, output: str) -> None:
    """Get a specific Agent."""
    args = ["get", "agent", name, "-n", namespace, "-o", output]
    result = run_kubectl(args)
    typer.echo(result.stdout)


def logs_command(name: str, namespace: str, follow: bool, tail: int | None) -> None:
    """View logs from an Agent pod."""
    args = ["logs", "-l", f"agent={name}", "-n", namespace]
    
    if follow:
        args.append("-f")
    
    if tail:
        args.extend(["--tail", str(tail)])
    
    if follow:
        import os
        os.execvp("kubectl", ["kubectl"] + args)
    else:
        result = run_kubectl(args)
        typer.echo(result.stdout)


def delete_command(name: str, namespace: str, force: bool) -> None:
    """Delete an Agent."""
    if not force:
        confirm = typer.confirm(f"Delete Agent '{name}' in namespace '{namespace}'?")
        if not confirm:
            typer.echo("Cancelled.")
            return
    
    args = ["delete", "agent", name, "-n", namespace]
    result = run_kubectl(args)
    typer.echo(result.stdout)


def deploy_command(file: str, namespace: str | None) -> None:
    """Deploy an Agent from YAML file."""
    args = ["apply", "-f", file]
    
    if namespace:
        args.extend(["-n", namespace])
    
    result = run_kubectl(args)
    typer.echo(result.stdout)
