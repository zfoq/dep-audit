"""Batch scanning from TOML config files.

Handles the scan-list CLI command: reading TOML configs,
running batch scans, merging results, writing enriched TOML, and
formatting output as terminal tables or markdown.
"""

from __future__ import annotations

import argparse
import json
import logging
import tomllib
from datetime import UTC, datetime
from pathlib import Path

from dep_audit.scanner import scan_remote

logger = logging.getLogger("dep_audit")


def cmd_scan_list(args: argparse.Namespace) -> int:
    """Batch scan repos from a TOML file."""
    path = Path(args.file)
    if not path.exists():
        logger.error("Error: %s not found", path)
        return 1

    with open(path, "rb") as f:
        config = tomllib.load(f)

    repos = config.get("repos", [])
    if not repos:
        logger.error("No [[repos]] entries found in file.")
        return 1

    # Group results by repo for TOML structure
    grouped: list[dict] = []
    flat_results: list[dict] = []
    all_scan_results = []

    repo_filter = args.repo
    ref_override = args.ref

    for entry in repos:
        name = entry.get("name", entry.get("repo", ""))
        repo = entry.get("repo", "")
        ecosystem = entry.get("ecosystem")
        ref = entry.get("ref", "HEAD")
        target_version = entry.get("target_version")
        old_scans = entry.get("scans", [])

        if not repo:
            continue

        # When --repo is given, skip non-matching repos but preserve them
        if repo_filter and repo != repo_filter:
            grouped.append({
                "name": name,
                "repo": repo,
                "ecosystem": ecosystem or "",
                "scans": old_scans,
            })
            continue

        # CLI flags override per-entry config
        if ref_override:
            ref = ref_override
        tv = args.target_version or target_version

        results = scan_remote(
            repo_url=repo,
            ref=ref,
            ecosystem=ecosystem,
            target_version=tv,
            offline=args.offline,
        )

        new_scans: list[dict] = []
        for result in results:
            all_scan_results.append(result)
            flagged = [c for c in result.classifications if c.classification != "ok"]
            stdlib = [c for c in flagged if c.classification in ("stdlib_backport", "zombie_shim")]
            deprecated = [c for c in flagged if c.classification == "deprecated"]
            total = len(result.lockfile_result.deps)
            scan_data = {
                "ref": ref,
                "target_version": result.target_version,
                "deps": total,
                "flagged": len(flagged),
                "stdlib_replacements": len(stdlib),
                "deprecated": len(deprecated),
                "flagged_names": [c.name for c in flagged],
            }
            new_scans.append(scan_data)
            flat_results.append({
                "name": name,
                "repo": repo,
                "ecosystem": result.ecosystem,
                **scan_data,
            })

        # Merge: new scans replace matching ref+target, preserve others
        merged_scans = _merge_scans(old_scans, new_scans)

        # Detect ecosystem from scan results if not explicitly set
        detected_eco = ecosystem
        if not detected_eco and flat_results:
            detected_eco = flat_results[-1]["ecosystem"]

        repo_entry: dict = {
            "name": name,
            "repo": repo,
            "ecosystem": detected_eco or "",
        }
        if ref != "HEAD":
            repo_entry["ref"] = ref
        if target_version:
            repo_entry["target_version"] = target_version
        repo_entry["scans"] = merged_scans
        grouped.append(repo_entry)

    # Write enriched TOML back to file
    write_scan_list_toml(path, grouped)

    if args.format == "json":
        output = {
            "scanned_at": datetime.now(UTC).isoformat(),
            "results": flat_results,
        }
        print(json.dumps(output, indent=2))
    elif args.format == "markdown":
        print(format_markdown(flat_results))
    else:
        format_terminal(flat_results)

    # Auto-discovery across all scanned repos
    if args.discover:
        _discover_from_scan_results(all_scan_results)

    if args.exit_code and any(r.get("flagged", 0) > 0 for r in flat_results):
        return 1
    return 0


