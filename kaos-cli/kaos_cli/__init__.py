"""KAOS CLI - CLI for K8s Agent Orchestration System."""

try:
    from importlib.metadata import version

    __version__ = version("kaos-cli")
except Exception:
    __version__ = "0.8.3.dev0"
