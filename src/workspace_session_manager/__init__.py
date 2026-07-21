"""Workspace Session Manager."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("workspace-session-manager")
except PackageNotFoundError:  # pragma: no cover - source tree without installation
    __version__ = "0.2.0"

__all__ = ["__version__"]
