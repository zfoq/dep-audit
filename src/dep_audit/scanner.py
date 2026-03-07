"""Main scan orchestration: lockfile -> classify -> usage scan -> anchor trace -> report.

This is where the whole pipeline comes together. Each step feeds into the next:
parse deps, classify them against the junk DB, scan source for actual usage,
trace anchors for transitive junk, then format the report.
"""

from __future__ import annotations

import logging
from pathlib import Path

from dep_audit import ecosystems
from dep_audit.anchors import AnchorResult, trace_anchors
from dep_audit.classify import classify_all
from dep_audit.lockfiles_pkg import LockfileResult, parse
from dep_audit.report import json_report, sarif_report, terminal_report
from dep_audit.types import ScanResult

logger = logging.getLogger("dep_audit")

# Re-export so existing `from dep_audit.scanner import ScanResult` keeps working
__all__ = ["ScanResult", "scan", "scan_remote", "format_report"]


def scan(
    project_root: Path,
    ecosystem: str | None = None,
    target_version: str | None = None,
    include_dev: bool = False,
    offline: bool = False,
    ignore: set[str] | None = None,
) -> list[ScanResult]:
    """Run a full scan of the project. Returns one ScanResult per ecosystem."""
    project_root = project_root.resolve()
    project_name = project_root.name

    eco_list = [ecosystem] if ecosystem else ecosystems.detect_ecosystem(project_root)
    if not eco_list:
        return []

    from dep_audit.config import detect_target_version

    results: list[ScanResult] = []
    for eco in eco_list:
        tv = (
            target_version
            or detect_target_version(project_root, eco)
            or ecosystems.resolve_target_version(eco)
        )
        result = _scan_ecosystem(project_root, project_name, eco, tv, include_dev, offline, ignore or set())
        results.append(result)

    return results


def _scan_ecosystem(
    project_root: Path,
    project_name: str,
    ecosystem: str,
    target_version: str,
    include_dev: bool,
    offline: bool,
    ignore: set[str],
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
        logger.info("  Resolving transitive dependencies via deps.dev...")
        lockfile_result = _resolve_transitive_deps(lockfile_result, ecosystem)
        result.lockfile_result = lockfile_result

    # 2. Load junk DB once — used for both classification and anchor tracing
    from dep_audit.db import load_junk_db
    junk_db = load_junk_db(ecosystem)

    # 2a. Classify all production packages
    packages = [
        {"name": d.name, "version": d.version, "is_direct": d.is_direct}
        for d in lockfile_result.deps
    ]
    result.classifications = classify_all(ecosystem, packages, target_version, offline, junk_db=junk_db)

    # 2b. Apply ignore list (config file + inline # dep-audit: ignore comments)
    effective_ignore = ignore | lockfile_result.inline_ignores
    if effective_ignore:
        result.classifications = [
            c for c in result.classifications if c.name not in effective_ignore
        ]

    # 3. Build dependency tree (from deps.dev or lockfile)
    result.dependency_tree = _build_dep_tree(lockfile_result)

    # 4. Identify packages to scan for usage
    flagged_names = {
        c.name for c in result.classifications if c.classification != "ok"
    }
    direct_names = {d.name for d in lockfile_result.deps if d.is_direct}
    # Scan: all direct deps + all flagged
    scan_names = direct_names | flagged_names

    # 5. Scan source code
    eco_config = ecosystems.get_or_none(ecosystem)
    if eco_config and eco_config.scan_imports:
        result.usage = eco_config.scan_imports(project_root, scan_names)

    # 6. Trace anchors for flagged packages
    from dep_audit.anchors import classify_anchor

    flagged_transitive = [
        c.name for c in result.classifications
        if c.classification != "ok" and not c.is_direct
    ]

    if flagged_transitive:
        result.anchors = trace_anchors(
            result.dependency_tree,
            flagged_transitive,
            direct_names,
            junk_db,
            result.usage,
        )

    # Also add anchor entries for flagged direct deps
    for c in result.classifications:
        if c.classification != "ok" and c.is_direct and c.name not in result.anchors:
            verdict = classify_anchor(c.name, junk_db, result.usage)
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
    ignore: set[str] | None = None,
) -> list[ScanResult]:
    """Scan a remote GitHub repository by fetching only lockfiles.

    No source code is downloaded, so usage scanning is skipped.
    """
    from dep_audit.github import fetch_all_lockfile_bundles, fetch_lockfile_bundle, parse_github_url
    from dep_audit.lockfiles_pkg import parse_from_content

    repo = parse_github_url(repo_url)
    if repo is None:
        return []

    if ref != "HEAD":
        repo.ref = ref

    project_name = f"{repo.owner}/{repo.repo}"

    if ecosystem:
        # Single ecosystem: fetch only what's needed (fetch_lockfile_bundle is more
        # targeted than fetch_all_lockfile_bundles which probes all ecosystems).
        eco_bundles = {ecosystem: fetch_lockfile_bundle(repo, ecosystem)}
    else:
        logger.info("  Fetching lockfiles from %s (%s)...", project_name, repo.ref)
        eco_bundles = fetch_all_lockfile_bundles(repo)

    if not eco_bundles:
        return []

    from dep_audit.config import detect_target_version_from_bundle

    results: list[ScanResult] = []
    for eco, bundle in eco_bundles.items():
        tv = (
            target_version
            or detect_target_version_from_bundle(bundle, eco)
            or ecosystems.resolve_target_version(eco)
        )

        if not bundle:
            logger.warning("  No %s lockfiles found.", eco)
            continue

        logger.info("  Found: %s", ", ".join(bundle.keys()))

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
            logger.info("  Resolving transitive dependencies via deps.dev...")
            lockfile_result = _resolve_transitive_deps(lockfile_result, eco)
            result.lockfile_result = lockfile_result

        # Classify all packages (same as local scan)
        packages = [
            {"name": d.name, "version": d.version, "is_direct": d.is_direct}
            for d in lockfile_result.deps
        ]
        result.classifications = classify_all(eco, packages, tv, offline)

        # Apply ignore list (config + inline # dep-audit: ignore comments)
        effective_ignore = (ignore or set()) | lockfile_result.inline_ignores
        if effective_ignore:
            result.classifications = [
                c for c in result.classifications if c.name not in effective_ignore
            ]

        # Build dependency tree
        result.dependency_tree = _build_dep_tree(lockfile_result)

        # Skip: usage scanning (no source code)

        # Trace anchors — chains show "pulled in by X" even without usage data
        direct_names = {d.name for d in lockfile_result.deps if d.is_direct}
        flagged_transitive = [
            c.name for c in result.classifications
            if c.classification != "ok" and not c.is_direct
        ]
        if flagged_transitive:
            result.anchors = _trace_anchors_no_usage(
                result.dependency_tree, flagged_transitive, direct_names,
            )

        results.append(result)

    return results


