"""KAOS system create-rbac command for MCPServer RBAC setup."""

import subprocess
import sys
import typer


def create_rbac_command(
    name: str,
    namespace: str,
    namespaces: list[str],
    resources: list[str],
    verbs: list[str],
    read_only: bool,
    cluster_wide: bool,
) -> None:
    """Create RBAC resources for MCPServer Kubernetes runtime.

    Generates and applies ServiceAccount, Role/ClusterRole, and RoleBinding/ClusterRoleBinding.
    """
    if read_only:
        verbs = ["get", "list", "watch"]

    if not verbs:
        verbs = ["get", "list", "watch", "create", "update", "patch", "delete"]

    if not resources:
        resources = ["pods", "deployments", "services", "configmaps", "secrets"]

    # Generate YAML
    yaml_docs = []

    # ServiceAccount
    sa_yaml = f"""apiVersion: v1
kind: ServiceAccount
metadata:
  name: {name}
  namespace: {namespace}
"""
    yaml_docs.append(sa_yaml)

    # Role or ClusterRole
    if cluster_wide:
        role_yaml = f"""apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: {name}
rules:
- apiGroups: ["", "apps", "batch"]
  resources: [{', '.join(f'"{r}"' for r in resources)}]
  verbs: [{', '.join(f'"{v}"' for v in verbs)}]
"""
    else:
        role_yaml = f"""apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: {name}
  namespace: {namespace}
rules:
- apiGroups: ["", "apps", "batch"]
  resources: [{', '.join(f'"{r}"' for r in resources)}]
  verbs: [{', '.join(f'"{v}"' for v in verbs)}]
"""
    yaml_docs.append(role_yaml)

    # RoleBinding or ClusterRoleBinding
    if cluster_wide:
        binding_yaml = f"""apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: {name}
subjects:
- kind: ServiceAccount
  name: {name}
  namespace: {namespace}
roleRef:
  kind: ClusterRole
  name: {name}
  apiGroup: rbac.authorization.k8s.io
"""
    else:
        # If specific namespaces provided, create RoleBindings in each
        if namespaces:
            for ns in namespaces:
                binding_yaml = f"""apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: {name}
  namespace: {ns}
subjects:
- kind: ServiceAccount
  name: {name}
  namespace: {namespace}
roleRef:
  kind: Role
  name: {name}
  apiGroup: rbac.authorization.k8s.io
"""
                yaml_docs.append(binding_yaml)
        else:
            binding_yaml = f"""apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: {name}
  namespace: {namespace}
subjects:
- kind: ServiceAccount
  name: {name}
  namespace: {namespace}
roleRef:
  kind: Role
  name: {name}
  apiGroup: rbac.authorization.k8s.io
"""

    if not namespaces or cluster_wide:
        yaml_docs.append(binding_yaml)

    combined_yaml = "---\n".join(yaml_docs)

    # Output the YAML
    typer.echo("Generated RBAC resources:")
    typer.echo("-" * 40)
    typer.echo(combined_yaml)
    typer.echo("-" * 40)

    # Apply via kubectl
    typer.echo("\nApplying RBAC resources...")
    try:
        result = subprocess.run(
            ["kubectl", "apply", "-f", "-"],
            input=combined_yaml,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            typer.echo("✅ RBAC resources created successfully!")
            typer.echo(f"\nUse in your MCPServer with:")
            typer.echo(f"  spec:")
            typer.echo(f"    serviceAccountName: {name}")
        else:
            typer.echo(f"Error: {result.stderr}", err=True)
            sys.exit(1)
    except FileNotFoundError:
        typer.echo("Error: kubectl not found. Please install kubectl.", err=True)
        sys.exit(1)
