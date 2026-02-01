"""KAOS install/uninstall commands moved to system subcommand.

This module is re-exported from the original install.py for backwards compatibility
but all commands are now under 'kaos system install/uninstall'.
"""

from kaos_cli.install import (
    install_command,
    uninstall_command,
    check_helm_installed,
    run_helm_command,
)

__all__ = [
    "install_command",
    "uninstall_command",
    "check_helm_installed",
    "run_helm_command",
]
