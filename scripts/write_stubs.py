"""Parse stub TOML files produced by `dep-audit db export --discovered` and
write each discovered package as an individual file under src/dep_audit/db/.

Usage:
    python3 scripts/write_stubs.py <stubs_dir>

Each file in <stubs_dir> must be named `<ecosystem>.toml` and contain one or
more blocks separated by `# --- <package-name> ---` comment headers.
Packages that already have a DB entry are silently skipped.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path


def parse_stubs(path: Path) -> list[tuple[str, str]]:
    """Return [(name, toml_block), ...] from a combined stub file."""
    content = path.read_text(encoding="utf-8")
    parts = re.split(r"# --- (.+?) ---\n", content)
    # parts: ["", name1, toml1, name2, toml2, ...]
    it = iter(parts[1:])
    return [(name.strip(), block.strip()) for name, block in zip(it, it)]


def main(stubs_dir: Path) -> int:
    db_root = Path("src/dep_audit/db")
    written = 0

    for stub_file in sorted(stubs_dir.glob("*.toml")):
        ecosystem = stub_file.stem  # filename is the ecosystem name
        for name, toml_block in parse_stubs(stub_file):
            dest = db_root / ecosystem / f"{name}.toml"
            if dest.exists():
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(toml_block + "\n", encoding="utf-8")
            print(f"  + {ecosystem}/{name}.toml")
            written += 1

    print(f"\n{written} new stub(s) written.")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <stubs_dir>", file=sys.stderr)
        sys.exit(1)
    sys.exit(main(Path(sys.argv[1])))
