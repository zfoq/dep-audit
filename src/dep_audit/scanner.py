"""Main scan orchestration: lockfile -> classify -> usage scan -> anchor trace -> report.

This is where the whole pipeline comes together. Each step feeds into the next:
parse deps, classify them against the junk DB, scan source for actual usage,
trace anchors for transitive junk, then format the report.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

from dep_audit.anchors import AnchorResult, trace_anchors
from dep_audit.classify import Classification, classify_all
from dep_audit.lockfiles import LockfileResult, detect_ecosystem, parse
from dep_audit.report import anchor_report, json_report, terminal_report
from dep_audit.usage import UsageReport, scan_python_imports


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


def scan(
    project_root: Path,
    ecosystem: str | None = None,
    target_version: str | None = None,
    include_dev: bool = False,
    offline: bool = False,
) -> list[ScanResult]:
    """Run a full scan of the project. Returns one ScanResult per ecosystem."""
    project_root = project_root.resolve()
    project_name = project_root.name

    ecosystems = [ecosystem] if ecosystem else detect_ecosystem(project_root)
    if not ecosystems:
        return []

    results: list[ScanResult] = []
    for eco in ecosystems:
        tv = target_version or _default_target_version(eco)
        result = _scan_ecosystem(project_root, project_name, eco, tv, include_dev, offline)
        results.append(result)

    return results


def _scan_ecosystem(
    project_root: Path,
    project_name: str,
    ecosystem: str,
    target_version: str,
    include_dev: bool,
    offline: bool,
) -> ScanResult:
    """Scan a single ecosystem."""
    # 1. Parse lockfile
    lockfile_result = parse(project_root, ecosystem, include_dev)

    result = ScanResult(
        project_name=project_name,
        ecosystem=ecosystem,
        target_version=target_version,
        lockfile_result=lockfile_result,
    )

    if not lockfile_result.deps:
        return result

    # 1b. Resolve transitive deps if we only have a partial source
    if not offline and not _has_full_lockfile(lockfile_result.source_file):
        print("  Resolving transitive dependencies via deps.dev...", file=sys.stderr)
        lockfile_result = _resolve_transitive_deps(lockfile_result, ecosystem)
        result.lockfile_result = lockfile_result

    # 2. Classify all production packages
    packages = [
        {"name": d.name, "version": d.version, "is_direct": d.is_direct}
        for d in lockfile_result.deps
    ]
    result.classifications = classify_all(ecosystem, packages, target_version, offline)

    # 3. Build dependency tree (from deps.dev or lockfile)
    result.dependency_tree = _build_dep_tree(lockfile_result, ecosystem, offline)

    # 4. Identify packages to scan for usage
    flagged_names = {
        c.name for c in result.classifications if c.classification != "ok"
    }
    direct_names = {d.name for d in lockfile_result.deps if d.is_direct}
    # Scan: all direct deps + all flagged
    scan_names = direct_names | flagged_names

    # 5. Scan source code
    if ecosystem == "python":
        result.usage = scan_python_imports(project_root, scan_names)
    # npm/cargo scanning would go here in Phase 2+

    # 6. Trace anchors for flagged transitive packages
    flagged_transitive = [
        c.name for c in result.classifications
        if c.classification != "ok" and not c.is_direct
    ]
    if flagged_transitive:
        from dep_audit.db import load_junk_db
        junk_db = load_junk_db(ecosystem)
        result.anchors = trace_anchors(
            result.dependency_tree,
            flagged_transitive,
            direct_names,
            junk_db,
            result.usage,
        )

    # Also add anchor entries for flagged direct deps
    for c in result.classifications:
        if c.classification != "ok" and c.is_direct:
            u = result.usage.get(c.name, UsageReport())
            if c.name not in result.anchors:
                verdict = "UNUSED" if u.import_count == 0 else (
                    "REPLACEABLE" if c.classification in ("stdlib_backport", "zombie_shim") else
                    "JUSTIFIED"
                )
                result.anchors[c.name] = AnchorResult(
                    anchor_name=c.name,
                    anchor_verdict=verdict,
                    chain=[c.name],
                )

    return result


def scan_remote(
    repo_url: str,
    ref: str = "HEAD",
    ecosystem: str | None = None,
    target_version: str | None = None,
    include_dev: bool = False,
    offline: bool = False,
) -> list[ScanResult]:
    """Scan a remote GitHub repository by fetching only lockfiles.

    No source code is downloaded, so usage scanning is skipped.
    """
    from dep_audit.github import detect_remote_ecosystem, fetch_lockfile_bundle, parse_github_url
    from dep_audit.lockfiles import parse_from_content

    repo = parse_github_url(repo_url)
    if repo is None:
        return []

    if ref != "HEAD":
        repo.ref = ref

    project_name = f"{repo.owner}/{repo.repo}"

    ecosystems = [ecosystem] if ecosystem else detect_remote_ecosystem(repo)
    if not ecosystems:
        return []

    results: list[ScanResult] = []
    for eco in ecosystems:
        tv = target_version or _default_target_version(eco)

        print(f"  Fetching lockfiles from {project_name} ({repo.ref})...", file=sys.stderr)
        bundle = fetch_lockfile_bundle(repo, eco)
        if not bundle:
            print(f"  No {eco} lockfiles found.", file=sys.stderr)
            continue

        print(f"  Found: {', '.join(bundle.keys())}", file=sys.stderr)

        lockfile_result = parse_from_content(eco, bundle, include_dev)

        result = ScanResult(
            project_name=project_name,
            ecosystem=eco,
            target_version=tv,
            lockfile_result=lockfile_result,
            is_remote=True,
        )

        if not lockfile_result.deps:
            results.append(result)
            continue

        # Resolve transitive deps if we only have a partial source
        if not offline and not _has_full_lockfile(lockfile_result.source_file):
            print("  Resolving transitive dependencies via deps.dev...", file=sys.stderr)
            lockfile_result = _resolve_transitive_deps(lockfile_result, eco)
            result.lockfile_result = lockfile_result

        # Classify all packages (same as local scan)
        packages = [
            {"name": d.name, "version": d.version, "is_direct": d.is_direct}
            for d in lockfile_result.deps
        ]
        result.classifications = classify_all(eco, packages, tv, offline)

        # Build dependency tree
        result.dependency_tree = _build_dep_tree(lockfile_result, eco, offline)

        # Skip: usage scanning (no source code)
        # Skip: anchor tracing (verdicts depend on usage data)

        results.append(result)

    return results


def format_report(result: ScanResult, fmt: str = "terminal") -> str:
    """Format a ScanResult into the requested output format."""
    total = len(result.lockfile_result.deps)
    if fmt == "json":
        return json_report(
            result.project_name, result.ecosystem, result.target_version,
            total, result.classifications, result.usage, result.anchors,
            is_remote=result.is_remote,
        )
    elif fmt == "anchor":
        return anchor_report(
            result.project_name, result.ecosystem, result.target_version,
            result.classifications, result.usage, result.anchors,
            is_remote=result.is_remote,
        )
    else:
        return terminal_report(
            result.project_name, result.ecosystem, result.target_version,
            total, result.classifications, result.usage, result.anchors,
            is_remote=result.is_remote,
        )


def _default_target_version(ecosystem: str) -> str:
    """Get default target version for the ecosystem."""
    if ecosystem == "python":
        return f"{sys.version_info.major}.{sys.version_info.minor}"
    return ""


def _has_full_lockfile(source_file: str) -> bool:
    """Check if the source is a real lockfile (with resolved transitives)."""
    s = source_file.lower()
    return "uv.lock" in s or "poetry.lock" in s


def _resolve_transitive_deps(
    lockfile_result: LockfileResult,
    ecosystem: str,
) -> LockfileResult:
    """Use deps.dev to resolve transitive dependencies for incomplete sources.

    requirements.txt and pyproject.toml only list direct deps, so we query
    deps.dev for each one to discover their full dependency trees.
    This gives us visibility into transitive junk like pytz or six
    pulled in by something you do depend on.
    """
    from dep_audit import depsdev
    from dep_audit.lockfiles import Dependency, _normalize

    known: dict[str, Dependency] = {d.name: d for d in lockfile_result.deps}
    # Track parent→child edges for anchor tracing
    tree_edges: dict[str, list[str]] = {d.name: [] for d in lockfile_result.deps}

    direct_deps = [d for d in lockfile_result.deps if d.is_direct]

    for dep in direct_deps:
        version = dep.version
        if not version:
            # No version pinned — try to get the latest from deps.dev
            pkg = depsdev.get_package(ecosystem, dep.name)
            if pkg and pkg.get("versions"):
                version = pkg["versions"][-1].get("versionKey", {}).get("version", "")
            if not version:
                continue

        data = depsdev.get_dependencies(ecosystem, dep.name, version)
        if not data:
            continue

        nodes = data.get("nodes", [])
        edges = data.get("edges", [])

        # Build node index — node 0 is the package itself
        node_names: list[str] = []
        for node in nodes:
            vk = node.get("versionKey", {})
            node_names.append(_normalize(vk.get("name", "")))

        # Add transitive deps we haven't seen yet
        for node in nodes:
            vk = node.get("versionKey", {})
            name = _normalize(vk.get("name", ""))
            ver = vk.get("version", "")
            relation = node.get("relation", "")

            if relation == "SELF" or not name:
                continue

            if name not in known:
                known[name] = Dependency(
                    name=name,
                    version=ver,
                    is_direct=False,
                    group="default",
                )
                tree_edges[name] = []

        # Record parent→child edges
        for edge in edges:
            from_idx = edge.get("fromNode", 0)
            to_idx = edge.get("toNode", 0)
            if from_idx < len(node_names) and to_idx < len(node_names):
                parent = node_names[from_idx]
                child = node_names[to_idx]
                if parent in tree_edges:
                    tree_edges[parent].append(child)
                else:
                    tree_edges[parent] = [child]

    resolved = LockfileResult(
        ecosystem=lockfile_result.ecosystem,
        deps=list(known.values()),
        source_file=lockfile_result.source_file,
    )
    # Stash edges on the result so _build_dep_tree can use them
    resolved._tree_edges = tree_edges  # type: ignore[attr-defined]
    return resolved


def _build_dep_tree(
    lockfile_result: LockfileResult,
    _ecosystem: str,
    _offline: bool,
) -> dict[str, list[str]]:
    """Build a dependency tree from lockfile data.

    If the lockfile was enriched with deps.dev data (via _resolve_transitive_deps),
    uses the real parent→child edges. Otherwise falls back to a flat structure.
    """
    # Check if we have real edges from dependency resolution
    edges = getattr(lockfile_result, "_tree_edges", None)
    if edges:
        return edges

    tree: dict[str, list[str]] = {}
    for d in lockfile_result.deps:
        tree[d.name] = []
    return tree