def format_report(result: ScanResult, fmt: str = "terminal") -> str:
    """Format a ScanResult into the requested output format."""
    if fmt == "json":
        return json_report(result)
    elif fmt == "sarif":
        return sarif_report(result)
    else:
        return terminal_report(result)


def _has_full_lockfile(source_file: str) -> bool:
    """Check if the source is a real lockfile (with resolved transitives)."""
    from pathlib import PurePosixPath

    name = PurePosixPath(source_file).name.lower()
    return any(name in eco.full_lockfile_names for eco in ecosystems.all_ecosystems())


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
    from dep_audit.lockfiles_pkg import Dependency, normalize_package_name

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
            node_names.append(normalize_package_name(vk.get("name", "")))

        # Add transitive deps we haven't seen yet
        for node in nodes:
            vk = node.get("versionKey", {})
            name = normalize_package_name(vk.get("name", ""))
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

    return LockfileResult(
        ecosystem=lockfile_result.ecosystem,
        deps=list(known.values()),
        source_file=lockfile_result.source_file,
        tree_edges=tree_edges,
    )


def _trace_anchors_no_usage(
    dependency_tree: dict[str, list[str]],
    flagged_packages: list[str],
    direct_deps: set[str],
) -> dict[str, AnchorResult]:
    """Trace anchors without usage data (remote scans).

    Provides chain information ("pulled in by X") with an UNKNOWN verdict
    since we can't classify without import usage data.
    """
    from dep_audit.anchors import find_path_to_direct

    # Build reverse graph: child -> parents
    reverse: dict[str, set[str]] = {}
    for parent, children in dependency_tree.items():
        for child in children:
            reverse.setdefault(child, set()).add(parent)

    results: dict[str, AnchorResult] = {}
    for pkg in flagged_packages:
        if pkg in direct_deps:
            chain = [pkg]
            anchor_name = pkg
        else:
            chain = find_path_to_direct(pkg, reverse, direct_deps)
            if not chain:
                continue
            anchor_name = chain[0]

        results[pkg] = AnchorResult(
            anchor_name=anchor_name,
            anchor_verdict="UNKNOWN",
            chain=chain,
        )

    return results


def _build_dep_tree(lockfile_result: LockfileResult) -> dict[str, list[str]]:
    """Build a dependency tree from lockfile data.

    If the lockfile was enriched with deps.dev data (via _resolve_transitive_deps),
    uses the real parent→child edges. Otherwise falls back to a flat structure.
    """
    if lockfile_result.tree_edges is not None:
        return lockfile_result.tree_edges

    tree: dict[str, list[str]] = {}
    for d in lockfile_result.deps:
        tree[d.name] = []
    return tree
