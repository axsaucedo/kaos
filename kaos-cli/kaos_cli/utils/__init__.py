"""Shared utilities for KAOS CLI commands."""

import subprocess

from kaos_cli.install import MONITORING_BACKENDS

DEFAULT_MONITORING_BACKEND = MONITORING_BACKENDS[0]  # "signoz"


def current_context_namespace() -> str | None:
    """Return the namespace configured on the current kubectl context."""
    try:
        result = subprocess.run(
            [
                "kubectl",
                "config",
                "view",
                "--minify",
                "-o",
                "jsonpath={..namespace}",
            ],
            capture_output=True,
            text=True,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def preprocess_optional_value_flag(
    args: list[str], flag: str, default: str
) -> list[str]:
    """Pre-process CLI args to insert a default value when a flag is used without one.

    Detects when `flag` is followed by another option (starts with '-') or is at end
    of args, and inserts `default` as the value.
    """
    new_args = []
    i = 0
    while i < len(args):
        if args[i] == flag:
            new_args.append(args[i])
            if i + 1 < len(args) and not args[i + 1].startswith("-"):
                new_args.append(args[i + 1])
                i += 2
            else:
                new_args.append(default)
                i += 1
        else:
            new_args.append(args[i])
            i += 1
    return new_args
