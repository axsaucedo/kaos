"""Observability and development pgvector installation helpers."""

import json
import subprocess

import typer

from . import (
    PGVECTOR_DB, PGVECTOR_IMAGE, PGVECTOR_NAME, PGVECTOR_PASSWORD,
    PGVECTOR_SECRET_KEY, PGVECTOR_SECRET_NAME, PGVECTOR_USER,
)


def _root():
    """Resolve shared helpers through the public package for compatibility."""
    import kaos_cli.install as root

    return root
def _create_jaeger_ui_config(namespace: str) -> None:
    """Create ConfigMap with Jaeger UI config for dark theme."""
    ui_config = json.dumps({"themes": {"enabled": True}})
    cm_yaml = (
        f"apiVersion: v1\nkind: ConfigMap\nmetadata:\n"
        f"  name: jaeger-ui-config\n  namespace: {namespace}\n"
        f"data:\n  ui-config.json: '{ui_config}'\n"
    )
    result = subprocess.run(
        ["kubectl", "apply", "-f", "-"],
        input=cm_yaml,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        typer.echo(
            f"Warning: Could not create Jaeger UI config: {result.stderr}", err=True
        )

def _install_signoz(namespace: str) -> bool:
    """Install SigNoz monitoring stack."""
    typer.echo("Installing SigNoz monitoring stack...")

    result = _root().run_helm_command(
        ["repo", "add", "signoz", "https://charts.signoz.io", "--force-update"],
        check=False,
    )
    if result.returncode != 0 and "already exists" not in result.stderr:
        typer.echo(f"Warning adding SigNoz repo: {result.stderr}", err=True)

    _root().run_helm_command(["repo", "update"], check=False)

    result = _root().run_helm_command(
        [
            "upgrade",
            "--install",
            "signoz",
            "signoz/signoz",
            "--namespace",
            namespace,
            "--create-namespace",
        ],
        check=False,
    )
    if result.returncode != 0:
        typer.echo(f"Error installing SigNoz: {result.stderr}", err=True)
        return False

    typer.echo(f"✅ SigNoz monitoring installed in '{namespace}' namespace")
    return True

def _install_jaeger(namespace: str) -> bool:
    """Install Jaeger all-in-one with OTLP collector and dark mode."""
    typer.echo("Installing Jaeger all-in-one...")

    result = _root().run_helm_command(
        [
            "repo",
            "add",
            "jaegertracing",
            "https://jaegertracing.github.io/helm-charts",
            "--force-update",
        ],
        check=False,
    )
    if result.returncode != 0 and "already exists" not in result.stderr:
        typer.echo(f"Warning adding Jaeger repo: {result.stderr}", err=True)

    _root().run_helm_command(["repo", "update"], check=False)

    # Create ConfigMap before Helm install to avoid mount race condition
    subprocess.run(
        ["kubectl", "create", "namespace", namespace],
        capture_output=True,
        text=True,
    )
    _create_jaeger_ui_config(namespace)

    result = _root().run_helm_command(
        [
            "upgrade",
            "--install",
            "jaeger",
            "jaegertracing/jaeger",
            "--namespace",
            namespace,
            "--create-namespace",
            "--set",
            "allInOne.enabled=true",
            "--set",
            "collector.enabled=false",
            "--set",
            "query.enabled=false",
            "--set",
            "agent.enabled=false",
            "--set",
            "provisionDataStore.cassandra=false",
            "--set-json",
            'allInOne.extraEnv=[{"name":"QUERY_UI_CONFIG","value":"/etc/jaeger/ui-config.json"}]',
            "--set-json",
            'allInOne.extraConfigmapMounts=[{"name":"jaeger-ui-config","mountPath":"/etc/jaeger","configMap":"jaeger-ui-config"}]',
        ],
        check=False,
    )
    if result.returncode != 0:
        typer.echo(f"Error installing Jaeger: {result.stderr}", err=True)
        return False

    typer.echo(f"✅ Jaeger installed in '{namespace}' namespace (dark mode enabled)")
    return True

def _install_monitoring(backend: str, namespace: str) -> bool:
    """Install monitoring stack for the given backend."""
    if backend == "jaeger":
        return _install_jaeger(namespace)
    return _install_signoz(namespace)

def _pgvector_dsn(namespace: str) -> str:
    """DSN for the in-cluster development pgvector Postgres."""
    host = f"{PGVECTOR_NAME}.{namespace}.svc.cluster.local"
    return f"postgresql://{PGVECTOR_USER}:{PGVECTOR_PASSWORD}@{host}:5432/{PGVECTOR_DB}"

def _pgvector_manifest(namespace: str) -> str:
    """Render the Secret, Deployment, and Service for the dev pgvector Postgres."""
    dsn = _pgvector_dsn(namespace)
    return f"""apiVersion: v1
kind: Secret
metadata:
  name: {PGVECTOR_SECRET_NAME}
  namespace: {namespace}
stringData:
  {PGVECTOR_SECRET_KEY}: {dsn}
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {PGVECTOR_NAME}
  namespace: {namespace}
spec:
  replicas: 1
  selector:
    matchLabels:
      app: {PGVECTOR_NAME}
  template:
    metadata:
      labels:
        app: {PGVECTOR_NAME}
    spec:
      containers:
      - name: postgres
        image: {PGVECTOR_IMAGE}
        env:
        - name: POSTGRES_USER
          value: {PGVECTOR_USER}
        - name: POSTGRES_PASSWORD
          value: {PGVECTOR_PASSWORD}
        - name: POSTGRES_DB
          value: {PGVECTOR_DB}
        ports:
        - containerPort: 5432
        readinessProbe:
          exec:
            command: ["pg_isready", "-U", "{PGVECTOR_USER}", "-d", "{PGVECTOR_DB}"]
          initialDelaySeconds: 5
          periodSeconds: 5
---
apiVersion: v1
kind: Service
metadata:
  name: {PGVECTOR_NAME}
  namespace: {namespace}
spec:
  selector:
    app: {PGVECTOR_NAME}
  ports:
  - port: 5432
    targetPort: 5432
"""

def _install_pgvector(namespace: str) -> bool:
    """Provision a development pgvector Postgres for external-mode MemoryStores.

    This is an opt-in, dev-only datastore (single replica, no persistence,
    default credentials). It writes a Secret holding the connection DSN that an
    ``external`` MemoryStore references via connectionSecretRef.
    """
    typer.echo("Installing development pgvector Postgres...")

    ns_result = _root()._run_kubectl(["create", "namespace", namespace], check=False)
    if ns_result.returncode != 0 and "already exists" not in ns_result.stderr:
        typer.echo(f"Warning creating namespace: {ns_result.stderr}", err=True)

    result = _root()._run_kubectl(
        ["apply", "-f", "-"], check=False, input=_pgvector_manifest(namespace)
    )
    if result.returncode != 0:
        typer.echo(f"Error installing pgvector Postgres: {result.stderr}", err=True)
        return False

    _root()._run_kubectl(
        [
            "rollout",
            "status",
            f"deployment/{PGVECTOR_NAME}",
            "--namespace",
            namespace,
            "--timeout=120s",
        ],
        check=False,
    )

    typer.echo(
        f"✅ pgvector Postgres installed in '{namespace}' "
        f"(dev-only; DSN in secret '{PGVECTOR_SECRET_NAME}' key '{PGVECTOR_SECRET_KEY}')"
    )
    return True

def _uninstall_pgvector(namespace: str) -> bool:
    """Remove the development pgvector Postgres and its connection secret."""
    typer.echo("Uninstalling development pgvector Postgres...")
    for kind, name in (
        ("deployment", PGVECTOR_NAME),
        ("service", PGVECTOR_NAME),
        ("secret", PGVECTOR_SECRET_NAME),
    ):
        _root()._run_kubectl(
            ["delete", kind, name, "--namespace", namespace, "--ignore-not-found"],
            check=False,
        )
    typer.echo(f"✅ pgvector Postgres uninstalled from '{namespace}'")
    return True

def _uninstall_monitoring(backend: str, namespace: str) -> bool:
    """Uninstall monitoring stack for the given backend."""
    release = "jaeger" if backend == "jaeger" else "signoz"
    typer.echo(f"Uninstalling {backend} from namespace '{namespace}'...")

    result = _root().run_helm_command(
        ["uninstall", release, "--namespace", namespace],
        check=False,
    )

    if result.returncode == 0:
        # Clean up Jaeger UI ConfigMap if applicable
        if backend == "jaeger":
            subprocess.run(
                [
                    "kubectl",
                    "delete",
                    "configmap",
                    "jaeger-ui-config",
                    "-n",
                    namespace,
                    "--ignore-not-found",
                ],
                capture_output=True,
                text=True,
            )
        typer.echo(f"✅ {backend.capitalize()} uninstalled from '{namespace}'")
        return True
    elif "not found" in result.stderr.lower():
        typer.echo(
            f"{backend.capitalize()} release not found in namespace '{namespace}'."
        )
        return True
    else:
        typer.echo(f"Error uninstalling {backend}: {result.stderr}", err=True)
        return False

def _get_otel_endpoint(backend: str, namespace: str) -> str:
    """Return the OTLP collector endpoint for the given backend."""
    if backend == "jaeger":
        return f"http://jaeger.{namespace}:4317"
    return f"http://signoz-otel-collector.{namespace}:4317"
