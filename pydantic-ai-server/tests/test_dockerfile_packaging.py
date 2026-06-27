"""Guard that the container image ships every packaged module.

The runtime image installs the project with ``--no-deps`` from the copied source
tree, so every package listed for the wheel build must also be copied into the
image. A package that is declared but never copied is silently dropped from the
wheel and only fails at container start with ``ModuleNotFoundError``.
"""

import re
import tomllib
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_PYPROJECT = _ROOT / "pyproject.toml"
_DOCKERFILE = _ROOT / "Dockerfile"


def _wheel_packages() -> list[str]:
    data = tomllib.loads(_PYPROJECT.read_text())
    return data["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"]


def _copied_dirs() -> set[str]:
    copied: set[str] = set()
    for line in _DOCKERFILE.read_text().splitlines():
        match = re.match(r"\s*COPY\s+(\S+)/\s+\S+", line)
        if match:
            copied.add(match.group(1).strip("./"))
    return copied


def test_every_wheel_package_is_copied_into_image():
    packages = _wheel_packages()
    assert packages, "expected at least one wheel package to be declared"

    copied = _copied_dirs()
    missing = [pkg for pkg in packages if pkg not in copied]
    assert not missing, (
        f"Dockerfile does not COPY wheel package(s) {missing}; they would be "
        f"dropped from the image and crash the runtime at import. Copied dirs: {sorted(copied)}"
    )
