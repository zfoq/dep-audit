"""Report formatting: terminal (plain text), JSON, and anchor-grouped views.

The terminal report is designed to be scannable — most actionable stuff first
(unused deps you can just delete), then replacements, then deprecated packages.

Remote scans skip the "unused" section since we can't scan source imports.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from dep_audit.usage import UsageReport

if TYPE_CHECKING:
    from dep_audit.anchors import AnchorResult
    from dep_audit.classify import Classification
    from dep_audit.types import ScanResult


def terminal_report(result: ScanResult) -> str:
    """Generate terminal report string."""
    from dep_audit import ecosystems as eco_mod

    project_name = result.project_name
    ecosystem = result.ecosystem
    target_version = result.target_version
    total_production_deps = len(result.lockfile_result.deps)
    classifications = result.classifications
    usage = result.usage
    anchors = result.anchors
    is_remote = result.is_remote

    lines: list[str] = []
    flagged = [c for c in classifications if c.classification != "ok"]

    mode_label = " (remote)" if is_remote else ""
    eco_label = f"{eco_mod.display_name(ecosystem)} {target_version}"
    lines.append("")
    lines.append(f"{'=' * 3} dep-audit: {project_name}{mode_label} ({eco_label}) {'=' * 3}")
    lines.append("")

    if is_remote:
        lines.append("NOTE: Remote scan — no source code available for import analysis.")
        lines.append("      Usage-based sections (REMOVE) are skipped.")
        lines.append("")

    # Section 1: REMOVE — unused (only for local scans)
    if not is_remote:
        unused = [c for c in flagged if c.is_direct and _is_unused(c, usage)]
        lines.append("REMOVE — unused dependencies (zero effort):")
        lines.append("")
        if unused:
            for c in unused:
                lines.append(f"  {c.name} {'·' * max(1, 40 - len(c.name))} not imported anywhere in project")
                lines.append("      just delete from dependency list")
                also = _also_removes(c.name, anchors)
                if also:
                    lines.append(f"      also removes: {', '.join(also)}")
                lines.append("")
        else:
            lines.append("  (none)")
            lines.append("")

    # Section 2: REPLACE — stdlib alternatives
    if is_remote:
        # For remote: show ALL stdlib_backport/zombie_shim (can't filter by usage)
        replaceable = [
            c for c in flagged
            if c.classification in ("stdlib_backport", "zombie_shim")
        ]
    else:
        replaceable = [
            c for c in flagged
            if c.classification in ("stdlib_backport", "zombie_shim")
            and not _is_unused(c, usage)
        ]
    replaceable.sort(key=lambda c: usage.get(c.name, UsageReport()).import_count)
    lines.append("REPLACE — stdlib alternatives available:")
    lines.append("")
    if replaceable:
        for c in replaceable:
            u = usage.get(c.name, UsageReport())
            label = c.classification
            since = f" ({target_version}+)" if c.stdlib_since else ""
            lines.append(f"  {c.name} {'·' * max(1, 40 - len(c.name))} {label} → {c.replacement}{since}")
            if not is_remote and u.import_count > 0:
                if u.file_count == 1:
                    ref = u.files[0] if u.files else None
                    loc = f" in {ref.path}:{ref.line}" if ref else ""
                    lines.append(f"      {u.import_count} import{loc}")
                else:
                    lines.append(f"      {u.import_count} imports across {u.file_count} files")
            also = _also_removes(c.name, anchors)
            if also:
                lines.append(f"      removing {c.name} also removes {', '.join(also)}")
            lines.append("")
    else:
        lines.append("  (none)")
        lines.append("")

    # Section 3: DEPRECATED
    deprecated = [c for c in flagged if c.classification == "deprecated"]
    lines.append("DEPRECATED:")
    lines.append("")
    if deprecated:
        for c in deprecated:
            repl = f" → {c.replacement}" if c.replacement else ""
            lines.append(f"  {c.name} {'·' * max(1, 40 - len(c.name))} deprecated{repl}")
            for flag in c.flags:
                lines.append(f"      {flag}")
            lines.append("")
    else:
        lines.append("  (none)")
        lines.append("")

    # Summary
    also_removed = set()
    for c in flagged:
        also_removed.update(_also_removes(c.name, anchors))

    lines.append("SUMMARY")
    total_flagged = len(flagged)
    lines.append(f"  {total_flagged} unnecessary package{'s' if total_flagged != 1 else ''} found")
    lines.append(f"  {total_production_deps} total production dependencies scanned")
    if not is_remote:
        unused_list = [c for c in flagged if c.is_direct and _is_unused(c, usage)]
        if unused_list:
            lines.append(f"  {len(unused_list)} zero-effort removal{'s' if len(unused_list) != 1 else ''}")
    if replaceable:
        lines.append(f"  {len(replaceable)} stdlib replacement{'s' if len(replaceable) != 1 else ''}")
    if deprecated:
        lines.append(f"  {len(deprecated)} deprecated")
    if also_removed:
        lines.append(f"  {len(also_removed)} transitive dep{'s' if len(also_removed) != 1 else ''} also freed")
    if is_remote:
        lines.append("  (remote scan — import usage not analyzed)")
    lines.append("")

    return "\n".join(lines)


def json_report(result: ScanResult) -> str:
    """Generate JSON report string."""
    project_name = result.project_name
    ecosystem = result.ecosystem
    target_version = result.target_version
    total_production_deps = len(result.lockfile_result.deps)
    classifications = result.classifications
    usage = result.usage
    anchors = result.anchors
    is_remote = result.is_remote

    flagged = [c for c in classifications if c.classification != "ok"]

    flagged_out: list[dict[str, Any]] = []
    for c in flagged:
        u = usage.get(c.name, UsageReport())
        entry: dict[str, Any] = {
            "name": c.name,
            "version": c.version,
            "classification": c.classification,
            "is_direct": c.is_direct,
            # null for remote scans (we don't know), 0+ for local
            "imports": None if is_remote else u.import_count,
        }
        if c.replacement:
            entry["replacement"] = c.replacement
        if c.stdlib_since:
            entry["stdlib_since"] = c.stdlib_since
        if u.files:
            entry["files"] = [{"path": f.path, "line": f.line} for f in u.files]
        also = _also_removes(c.name, anchors)
        if also:
            entry["also_removes"] = also

        anchor = anchors.get(c.name)
        if anchor and not c.is_direct:
            entry["anchor"] = {
                "name": anchor.anchor_name,
                "verdict": anchor.anchor_verdict,
            }
        else:
            entry["anchor"] = None

        flagged_out.append(entry)

    unused_count = sum(1 for c in flagged if c.is_direct and _is_unused(c, usage)) if not is_remote else None
    replaceable_count = sum(
        1 for c in flagged
        if c.classification in ("stdlib_backport", "zombie_shim")
        and (is_remote or not _is_unused(c, usage))
    )
    deprecated_count = sum(1 for c in flagged if c.classification == "deprecated")
    also_freed: set[str] = set()
    for c in flagged:
        also_freed.update(_also_removes(c.name, anchors))

    report = {
        "project": project_name,
        "ecosystem": ecosystem,
        "target_version": target_version,
        "scan_mode": "remote" if is_remote else "local",
        "scanned_at": datetime.now(UTC).isoformat(),
        "production_deps": total_production_deps,
        "flagged": flagged_out,
        "summary": {
            "zero_effort_removals": unused_count,
            "stdlib_replacements": replaceable_count,
            "deprecated": deprecated_count,
            "total_transitive_freed": len(also_freed),
        },
    }

    return json.dumps(report, indent=2)


def anchor_report(result: ScanResult) -> str:
    """Generate anchor-grouped report."""
    project_name = result.project_name
    classifications = result.classifications
    usage = result.usage
    anchors = result.anchors
    is_remote = result.is_remote

    lines: list[str] = []
    mode_label = " (remote)" if is_remote else ""
    lines.append("")
    lines.append(f"{'=' * 3} dep-audit: {project_name}{mode_label} — grouped by anchor {'=' * 3}")
    lines.append("")

    if is_remote:
        lines.append("NOTE: Remote scan — anchor verdicts unavailable (no import data).")
        lines.append("")

    flagged = [c for c in classifications if c.classification != "ok"]
    if not flagged:
        lines.append("No unnecessary dependencies found.")
        lines.append("")
        return "\n".join(lines)

    # Group by anchor
    cls_map = {c.name: c for c in flagged}
    anchor_groups: dict[str, list[str]] = {}

    for c in flagged:
        a = anchors.get(c.name)
        if c.is_direct:
            anchor_groups.setdefault(c.name, [])
        elif a:
            anchor_groups.setdefault(a.anchor_name, []).append(c.name)

    for anchor_name in sorted(anchor_groups.keys()):
        deps_under = anchor_groups[anchor_name]
        c = cls_map.get(anchor_name)
        u = usage.get(anchor_name, UsageReport())

        if c:
            repl = f" → {c.replacement}" if c.replacement else ""
            verdict = anchors.get(anchor_name)
            verdict_str = f" ({verdict.anchor_verdict})" if verdict else ""
            lines.append(f"{anchor_name}{verdict_str}{repl}")
            if c.classification != "ok":
                pl = "s" if u.import_count != 1 else ""
                lines.append(f"  ├── itself: {c.classification}, {u.import_count} import{pl}")
        else:
            verdict = anchors.get(anchor_name)
            verdict_str = f" ({verdict.anchor_verdict})" if verdict else ""
            lines.append(f"{anchor_name}{verdict_str}")
            pl = "s" if u.import_count != 1 else ""
            lines.append(f"  ├── {u.import_count} import{pl} in source")

        for dep in deps_under:
            dep_c = cls_map.get(dep)
            if dep_c:
                lines.append(f"  └── brings in: {dep} ({dep_c.classification})")

        # Action line
        if is_remote:
            if c and c.replacement:
                lines.append(f"  action: replace with {c.replacement}")
            else:
                lines.append(f"  action: {c.classification if c else 'review'}")
        elif u.import_count == 0:
            lines.append("  action: delete from dependency list")
        elif c and c.replacement:
            pl = "s" if u.import_count != 1 else ""
            total = 1 + len(deps_under)
            lines.append(f"  action: replace {u.import_count} import{pl}, removes {total} packages total")
        else:
            lines.append(f"  action: review {u.import_count} import sites")

        lines.append("")

    return "\n".join(lines)


def _is_unused(c: Classification, usage: dict[str, UsageReport]) -> bool:
    u = usage.get(c.name, UsageReport())
    return c.is_direct and u.import_count == 0


def _also_removes(name: str, anchors: dict[str, AnchorResult]) -> list[str]:
    """Find transitive packages whose anchor is `name`."""
    return [
        pkg for pkg, a in anchors.items()
        if a.anchor_name == name and pkg != name
    ]
