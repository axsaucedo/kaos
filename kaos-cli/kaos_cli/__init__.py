"""KAOS CLI - CLI for K8s Agent Orchestration System."""

try:
    from importlib.metadata import version

    __version__ = version("kaos-cli")
except Exception:
    __version__ = "0.4.2.dev0"
