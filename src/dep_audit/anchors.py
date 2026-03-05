"""Anchor tracing: find which direct dep pulled in a flagged transitive.

When a transitive dependency is junk (e.g. "six"), we need to tell the user
which of *their* direct dependencies is responsible for dragging it in. That
direct dep is the "anchor". Removing or replacing the anchor kills the whole chain.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from dep_audit.usage import UsageReport


@dataclass
class AnchorResult:
    anchor_name: str
    anchor_verdict: str  # UNUSED, REPLACEABLE, OVERKILL, JUSTIFIED
    chain: list[str] = field(default_factory=list)


def trace_anchors(
    dependency_tree: dict[str, list[str]],
    flagged_packages: list[str],
    direct_deps: set[str],
    junk_db: dict[str, dict],
    usage: dict[str, UsageReport],
) -> dict[str, AnchorResult]:
    """For each flagged transitive package, walk the tree upward to find the anchor.

    dependency_tree: {package_name: [dependency_names]}
        Maps each package to the packages it depends on.
    """
    # Build reverse graph: child -> parents
    reverse: dict[str, set[str]] = {}
    for parent, children in dependency_tree.items():
        for child in children:
            reverse.setdefault(child, set()).add(parent)

    results: dict[str, AnchorResult] = {}

    for pkg in flagged_packages:
        if pkg in direct_deps:
            # It's a direct dep, it is its own anchor
            anchor_name = pkg
            chain = [pkg]
        else:
            # Walk upward to find a direct dep
            chain = _find_path_to_direct(pkg, reverse, direct_deps)
            if not chain:
                continue
            anchor_name = chain[0]

        verdict = classify_anchor(anchor_name, junk_db, usage)
        results[pkg] = AnchorResult(
            anchor_name=anchor_name,
            anchor_verdict=verdict,
            chain=chain,
        )

    return results


def _find_path_to_direct(
    start: str,
    reverse: dict[str, set[str]],
    direct_deps: set[str],
) -> list[str]:
    """BFS from start upward through reverse deps to find a direct dep.
    Returns path from direct dep down to start, or empty list."""
    from collections import deque

    visited: set[str] = set()
    queue: deque[list[str]] = deque([[start]])

    while queue:
        path = queue.popleft()
        current = path[-1]

        if current in visited:
            continue
        visited.add(current)

        if current in direct_deps and current != start:
            return list(reversed(path))

        for parent in reverse.get(current, []):
            if parent not in visited:
                queue.append(path + [parent])

    return []


def classify_anchor(
    anchor_name: str,
    junk_db: dict[str, dict],
    usage: dict[str, UsageReport],
) -> str:
    """Figure out how hard it would be to get rid of this anchor.

    UNUSED:      not imported at all → just delete the dep line
    REPLACEABLE: the anchor itself is junk → swap it for the stdlib equivalent
    OVERKILL:    only used in 1-3 places → maybe inline those few calls
    JUSTIFIED:   heavily used → the junk transitive is collateral damage, leave it
    """
    report = usage.get(anchor_name)
    import_count = report.import_count if report else 0

    if import_count == 0:
        return "UNUSED"
    if anchor_name in junk_db:
        return "REPLACEABLE"
    if import_count <= 3:
        return "OVERKILL"
    return "JUSTIFIED"


