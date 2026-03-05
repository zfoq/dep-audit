"""Shared types for lockfile parsers."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Dependency:
    name: str
    version: str
    is_direct: bool = True
    group: str = "default"  # default, dev, test, docs


@dataclass
class LockfileResult:
    ecosystem: str
    deps: list[Dependency] = field(default_factory=list)
    source_file: str = ""
    tree_edges: dict[str, list[str]] | None = None
