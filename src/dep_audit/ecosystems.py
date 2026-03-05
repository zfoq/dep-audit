"""Central ecosystem registry.

Every ecosystem-specific dispatch point in the codebase queries this registry
instead of maintaining its own hardcoded dict/if-chain.  Adding a new ecosystem
(e.g. Cargo) means: create one EcosystemConfig + one parser module.  Zero
changes to scanner, CLI, github, report, or scan_list.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class LockfileSpec:
    """A lockfile name and optional companion files fetched alongside it."""

    file: str
    companions: list[str] = field(default_factory=list)


@dataclass
class EcosystemConfig:
    """Everything the tool needs to know about one ecosystem."""

    name: str                    # "python", "npm"
    system_name: str             # deps.dev API name: "pypi", "npm"
    display_name: str            # human label: "Python", "npm"

    default_target_version: str | Callable[[], str]

    markers: tuple[str, ...]                 # files that indicate this ecosystem
    lockfiles: tuple[LockfileSpec, ...]      # ordered lockfile configs
    full_lockfile_names: frozenset[str]      # lockfiles with resolved transitives

    parse: Callable[..., Any]
    parse_from_content: Callable[..., Any]
    scan_imports: Callable[..., Any] | None = None


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_REGISTRY: dict[str, EcosystemConfig] = {}


def register(config: EcosystemConfig) -> None:
    """Register an ecosystem configuration."""
    _REGISTRY[config.name] = config


def get(name: str) -> EcosystemConfig:
    """Get ecosystem config by name.  Raises KeyError if not found."""
    return _REGISTRY[name]


def get_or_none(name: str) -> EcosystemConfig | None:
    """Get ecosystem config by name, or None."""
    return _REGISTRY.get(name)


def all_ecosystems() -> list[EcosystemConfig]:
    """Return all registered ecosystems in registration order."""
    return list(_REGISTRY.values())


def detect_ecosystem(project_root: Path) -> list[str]:
    """Detect which ecosystems are present by checking marker files."""
    found: list[str] = []
    for eco in _REGISTRY.values():
        if any((project_root / m).exists() for m in eco.markers):
            found.append(eco.name)
    return found


def display_name(ecosystem: str) -> str:
    """Get display name for an ecosystem, falling back to the raw name."""
    eco = _REGISTRY.get(ecosystem)
    return eco.display_name if eco else ecosystem


def resolve_target_version(ecosystem: str) -> str:
    """Resolve the default target version for an ecosystem."""
    eco = _REGISTRY.get(ecosystem)
    if eco is None:
        return ""
    tv = eco.default_target_version
    if callable(tv):
        return tv()
    return tv or ""


# ---------------------------------------------------------------------------
# Register built-in ecosystems
# ---------------------------------------------------------------------------

def _python_target_version() -> str:
    return f"{sys.version_info.major}.{sys.version_info.minor}"


def _register_builtins() -> None:
    from dep_audit.lockfiles_pkg.cargo import _parse_cargo_from_content, parse_cargo
    from dep_audit.lockfiles_pkg.npm import _parse_npm_from_content, parse_npm
    from dep_audit.lockfiles_pkg.python import _parse_python_from_content, parse_python
    from dep_audit.usage import scan_javascript_imports, scan_python_imports, scan_rust_imports

    register(EcosystemConfig(
        name="python",
        system_name="pypi",
        display_name="Python",
        default_target_version=_python_target_version,
        markers=(
            "pyproject.toml", "uv.lock", "poetry.lock",
            "requirements.txt", "setup.py",
        ),
        lockfiles=(
            LockfileSpec("uv.lock", ["pyproject.toml"]),
            LockfileSpec("poetry.lock", ["pyproject.toml"]),
            LockfileSpec("pyproject.toml"),
            LockfileSpec("requirements.txt"),
        ),
        full_lockfile_names=frozenset({"uv.lock", "poetry.lock"}),
        parse=parse_python,
        parse_from_content=_parse_python_from_content,
        scan_imports=scan_python_imports,
    ))

    register(EcosystemConfig(
        name="npm",
        system_name="npm",
        display_name="npm",
        default_target_version="22.0",
        markers=(
            "package.json", "package-lock.json",
            "yarn.lock", "pnpm-lock.yaml",
        ),
        lockfiles=(
            LockfileSpec("package-lock.json", ["package.json"]),
            LockfileSpec("yarn.lock", ["package.json"]),
            LockfileSpec("pnpm-lock.yaml", ["package.json"]),
            LockfileSpec("package.json"),
        ),
        full_lockfile_names=frozenset({
            "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
        }),
        parse=parse_npm,
        parse_from_content=_parse_npm_from_content,
        scan_imports=scan_javascript_imports,
    ))

    register(EcosystemConfig(
        name="cargo",
        system_name="cargo",
        display_name="Rust",
        default_target_version="1.80",
        markers=("Cargo.toml", "Cargo.lock"),
        lockfiles=(
            LockfileSpec("Cargo.lock", ["Cargo.toml"]),
            LockfileSpec("Cargo.toml"),
        ),
        full_lockfile_names=frozenset({"Cargo.lock"}),
        parse=parse_cargo,
        parse_from_content=_parse_cargo_from_content,
        scan_imports=scan_rust_imports,
    ))


_register_builtins()
