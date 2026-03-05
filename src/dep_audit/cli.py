"""CLI entry point and argument parsing."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="dep-audit",
        description="Identify unnecessary dependencies in software projects.",
    )
    sub = parser.add_subparsers(dest="command")

    # --- scan ---
    p_scan = sub.add_parser("scan", help="Scan project dependencies")
    p_scan.add_argument("path", nargs="?", default=".", help="Project root (default: .)")
    p_scan.add_argument("--ecosystem", help="Force a specific ecosystem")
    p_scan.add_argument("--target-version", help="Language version the project targets")
    p_scan.add_argument("--include-dev", action="store_true", help="Include dev dependencies")
    p_scan.add_argument("--format", choices=["terminal", "json", "anchor"], default="terminal")
    p_scan.add_argument("--offline", action="store_true", help="Skip deps.dev API calls")
    p_scan.add_argument("--ref", default="HEAD", help="Git ref for remote repos (branch/tag/commit)")

    # --- check ---
    p_check = sub.add_parser("check", help="Look up a single package")
    p_check.add_argument("package", help="Package name")
    p_check.add_argument("--ecosystem", default="python", help="Ecosystem (default: python)")
    p_check.add_argument("--target-version", help="Language version")

    # --- db ---
    p_db = sub.add_parser("db", help="Database management")
    db_sub = p_db.add_subparsers(dest="db_command")

    p_db_list = db_sub.add_parser("list", help="List all entries")
    p_db_list.add_argument("ecosystem", nargs="?", default="python")

    p_db_show = db_sub.add_parser("show", help="Show a single entry")
    p_db_show.add_argument("package", help="Package name")
    p_db_show.add_argument("--ecosystem", default="python")

    p_db_validate = db_sub.add_parser("validate", help="Validate all entries")
    p_db_validate.add_argument("ecosystem", nargs="?", default="python")

    p_db_export = db_sub.add_parser("export", help="Export discovered entries")
    p_db_export.add_argument("--discovered", action="store_true", required=True)
    p_db_export.add_argument("--ecosystem", default="python")
    p_db_export.add_argument("path", nargs="?", default=".", help="Project root or owner/repo")
    p_db_export.add_argument("--ref", default="HEAD", help="Git ref for remote repos")
    p_db_export.add_argument("--write", action="store_true", help="Write directly to db/ (default: print to stdout)")
    p_db_export.add_argument("--offline", action="store_true", help="Skip deps.dev API calls")

    # --- scan-list ---
    p_scan_list = sub.add_parser("scan-list", help="Batch scan repos from a TOML file")
    p_scan_list.add_argument("file", help="TOML file with [[repos]] entries")
    p_scan_list.add_argument("--format", choices=["terminal", "json", "markdown"], default="terminal")
    p_scan_list.add_argument("--target-version", help="Language version the project targets")
    p_scan_list.add_argument("--offline", action="store_true", help="Skip deps.dev API calls")
    p_scan_list.add_argument("--discover", action="store_true", help="Auto-discover new junk DB entries")
    p_scan_list.add_argument("--write", action="store_true", help="Write discovered entries to db/")

    # --- cache ---
    p_cache = sub.add_parser("cache", help="Cache management")
    cache_sub = p_cache.add_subparsers(dest="cache_command")
    cache_sub.add_parser("clear", help="Clear all cached data")
    cache_sub.add_parser("stats", help="Show cache statistics")

    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 0

    if args.command == "scan":
        return _cmd_scan(args)
    elif args.command == "scan-list":
        return _cmd_scan_list(args)
    elif args.command == "check":
        return _cmd_check(args)
    elif args.command == "db":
        return _cmd_db(args)
    elif args.command == "cache":
        return _cmd_cache(args)
    else:
        parser.print_help()
        return 1


def _cmd_scan(args: argparse.Namespace) -> int:
    from dep_audit.github import is_github_target

    # Route to remote scan if the target looks like a GitHub URL/shorthand
    if is_github_target(args.path):
        return _cmd_scan_remote(args)

    from dep_audit.scanner import format_report, scan

    project_root = Path(args.path).resolve()
    if not project_root.is_dir():
        print(f"Error: {project_root} is not a directory", file=sys.stderr)
        return 1

    results = scan(
        project_root=project_root,
        ecosystem=args.ecosystem,
        target_version=args.target_version,
        include_dev=args.include_dev,
        offline=args.offline,
    )

    if not results:
        print("No supported ecosystems detected.", file=sys.stderr)
        return 1

    for result in results:
        output = format_report(result, args.format)
        print(output)

        _show_discovered(result)

    return 0


def _cmd_scan_remote(args: argparse.Namespace) -> int:
    from dep_audit.scanner import format_report, scan_remote

    results = scan_remote(
        repo_url=args.path,
        ref=args.ref,
        ecosystem=args.ecosystem,
        target_version=args.target_version,
        include_dev=args.include_dev,
        offline=args.offline,
    )

    if not results:
        print("No supported lockfiles found in the remote repository.", file=sys.stderr)
        return 1

    for result in results:
        output = format_report(result, args.format)
        print(output)

        _show_discovered(result)

    return 0


def _cmd_scan_list(args: argparse.Namespace) -> int:
    import json
    import tomllib
    from datetime import UTC, datetime

    from dep_audit.scanner import scan_remote

    path = Path(args.file)
    if not path.exists():
        print(f"Error: {path} not found", file=sys.stderr)
        return 1

    with open(path, "rb") as f:
        config = tomllib.load(f)

    repos = config.get("repos", [])
    if not repos:
        print("No [[repos]] entries found in file.", file=sys.stderr)
        return 1

    all_results: list[dict] = []
    all_scan_results = []
    for entry in repos:
        name = entry.get("name", entry.get("repo", ""))
        repo = entry.get("repo", "")
        ecosystem = entry.get("ecosystem")
        ref = entry.get("ref", "HEAD")

        if not repo:
            continue

        results = scan_remote(
            repo_url=repo,
            ref=ref,
            ecosystem=ecosystem,
            target_version=args.target_version,
            offline=args.offline,
        )

        for result in results:
            if result.ecosystem != "python" and not ecosystem:
                continue
            all_scan_results.append(result)
            flagged = [c for c in result.classifications if c.classification != "ok"]
            stdlib = [c for c in flagged if c.classification in ("stdlib_backport", "zombie_shim")]
            deprecated = [c for c in flagged if c.classification == "deprecated"]
            total = len(result.lockfile_result.deps)
            all_results.append({
                "name": name,
                "repo": repo,
                "ecosystem": result.ecosystem,
                "total_deps": total,
                "flagged": len(flagged),
                "stdlib_replacements": len(stdlib),
                "deprecated": len(deprecated),
                "flagged_names": [c.name for c in flagged],
                "source": result.lockfile_result.source_file,
            })

    if args.format == "json":
        output = {
            "scanned_at": datetime.now(UTC).isoformat(),
            "results": all_results,
        }
        print(json.dumps(output, indent=2))
    elif args.format == "markdown":
        print(_format_scan_list_markdown(all_results))
    else:
        _format_scan_list_terminal(all_results)

    # Auto-discovery across all scanned repos
    if args.discover:
        _discover_from_scan_results(all_scan_results, write=args.write)

    return 0


def _format_scan_list_terminal(results: list[dict]) -> None:
    """Print a compact summary table to the terminal."""
    print()
    print(f"  {'Project':<25} {'Deps':>5}  {'Flagged':>7}  {'Stdlib':>6}  {'Depr':>4}  Details")
    print(f"  {'─' * 25} {'─' * 5}  {'─' * 7}  {'─' * 6}  {'─' * 4}  {'─' * 30}")
    for r in results:
        names = ", ".join(r["flagged_names"][:5])
        if len(r["flagged_names"]) > 5:
            names += f" +{len(r['flagged_names']) - 5} more"
        print(
            f"  {r['name']:<25} {r['total_deps']:>5}  {r['flagged']:>7}  "
            f"{r['stdlib_replacements']:>6}  {r['deprecated']:>4}  {names}"
        )
    print()
    total_flagged = sum(r["flagged"] for r in results)
    total_deps = sum(r["total_deps"] for r in results)
    print(f"  {len(results)} projects scanned, {total_deps} total deps, {total_flagged} flagged")
    print()


def _format_scan_list_markdown(results: list[dict]) -> str:
    """Generate a markdown table for SHOWCASE.md or CI output."""
    from datetime import UTC, datetime

    lines: list[str] = []
    lines.append("# dep-audit showcase")
    lines.append("")
    lines.append(f"*Last updated: {datetime.now(UTC).strftime('%Y-%m-%d')}*")
    lines.append("")
    lines.append("| Project | Deps | Flagged | Stdlib replacements | Deprecated | Details |")
    lines.append("|---------|-----:|--------:|--------------------:|-----------:|---------|")
    for r in results:
        names = ", ".join(f"`{n}`" for n in r["flagged_names"][:6])
        if len(r["flagged_names"]) > 6:
            names += f" +{len(r['flagged_names']) - 6} more"
        repo_link = f"[{r['name']}](https://github.com/{r['repo']})"
        lines.append(
            f"| {repo_link} | {r['total_deps']} | {r['flagged']} | "
            f"{r['stdlib_replacements']} | {r['deprecated']} | {names} |"
        )
    lines.append("")
    total_flagged = sum(r["flagged"] for r in results)
    total_deps = sum(r["total_deps"] for r in results)
    lines.append(f"**{len(results)} projects scanned** — {total_deps} total deps, {total_flagged} flagged")
    lines.append("")
    lines.append("*Generated by `dep-audit scan-list showcase.toml --format markdown`*")
    lines.append("")
    return "\n".join(lines)


def _show_discovered(result) -> None:
    """Show packages matching detection rules but not in the junk DB."""
    from dep_audit.generate import discover_new

    discovered = discover_new(result.classifications, result.ecosystem)
    if discovered:
        print(f"\n  Found {len(discovered)} package(s) not in the junk database that match detection rules:")
        for c in discovered:
            print(f"    {c.name}  →  {c.classification} (confidence: {c.confidence:.2f})")
        print("\n  Run `dep-audit db export --discovered <path>` to export them.")
        print("  Add --write to save directly to db/.\n")


def _discover_from_scan_results(scan_results: list, *, write: bool) -> None:
    """Discover new junk DB entries from batch scan results."""
    from dep_audit.generate import discover_new, write_to_db

    # Deduplicate across repos (same package may appear in multiple scans)
    seen: set[str] = set()
    all_discovered = []
    for result in scan_results:
        for c in discover_new(result.classifications, result.ecosystem):
            if c.name not in seen:
                seen.add(c.name)
                all_discovered.append((c, result.ecosystem))

    if not all_discovered:
        print("\n  No new entries to discover.", file=sys.stderr)
        return

    print(f"\n  Discovered {len(all_discovered)} new package(s) across all scans:", file=sys.stderr)
    for c, _eco in all_discovered:
        print(f"    {c.name}  →  {c.classification} (confidence: {c.confidence:.2f})", file=sys.stderr)

    if write:
        # Group by ecosystem
        by_eco: dict[str, list] = {}
        for c, eco in all_discovered:
            by_eco.setdefault(eco, []).append(c)
        total = 0
        for eco, entries in by_eco.items():
            written = write_to_db(entries, eco)
            total += len(written)
            for p in written:
                print(f"    wrote {p}", file=sys.stderr)
        print(f"\n  {total} new entries written to db/.", file=sys.stderr)
    else:
        print("  Re-run with --write to save them to db/.", file=sys.stderr)


def _cmd_check(args: argparse.Namespace) -> int:
    from dep_audit import depsdev
    from dep_audit.db import get_junk_entry, load_stdlib_map

    name = args.package
    ecosystem = args.ecosystem
    entry = get_junk_entry(ecosystem, name)
    stdlib_map = load_stdlib_map(ecosystem)

    print()
    if entry:
        etype = entry.get("type", "unknown")
        conf = entry.get("confidence", 0.0)
        print(f"  {name} · {etype} · confidence: {conf:.2f}")
        print()
        summary = entry.get("summary", "")
        if summary:
            print(f"  {summary}")
            print()
        replacement = entry.get("replacement", "")
        stdlib_since = entry.get("stdlib_since", "")
        if replacement:
            since_str = f" (stdlib since {ecosystem.capitalize()} {stdlib_since})" if stdlib_since else ""
            print(f"  Replace with: {replacement}{since_str}")
            print()
    elif name in stdlib_map:
        m = stdlib_map[name]
        print(f"  {name} · stdlib_backport · confidence: 0.95")
        print()
        since = m.get("since", "")
        module = m.get("module", "")
        print(f"  Replace with: {module} (stdlib since {since})")
        print()
    else:
        print(f"  {name} · ok")
        print()
        print("  Not flagged. No known unnecessary usage.")
        print()

    # deps.dev enrichment
    pkg_data = depsdev.get_package(ecosystem, name)
    if pkg_data:
        versions = pkg_data.get("versions", [])
        latest_version = ""
        if versions:
            latest_version = versions[-1].get("versionKey", {}).get("version", "")

        if latest_version:
            deprecated, _ = depsdev.is_deprecated(ecosystem, name, latest_version)
            ver_data = depsdev.get_version(ecosystem, name, latest_version)
            advisories = len(ver_data.get("advisoryKeys", [])) if ver_data else 0

            sys_name = depsdev._system(ecosystem)
            print("  Ecosystem data:")
            print(f"    deps.dev:    https://deps.dev/{sys_name}/{name}")
            print(f"    deprecated:  {'yes' if deprecated else 'no'}")
            print(f"    advisories:  {advisories}")
            print()
    else:
        print("  (deps.dev data unavailable)")
        print()

    return 0


def _cmd_db(args: argparse.Namespace) -> int:
    if args.db_command == "list":
        return _cmd_db_list(args)
    elif args.db_command == "show":
        return _cmd_db_show(args)
    elif args.db_command == "validate":
        return _cmd_db_validate(args)
    elif args.db_command == "export":
        return _cmd_db_export(args)
    else:
        print("Usage: dep-audit db {list|show|validate|export}", file=sys.stderr)
        return 1


def _cmd_db_list(args: argparse.Namespace) -> int:
    from dep_audit.db import list_entries, load_junk_db

    ecosystem = args.ecosystem
    db = load_junk_db(ecosystem)
    groups = list_entries(ecosystem)

    total = len(db)
    print(f"\n  {ecosystem}: {total} entries\n")

    for type_name, names in sorted(groups.items()):
        print(f"  {type_name} ({len(names)}):")
        print(f"    {', '.join(sorted(names))}")
        print()

    return 0


def _cmd_db_show(args: argparse.Namespace) -> int:
    from dep_audit.db import get_junk_entry

    entry = get_junk_entry(args.ecosystem, args.package)
    if entry is None:
        print(f"No entry found for {args.package} in {args.ecosystem}", file=sys.stderr)
        return 1

    # Pretty-print the TOML content
    db_dir = Path(__file__).resolve().parent / "db"
    path = db_dir / args.ecosystem / f"{args.package}.toml"
    if path.exists():
        print(path.read_text(encoding="utf-8"))
    else:
        import json
        print(json.dumps(entry, indent=2, default=str))

    return 0


def _cmd_db_validate(args: argparse.Namespace) -> int:
    from dep_audit.db import validate_all

    errors, warnings = validate_all(args.ecosystem)

    for w in warnings:
        print(f"  WARNING: {w}")
    for e in errors:
        print(f"  ERROR: {e}")

    if not errors and not warnings:
        print(f"  All {args.ecosystem} entries valid.")

    if warnings and not errors:
        print(f"\n  {len(warnings)} warning(s), 0 errors. Validation passed.")
        return 0

    if errors:
        print(f"\n  {len(errors)} error(s), {len(warnings)} warning(s). Validation failed.")
        return 1

    return 0


def _cmd_db_export(args: argparse.Namespace) -> int:
    from dep_audit.generate import discover_new, format_toml_entry, write_to_db
    from dep_audit.github import is_github_target

    ecosystem = args.ecosystem

    # Run a scan to get classifications
    if is_github_target(args.path):
        from dep_audit.scanner import scan_remote
        results = scan_remote(
            repo_url=args.path,
            ref=args.ref,
            ecosystem=ecosystem,
            offline=args.offline,
        )
    else:
        from dep_audit.scanner import scan
        project_root = Path(args.path).resolve()
        if not project_root.is_dir():
            print(f"Error: {project_root} is not a directory", file=sys.stderr)
            return 1
        results = scan(
            project_root=project_root,
            ecosystem=ecosystem,
            offline=args.offline,
        )

    if not results:
        print("No results — nothing to export.", file=sys.stderr)
        return 1

    total_discovered = 0
    total_written = 0
    for result in results:
        discovered = discover_new(result.classifications, result.ecosystem)
        if not discovered:
            continue

        total_discovered += len(discovered)

        if args.write:
            written = write_to_db(discovered, result.ecosystem)
            total_written += len(written)
            for p in written:
                print(f"  wrote {p}")
        else:
            # Print TOML to stdout for review
            for c in discovered:
                print(f"# --- {c.name} ---")
                print(format_toml_entry(c, result.ecosystem))

    if total_discovered == 0:
        print("  No new entries discovered.", file=sys.stderr)
        return 0

    if args.write:
        print(f"\n  {total_written} new entries written to db/.", file=sys.stderr)
    else:
        print(f"\n  {total_discovered} entries found. Re-run with --write to save to db/.", file=sys.stderr)

    return 0


def _cmd_cache(args: argparse.Namespace) -> int:
    from dep_audit import cache

    if args.cache_command == "clear":
        cache.clear()
        print("Cache cleared.")
        return 0
    elif args.cache_command == "stats":
        s = cache.stats()
        print(f"  Entries: {s['entries']}")
        size_kb = s["size_bytes"] / 1024
        if size_kb > 1024:
            print(f"  Size:    {size_kb / 1024:.1f} MB")
        else:
            print(f"  Size:    {size_kb:.1f} KB")
        return 0
    else:
        print("Usage: dep-audit cache {clear|stats}", file=sys.stderr)
        return 1


def _default_version(ecosystem: str) -> str:
    if ecosystem == "python":
        return f"{sys.version_info.major}.{sys.version_info.minor}"
    return ""


if __name__ == "__main__":
    sys.exit(main())