def _merge_scans(old_scans: list[dict], new_scans: list[dict]) -> list[dict]:
    """Merge new scan results into existing ones.

    New scans replace old ones with matching ref+target_version.
    Old scans with different ref+target are preserved.
    """
    merged: dict[tuple[str, str], dict] = {}
    for s in old_scans:
        key = (s.get("ref", "HEAD"), s.get("target_version", ""))
        merged[key] = s
    for s in new_scans:
        key = (s.get("ref", "HEAD"), s.get("target_version", ""))
        merged[key] = s
    return list(merged.values())


def write_scan_list_toml(path: Path, entries: list[dict]) -> None:
    """Write enriched scan-list TOML with scan results inlined.

    Reads the original file to preserve comment lines (section headers),
    then writes the full file with config + scan results.
    """
    # Extract comment blocks from original file
    comments: list[str] = []
    try:
        original = path.read_text(encoding="utf-8")
        for line in original.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                comments.append(stripped)
    except OSError:
        pass

    # Derive ecosystem keywords from registry for section comment detection
    from dep_audit import ecosystems as eco_mod

    eco_keywords: set[str] = set()
    for eco_cfg in eco_mod.all_ecosystems():
        eco_keywords.add(eco_cfg.name.lower())
        eco_keywords.add(eco_cfg.display_name.lower())
    eco_keywords.update({"javascript", "rust"})

    def _is_section_comment(comment: str) -> bool:
        cl = comment.lower()
        return any(kw in cl for kw in eco_keywords)

    lines: list[str] = []
    # Write leading comments (file header) — stop at first ecosystem section
    comment_idx = 0
    while comment_idx < len(comments) and not _is_section_comment(comments[comment_idx]):
        lines.append(comments[comment_idx])
        comment_idx += 1

    if not lines:
        lines.append("# Batch scan config — add [[repos]] entries below.")
        lines.append("# Run: dep-audit scan-list <this-file>")

    section_comments = [c for c in comments if _is_section_comment(c)]

    prev_ecosystem = None
    is_first = True
    for entry in entries:
        eco = entry.get("ecosystem", "")

        # Insert section comment on ecosystem change
        if eco != prev_ecosystem:
            lines.append("")
            matched_comment = None
            eco_lower = eco.lower()
            eco_display_lower = _eco_label(eco).lower()
            for sc in section_comments:
                sc_lower = sc.lower()
                if eco_lower in sc_lower or eco_display_lower in sc_lower:
                    matched_comment = sc
                    break
            if matched_comment:
                lines.append(matched_comment)
            elif eco:
                lines.append(f"# {_eco_label(eco)} projects")
            lines.append("")
            prev_ecosystem = eco
        elif not is_first:
            lines.append("")

        is_first = False
        lines.append("[[repos]]")
        lines.append(f'name = "{entry["name"]}"')
        lines.append(f'repo = "{entry["repo"]}"')
        if eco:
            lines.append(f'ecosystem = "{eco}"')
        if entry.get("ref"):
            lines.append(f'ref = "{entry["ref"]}"')
        if entry.get("target_version"):
            lines.append(f'target_version = "{entry["target_version"]}"')

        for scan in entry.get("scans", []):
            lines.append("")
            lines.append("[[repos.scans]]")
            lines.append(f'ref = "{scan.get("ref", "HEAD")}"')
            lines.append(f'target_version = "{scan.get("target_version", "")}"')
            lines.append(f'deps = {scan.get("deps", 0)}')
            lines.append(f'flagged = {scan.get("flagged", 0)}')
            lines.append(f'stdlib_replacements = {scan.get("stdlib_replacements", 0)}')
            lines.append(f'deprecated = {scan.get("deprecated", 0)}')
            names = scan.get("flagged_names", [])
            if names:
                escaped = ", ".join(f'"{n}"' for n in names)
                lines.append(f"flagged_names = [{escaped}]")
            else:
                lines.append("flagged_names = []")

    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def _eco_label(ecosystem: str) -> str:
    """Human-readable ecosystem label."""
    from dep_audit import ecosystems

    return ecosystems.display_name(ecosystem)


