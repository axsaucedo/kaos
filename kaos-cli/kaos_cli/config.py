"""Load and update KAOS CLI configuration."""

from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml


CONFIG_FILENAME = ".kaos-config.yaml"
CONFIG_KEYS = {
    "gateway.address",
    "gateway.through_gateway",
    "auth.issuer",
    "auth.client_id",
    "auth.realm",
    "namespace",
}
DEFAULT_CONFIG = {
    "gateway": {"address": "", "through_gateway": False},
    "auth": {"issuer": "", "client_id": "", "realm": ""},
    "namespace": "default",
    "sessions": {},
}


def config_path(
    path: str | Path | None = None,
    *,
    cwd: Path | None = None,
    home: Path | None = None,
) -> Path:
    """Return the explicit config, otherwise local config before home config."""
    if path is not None:
        return Path(path)
    cwd = cwd or Path.cwd()
    home = home or Path.home()
    local = cwd / CONFIG_FILENAME
    user = home / CONFIG_FILENAME
    if local.exists():
        return local
    if user.exists():
        return user
    return local


def load_config(
    path: str | Path | None = None,
    *,
    cwd: Path | None = None,
    home: Path | None = None,
) -> dict[str, Any]:
    """Load config from disk, filling omitted schema sections with defaults."""
    selected = config_path(path, cwd=cwd, home=home)
    data = yaml.safe_load(selected.read_text()) if selected.exists() else {}
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ValueError(f"KAOS config must be a YAML mapping: {selected}")

    result = deepcopy(DEFAULT_CONFIG)
    for section in ("gateway", "auth"):
        value = data.get(section)
        if isinstance(value, dict):
            result[section].update(value)
    for key in ("namespace", "sessions"):
        if key in data:
            result[key] = data[key]
    if not isinstance(result["sessions"], dict):
        result["sessions"] = {}
    return result


def save_config(
    data: dict[str, Any],
    path: str | Path | None = None,
    *,
    cwd: Path | None = None,
    home: Path | None = None,
) -> Path:
    """Write config to the selected path and return it."""
    selected = config_path(path, cwd=cwd, home=home)
    selected.parent.mkdir(parents=True, exist_ok=True)
    selected.write_text(yaml.safe_dump(data, sort_keys=False))
    return selected


def get_value(data: dict[str, Any], key: str) -> Any:
    """Read a dotted config key."""
    value: Any = data
    for part in key.split("."):
        if not isinstance(value, dict) or part not in value:
            raise KeyError(key)
        value = value[part]
    return value


def set_value(data: dict[str, Any], key: str, value: Any) -> None:
    """Set a supported dotted config key."""
    if key not in CONFIG_KEYS:
        raise KeyError(key)
    target = data
    parts = key.split(".")
    for part in parts[:-1]:
        target = target.setdefault(part, {})
    target[parts[-1]] = value


def session_token(data: dict[str, Any], user: str | None = None) -> str | None:
    """Return a named user's token, or the most recently active session token."""
    sessions = data.get("sessions", {})
    if user:
        session = sessions.get(user, {})
        return session.get("token") if isinstance(session, dict) else None
    for session in reversed(list(sessions.values())):
        if isinstance(session, dict) and session.get("active") and session.get("token"):
            return session["token"]
    return None


def cache_session(
    user: str,
    token: str,
    groups: list[str],
    path: str | Path | None = None,
) -> Path:
    """Cache a login token and mark it as the active session."""
    data = load_config(path)
    for session in data["sessions"].values():
        if isinstance(session, dict):
            session.pop("active", None)
    data["sessions"][user] = {"token": token, "groups": groups, "active": True}
    return save_config(data, path)
