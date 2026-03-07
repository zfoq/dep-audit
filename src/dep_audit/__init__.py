"""dep-audit: Identify unnecessary dependencies in software projects."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("dep-audit")
except PackageNotFoundError:
    __version__ = "0.1.0"
