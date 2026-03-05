# dep-audit

A CLI tool that identifies unnecessary dependencies in software projects. It answers one question existing tools don't: *"which of your dependencies can you remove because the language itself now provides that functionality, or because the package is deprecated with a known replacement, or because you never actually use it?"*

## Install

```bash
# From PyPI (once published)
uvx dep-audit scan .

# From source
uv sync
uv run dep-audit scan .
```

Requires Python 3.11+. Zero runtime dependencies — everything uses the stdlib.

## Quick start

```bash
# Scan current project
dep-audit scan .

# Scan with JSON output
dep-audit scan . --format json

# Scan grouped by anchor dependency
dep-audit scan . --format anchor

# Offline mode (skip deps.dev API calls)
dep-audit scan . --offline

# Check a single package
dep-audit check pytz --ecosystem python

# Scan a remote GitHub repo (no clone needed)
dep-audit scan fastapi/fastapi

# Scan with a specific branch/tag
dep-audit scan pallets/flask --ref 3.1.x
```

## What it finds

- **Stdlib backports** — packages like `pytz`, `tomli`, `typing-extensions` that backport functionality now built into Python. If your minimum Python version is high enough, you don't need them.
- **Zombie shims** — compatibility layers like `six` and `future` that bridge Python 2→3. Python 2 has been EOL since 2020.
- **Deprecated packages** — packages the maintainer has officially abandoned, usually with a recommended replacement (e.g. `pycrypto` → `pycryptodome`).
- **Unused dependencies** — packages listed in your lockfile that aren't imported anywhere in your source code.

## Commands

### `scan`

Scan a project directory for unnecessary dependencies.

```bash
dep-audit scan <path> [--format text|json|anchor] [--offline] [--target-version 3.11]
```

- Detects ecosystem automatically (Python lockfiles: `uv.lock`, `poetry.lock`, `pyproject.toml`, `requirements.txt`)
- Classifies each dependency against the junk database and stdlib map
- Scans source code for actual import usage
- Traces transitive dependencies back to their anchor (direct dependency)
- Supports remote GitHub repos — just pass `owner/repo` or a full URL instead of a local path

#### Remote scanning

```bash
# Using owner/repo shorthand
dep-audit scan fastapi/fastapi

# Using full GitHub URL
dep-audit scan https://github.com/pallets/flask

# Specify a branch or tag
dep-audit scan django/django --ref stable/5.1.x

# Combine with other options
dep-audit scan odoo/odoo --format json --offline
```

Remote scans fetch only the lockfile(s) needed — no full clone required.
Import usage analysis is not available for remote scans since source code is not downloaded.

### `check`

Check a single package against the database.

```bash
dep-audit check <package> --ecosystem python
```

### `db`

Manage the junk database.

```bash
dep-audit db list python       # List all entries grouped by type
dep-audit db show pytz         # Show details for one entry
dep-audit db validate python   # Validate all entries for an ecosystem

# Discover new entries from a project scan
dep-audit db export --discovered .                         # print TOML to stdout
dep-audit db export --discovered fastapi/fastapi --write   # write to db/
```

### `scan-list`

Batch scan multiple repos from a TOML config file.

```bash
dep-audit scan-list showcase.toml                    # terminal table
dep-audit scan-list showcase.toml --format markdown  # markdown table
dep-audit scan-list showcase.toml --format json      # structured JSON

# Auto-discover new junk DB entries across all repos
dep-audit scan-list showcase.toml --discover         # report new entries
dep-audit scan-list showcase.toml --discover --write # write to db/
```

The config file uses `[[repos]]` entries:

```toml
[[repos]]
name = "FastAPI"
repo = "fastapi/fastapi"

[[repos]]
name = "Django"
repo = "django/django"
ecosystem = "python"
```

See [SHOWCASE.md](SHOWCASE.md) for results across popular Python projects.

### `cache`

Manage the local API response cache (`~/.cache/dep-audit/`).

```bash
dep-audit cache stats   # Show cache size and entry count
dep-audit cache clear   # Delete all cached data
```

## Report formats

**Terminal** (default) — prioritized sections:
1. REMOVE — unused deps you can just delete
2. REPLACE — stdlib alternatives available
3. DEPRECATED — packages with known replacements
4. SUMMARY — counts and transitive deps freed

**JSON** — structured output for CI integration.

**Anchor** — groups flagged transitive dependencies under the direct dependency that pulls them in, with an action line for each.

## Architecture

```
src/dep_audit/
├── cli.py          # Argparse entry point
├── scanner.py      # Orchestration pipeline
├── lockfiles.py    # Lockfile parsers (uv.lock, poetry.lock, etc.)
├── classify.py     # Classification decision tree
├── usage.py        # AST-based Python import scanner
├── anchors.py      # Trace transitive deps to their anchor
├── github.py       # GitHub raw content fetcher (remote scanning)
├── depsdev.py      # deps.dev API client
├── db.py           # TOML junk database loader
├── generate.py     # Discovery pipeline + TOML export
├── report.py       # Terminal, JSON, and anchor formatters
├── cache.py        # File-based JSON cache
├── db/python/      # Pre-seeded junk database (25 entries)
└── stdlib_map/     # Stdlib replacement lookup tables
```

## Junk database

Each entry is a TOML file in `db/{ecosystem}/{package}.toml`:

```toml
name = "pytz"
ecosystem = "python"
type = "stdlib_backport"        # stdlib_backport | zombie_shim | deprecated | micro_utility
replacement = "datetime.zoneinfo (3.9+)"
stdlib_since = "3.9"
confidence = 1.0
flags = ["zoneinfo available since 3.9", "pytz has quirky non-standard API"]
validated = 2025-01-15
```

## Auto-discovery

dep-audit can automatically discover new packages that should be in the junk database. When scanning projects, it identifies packages that match detection rules (stdlib_map patterns or deps.dev deprecation flags) but aren't yet in the curated DB.

**Single project:**

```bash
# Preview what would be added
dep-audit db export --discovered fastapi/fastapi

# Write directly to db/python/
dep-audit db export --discovered fastapi/fastapi --write
```

**Batch discovery across multiple repos:**

```bash
# Scan all showcase repos and discover new entries
dep-audit scan-list showcase.toml --discover

# Write discovered entries to db/
dep-audit scan-list showcase.toml --discover --write
```

The typical workflow for growing the database:
1. Run `scan-list` with `--discover` across popular projects
2. Review the discovered entries (printed to stderr)
3. Re-run with `--write` to commit them to `db/`
4. Run `dep-audit db validate python` to verify

## Optional dependencies

```bash
# Rich for colorized terminal output
uv pip install dep-audit[rich]
```

## Development

```bash
uv sync --group dev
uv run pytest
uv run ruff check src/ tests/
```

## License

MIT