def format_terminal(results: list[dict]) -> None:
    """Print a compact summary table to the terminal."""
    print()
    print(
        f"  {'Project':<20} {'Eco':<7} {'Ref':<10} {'Target':>6}  "
        f"{'Deps':>5}  {'Flagged':>7}  {'Stdlib':>6}  {'Depr':>4}  Details"
    )
    print(
        f"  {'─' * 20} {'─' * 7} {'─' * 10} {'─' * 6}  "
        f"{'─' * 5}  {'─' * 7}  {'─' * 6}  {'─' * 4}  {'─' * 25}"
    )
    for r in results:
        names = ", ".join(r["flagged_names"][:4])
        if len(r["flagged_names"]) > 4:
            names += f" +{len(r['flagged_names']) - 4}"
        ref = r.get("ref", "HEAD")
        if len(ref) > 10:
            ref = ref[:9] + "…"
        print(
            f"  {r['name']:<20} {_eco_label(r.get('ecosystem', '')):<7} {ref:<10} "
            f"{r.get('target_version', ''):>6}  "
            f"{r.get('deps', r.get('total_deps', 0)):>5}  {r['flagged']:>7}  "
            f"{r['stdlib_replacements']:>6}  {r['deprecated']:>4}  {names}"
        )
    print()
    total_flagged = sum(r["flagged"] for r in results)
    total_deps = sum(r.get("deps", r.get("total_deps", 0)) for r in results)
    print(f"  {len(results)} scans, {total_deps} total deps, {total_flagged} flagged")
    print()


def format_markdown(results: list[dict]) -> str:
    """Generate a markdown table for CI or documentation output."""
    lines: list[str] = []
    lines.append("# dep-audit scan-list results")
    lines.append("")
    lines.append(f"*Last updated: {datetime.now(UTC).strftime('%Y-%m-%d')}*")
    lines.append("")
    lines.append("| Project | Ref | Ecosystem | Target | Deps | Flagged | Stdlib | Deprecated | Details |")
    lines.append("|---------|-----|-----------|--------|-----:|--------:|-------:|-----------:|---------|")
    for r in results:
        names = ", ".join(f"`{n}`" for n in r["flagged_names"][:6])
        if len(r["flagged_names"]) > 6:
            names += f" +{len(r['flagged_names']) - 6} more"
        repo_link = f"[{r['name']}](https://github.com/{r['repo']})"
        ref = r.get("ref", "HEAD")
        eco = _eco_label(r.get("ecosystem", ""))
        target = r.get("target_version", "")
        deps = r.get("deps", r.get("total_deps", 0))
        lines.append(
            f"| {repo_link} | {ref} | {eco} | {target} | {deps} | {r['flagged']} | "
            f"{r['stdlib_replacements']} | {r['deprecated']} | {names} |"
        )
    lines.append("")
    total_flagged = sum(r["flagged"] for r in results)
    total_deps = sum(r.get("deps", r.get("total_deps", 0)) for r in results)
    lines.append(f"**{len(results)} scans** — {total_deps} total deps, {total_flagged} flagged")
    lines.append("")
    lines.append("*Generated by `dep-audit scan-list --format markdown`*")
    lines.append("")
    return "\n".join(lines)


def _discover_from_scan_results(scan_results: list) -> None:
    """Discover new junk DB entries from batch scan results."""
    from dep_audit.generate import discover_new

    seen: set[str] = set()
    all_discovered: list = []
    for result in scan_results:
        for c in discover_new(result.classifications, result.ecosystem):
            if c.name not in seen:
                seen.add(c.name)
                all_discovered.append(c)

    if not all_discovered:
        logger.info("\n  No new entries to discover.")
        return

    logger.info("\n  Discovered %d new package(s) across all scans:", len(all_discovered))
    for c in all_discovered:
        logger.info("    %s  →  %s (confidence: %.2f)", c.name, c.classification, c.confidence)
    logger.info("  Use `dep-audit db export --discovered` to export as TOML.")
