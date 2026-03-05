"""CLI entry point and argument parsing."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

logger = logging.getLogger("dep_audit")


def _setup_logging(*, verbose: bool = False, quiet: bool = False) -> None:
    """Configure logging level.

    Default:    INFO  (progress + errors, same as before)
    --verbose:  DEBUG (extra detail)
    --quiet:    WARNING (errors only)
    """
    if quiet:
        level = logging.WARNING
    elif verbose:
        level = logging.DEBUG
    else:
        level = logging.INFO

    # Clear existing handlers to avoid duplicates on repeated calls (e.g. tests)
    logger.handlers.clear()
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.setLevel(level)
    logger.addHandler(handler)
    logger.propagate = False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="dep-audit",
        description="Identify unnecessary dependencies in software projects.",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="Show debug-level output",
    )
    parser.add_argument(
        "-q", "--quiet", action="store_true",
        help="Suppress progress messages (errors only)",
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
    p_scan.add_argument(
        "--exit-code", action="store_true",
        help="Exit with code 1 if any flagged dependencies are found (for CI)",
    )

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
    p_db_export.add_argument("--offline", action="store_true", help="Skip deps.dev API calls")

    # --- scan-list ---
    p_scan_list = sub.add_parser("scan-list", help="Batch scan repos from a TOML file")
    p_scan_list.add_argument("file", help="TOML file with [[repos]] entries")
    p_scan_list.add_argument("--format", choices=["terminal", "json", "markdown"], default="terminal")
    p_scan_list.add_argument("--target-version", help="Language version the project targets")
    p_scan_list.add_argument("--offline", action="store_true", help="Skip deps.dev API calls")
    p_scan_list.add_argument("--repo", help="Only scan this repo (e.g. fastapi/fastapi)")
    p_scan_list.add_argument("--ref", default=None, help="Override git ref for the targeted repo")
    p_scan_list.add_argument("--discover", action="store_true", help="Auto-discover new junk DB entries")
    p_scan_list.add_argument(
        "--exit-code", action="store_true",
        help="Exit with code 1 if any flagged dependencies are found (for CI)",
    )

    # --- cache ---
    p_cache = sub.add_parser("cache", help="Cache management")
    cache_sub = p_cache.add_subparsers(dest="cache_command")
    cache_sub.add_parser("clear", help="Clear all cached data")

    args = parser.parse_args(argv)
    _setup_logging(verbose=args.verbose, quiet=args.quiet)

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
    from dep_audit.scanner import format_report, scan, scan_remote

    # Route to local or remote scan
    if is_github_target(args.path):
        results = scan_remote(
            repo_url=args.path,
            ref=args.ref,
            ecosystem=args.ecosystem,
            target_version=args.target_version,
            include_dev=args.include_dev,
            offline=args.offline,
        )
        if not results:
            logger.error("No supported lockfiles found in the remote repository.")
            return 1
    else:
        project_root = Path(args.path).resolve()
        if not project_root.is_dir():
            logger.error("Error: %s is not a directory", project_root)
            return 1
        results = scan(
            project_root=project_root,
            ecosystem=args.ecosystem,
            target_version=args.target_version,
            include_dev=args.include_dev,
            offline=args.offline,
        )
        if not results:
            logger.error("No supported ecosystems detected.")
            return 1

    has_flagged = False
    for result in results:
        output = format_report(result, args.format)
        print(output)
        if any(c.classification != "ok" for c in result.classifications):
            has_flagged = True

    if args.exit_code and has_flagged:
        return 1
    return 0


def _cmd_scan_list(args: argparse.Namespace) -> int:
    from dep_audit.scan_list import cmd_scan_list
    return cmd_scan_list(args)


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
            from dep_audit import ecosystems as eco_mod

            eco_label = eco_mod.display_name(ecosystem)
            since_str = f" (stdlib since {eco_label} {stdlib_since})" if stdlib_since else ""
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

            sys_name = depsdev.system_name(ecosystem)
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
        logger.error("Usage: dep-audit db {list|show|validate|export}")
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
    from dep_audit.db import get_entry_path, get_junk_entry

    entry = get_junk_entry(args.ecosystem, args.package)
    if entry is None:
        logger.error("No entry found for %s in %s", args.package, args.ecosystem)
        return 1

    # Pretty-print the TOML content
    path = get_entry_path(args.ecosystem, args.package)
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
    from dep_audit.generate import discover_new, format_toml_entry
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
            logger.error("Error: %s is not a directory", project_root)
            return 1
        results = scan(
            project_root=project_root,
            ecosystem=ecosystem,
            offline=args.offline,
        )

    if not results:
        logger.error("No results — nothing to export.")
        return 1

    total_discovered = 0
    for result in results:
        discovered = discover_new(result.classifications, result.ecosystem)
        if not discovered:
            continue

        total_discovered += len(discovered)

        # Print TOML to stdout for review
        for c in discovered:
            print(f"# --- {c.name} ---")
            print(format_toml_entry(c, result.ecosystem))

    if total_discovered == 0:
        logger.info("  No new entries discovered.")
    else:
        logger.info("\n  %d entries found.", total_discovered)

    return 0


def _cmd_cache(args: argparse.Namespace) -> int:
    from dep_audit import cache

    if args.cache_command == "clear":
        cache.clear()
        print("Cache cleared.")
        return 0
    else:
        logger.error("Usage: dep-audit cache {clear}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
