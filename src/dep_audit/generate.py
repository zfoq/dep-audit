"""Auto-generate new TOML entries for discovered packages.

The discovery pipeline identifies packages that match detection rules (stdlib_map,
deps.dev deprecated) but aren't yet in the curated junk DB. These can be exported
as TOML files for review.
"""

from __future__ import annotations

import datetime
from pathlib import Path

from dep_audit.classify import Classification


def discover_new(
    classifications: list[Classification],
    ecosystem: str,
) -> list[Classification]:
    """Filter classifications to packages not already in the junk DB.

    Returns only non-ok packages that were classified via stdlib_map or deps.dev
    (not from the curated junk DB).
    """
    from dep_audit.db import load_junk_db

    junk_db = load_junk_db(ecosystem)
    discovered = []
    for c in classifications:
        if c.classification == "ok":
            continue
        # Already in the curated DB — not a new discovery
        if c.name in junk_db:
            continue
        discovered.append(c)
    return discovered


def export_discovered(
    classifications: list[Classification],
    ecosystem: str,
    output_dir: Path | None = None,
) -> list[Path]:
    """Write TOML files for discovered packages.

    Returns list of paths written.
    """
    if output_dir is None:
        import tempfile
        output_dir = Path(tempfile.mkdtemp(prefix="dep-audit-export-")) / ecosystem

    output_dir.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []
    for c in classifications:
        if c.classification == "ok":
            continue

        path = output_dir / f"{c.name}.toml"
        content = format_toml_entry(c, ecosystem)
        path.write_text(content, encoding="utf-8")
        written.append(path)

    return written



def format_toml_entry(c: Classification, ecosystem: str) -> str:
    """Format a Classification as a TOML entry string."""
    today = datetime.date.today().isoformat()

    lines: list[str] = []
    lines.append(f'name = "{c.name}"')
    lines.append(f'ecosystem = "{ecosystem}"')
    lines.append(f'type = "{c.classification}"')
    lines.append(f"confidence = {c.confidence}")
    lines.append("")

    if c.replacement:
        lines.append(f'replacement = "{c.replacement}"')
    else:
        lines.append('replacement = ""')

    if c.stdlib_since:
        lines.append(f'stdlib_since = "{c.stdlib_since}"')

    lines.append("")

    # Flags
    lines.append("flags = [")
    for flag in c.flags:
        # Escape any quotes in the flag text
        escaped = flag.replace('"', '\\"')
        lines.append(f'    "{escaped}",')
    lines.append("]")
    lines.append("")

    lines.append(f"validated = {today}")
    lines.append("")

    return "\n".join(lines)
