"""Shared types used across dep_audit modules.

ScanResult lives here (rather than in scanner.py) so that report.py can
import it without creating a circular dependency with scanner.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from dep_audit.anchors import AnchorResult
from dep_audit.classify import Classification
from dep_audit.lockfiles_pkg._types import LockfileResult
from dep_audit.usage import UsageReport


@dataclass
class ScanResult:
    project_name: str
    ecosystem: str
    target_version: str
    lockfile_result: LockfileResult
    classifications: list[Classification] = field(default_factory=list)
    usage: dict[str, UsageReport] = field(default_factory=dict)
    anchors: dict[str, AnchorResult] = field(default_factory=dict)
    dependency_tree: dict[str, list[str]] = field(default_factory=dict)
    is_remote: bool = False
