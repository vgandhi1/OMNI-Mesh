"""MFG-Mesh: Industrial IT/OT data platform reference."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("mfg-mesh")
except PackageNotFoundError:
    __version__ = "0.1.0"

__all__ = ["__version__"]
