# dep-audit

A CLI tool that identifies unnecessary dependencies in software projects. It answers the question existing tools don't ask: *"which of your dependencies can you remove because the language itself now provides that functionality, the package is deprecated, or you never actually import it?"*

## What it finds

| Category | Examples |
|---|---|
| **Stdlib backports** | `pytz` → `zoneinfo`, `tomli` → `tomllib`, `lazy-static` → `std::sync::LazyLock` |
| **Zombie shims** | `six`, `future` — Python 2/3 compat layers; `winapi` → `windows-sys` |
| **Deprecated packages** | `pycrypto` → `pycryptodome`, `failure` → `thiserror + anyhow`, `request` (npm) |
| **Micro-utilities** | `is-odd`, `is-even`, `left-pad` — single expressions in native code |
| **Unused dependencies** | Packages in your lockfile that are never imported in your source code |

Supports **Python**, **npm/Node.js**, and **Cargo/Rust**.

## Install

```bash
# Run without installing (recommended for one-off scans)
uvx dep-audit scan .

# Install globally with pipx
pipx install dep-audit

# Install in a project
uv add --dev dep-audit
pip install dep-audit
```

Requires Python 3.11+. Zero runtime dependencies.

## Quick start

```bash
# Scan the current directory
dep-audit scan .

# Scan a specific project
dep-audit scan /path/to/my-project

# Scan a GitHub repo (no clone needed)
dep-audit scan fastapi/fastapi
dep-audit scan django/django --ref stable/5.1.x

# Check a single package
dep-audit check pytz
dep-audit check lazy-static --ecosystem cargo
dep-audit check left-pad --ecosystem npm --offline
```

## Ecosystems

| Ecosystem | Detection | Lockfiles parsed |
|---|---|---|
| **Python** | `pyproject.toml`, `requirements.txt`, `setup.py` | uv.lock, poetry.lock, pyproject.toml, requirements.txt |
| **npm** | `package.json` | package-lock.json, yarn.lock, pnpm-lock.yaml, package.json |
| **Cargo** | `Cargo.toml` | Cargo.lock, Cargo.toml |

dep-audit detects the ecosystem automatically. In multi-language repos it scans each detected ecosystem separately.

## Commands

### `scan` — scan a project

```bash
dep-audit scan [path] [options]
```

| Option | Description |
|---|---|
| `path` | Project root or `owner/repo` GitHub shorthand (default: `.`) |
| `--format terminal\|json\|sarif` | Output format (default: `terminal`) |
| `--offline` | Skip deps.dev API calls (faster, no network needed) |
| `--target-version 3.11` | Override the language version for stdlib detection |
| `--ecosystem python` | Force a specific ecosystem instead of auto-detecting |
| `--include-dev` | Include dev/test dependencies in the scan |
| `--exit-code` | Exit with code 1 if any issues are found (for CI) |
| `--min-confidence 0.8` | With `--exit-code`: only fail on findings at or above this threshold (0.0–1.0) |
| `--ignore PKG` | Suppress a package entirely — hidden from report (repeatable) |
| `--known PKG` | Mark a finding as intentional — still shown, won't trigger `--exit-code` (repeatable) |
| `--ref main` | Git ref for remote repos (branch, tag, or commit SHA) |

### `check` — look up a single package

```bash
dep-audit check <package> [--ecosystem python] [--offline]
```

Shows the package classification, what it can be replaced with, and live data from deps.dev (deprecated status, open advisories). Use `--offline` to skip the network call.

### `db` — manage the junk database

```bash
dep-audit db list python          # List all entries grouped by type
dep-audit db list cargo           # List Cargo entries
dep-audit db show pytz            # Show entry for one package

# Discover new candidate entries from a project
dep-audit db export --discovered .
dep-audit db export --discovered fastapi/fastapi
```

### `cache` — manage the API cache

```bash
dep-audit cache clear             # Delete ~/.cache/dep-audit/
```

## Output formats

### Terminal (default)

Results are grouped into four sections, most actionable first:

```
=== dep-audit: my-app (Python 3.12) ===

REMOVE — unused dependencies (zero effort):

  six ············································ not imported anywhere in project
      just delete from dependency list

REPLACE — stdlib alternatives available:

  pytz ··········································· stdlib_backport → datetime.zoneinfo (since 3.9)
      2 imports in src/utils.py:5

SIMPLIFY — micro-utilities (inline replacements):

  is-odd ········································· micro_utility → x % 2 !== 0
      3 imports across 2 files

DEPRECATED:

  pycrypto ······································· deprecated → pycryptodome

SUMMARY
  4 unnecessary packages found
  18 total production dependencies scanned
  1 zero-effort removal
  1 stdlib replacement
  1 micro-utility to inline
  1 deprecated
```

### JSON

```bash
dep-audit scan . --format json | jq '.flagged[]'
```

Schema:

```json
{
  "project": "my-app",
  "ecosystem": "python",
  "target_version": "3.12",
  "scan_mode": "local",
  "scanned_at": "2026-03-07T12:00:00+00:00",
  "production_deps": 18,
  "flagged": [
    {
      "name": "pytz",
      "version": "2024.1",
      "classification": "stdlib_backport",
      "confidence": 0.95,
      "is_direct": true,
      "imports": 2,
      "replacement": "datetime.zoneinfo",
      "stdlib_since": "3.9",
      "files": [{"path": "src/utils.py", "line": 5}]
    }
  ],
  "summary": {
    "zero_effort_removals": 1,
    "stdlib_replacements": 1,
    "micro_utilities": 0,
    "deprecated": 0,
    "total_transitive_freed": 2
  }
}
```

### SARIF (GitHub Code Scanning)

```bash
dep-audit scan . --format sarif > dep-audit.sarif
```

SARIF 2.1.0 output for GitHub Code Scanning and any tool that consumes SARIF. Findings map to rule IDs:

| Rule | Classification | Default level |
|---|---|---|
| DEP001 | `stdlib_backport` | warning |
| DEP002 | `zombie_shim` | warning |
| DEP003 | `deprecated` | error |
| DEP004 | `micro_utility` | note |

Low-confidence findings (below 0.7) are downgraded to `note`.

## Configuration

dep-audit reads config from the first file it finds, in priority order:

1. **`.dep-audit.toml`** — standalone config, works for any ecosystem
2. **`pyproject.toml`** — `[tool.dep-audit]` section, Python projects only

CLI flags always override config values.

**`.dep-audit.toml`** (or `[tool.dep-audit]` in `pyproject.toml`):

```toml
ignore         = ["lodash", "uuid"]       # hide these packages from the report entirely
known          = ["typing-extensions"]    # show findings but don't fail --exit-code
target-version = "3.11"                   # language version for stdlib checks
ecosystem      = "python"                 # force a specific ecosystem
offline        = true                     # always skip deps.dev API
exit-code      = true                     # always use exit code mode
min-confidence = 0.8                      # only fail CI on findings >= this confidence
```

`target-version` is auto-detected from the project manifest:

| Ecosystem | Detected from | Example |
|---|---|---|
| Python | `requires-python` in `pyproject.toml` | `>=3.11` → `3.11` |
| Rust | `package.rust-version` in `Cargo.toml` | `1.70` |
| npm | `engines.node` in `package.json` | `>=18.0.0` → `18.0` |

If the field is absent, dep-audit falls back to a safe default (Python: running interpreter, Rust: 1.80, Node: 22).

### Inline ignores

Suppress a single package by adding a comment inline. Supported in `requirements.txt`:

```
requests==2.31.0
six==1.16.0  # dep-audit: ignore
```

## Suppressing findings

Three ways to stop a finding from blocking CI, each with different intent:

### `ignore` — hide completely

The package disappears from the report entirely. Use this for genuine false positives.

```toml
[tool.dep-audit]
ignore = ["typing-extensions"]  # needed for runtime type hints on 3.10
```

```bash
dep-audit scan . --ignore typing-extensions
```

### `known` — acknowledge, don't block

The package still appears in the report but won't cause `--exit-code` to return 1. Use this for deliberate decisions — packages you know are flagged and have chosen to keep ("won't fix").

```toml
[tool.dep-audit]
known = ["six"]  # legacy code, migration planned for Q3
```

```bash
dep-audit scan . --known six
```

A note appears in stderr when known findings are present:

```
  1 known finding(s) suppressed from --exit-code: six
```

### `--min-confidence` — raise the threshold

Only fail CI on findings above a confidence threshold. Useful during migrations where you want to enforce clear-cut findings (confidence 1.0) but tolerate uncertain ones.

```bash
dep-audit scan . --exit-code --min-confidence 0.9
```

## CI integration

### GitHub Actions

```yaml
name: dep-audit
on: [push, pull_request]

jobs:
  dep-audit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Scan dependencies
        run: uvx dep-audit scan . --exit-code --offline
```

### GitHub Actions with Code Scanning (SARIF)

Upload findings as inline annotations on pull requests:

```yaml
name: dep-audit
on: [push, pull_request]

jobs:
  dep-audit:
    runs-on: ubuntu-latest
    permissions:
      security-events: write
    steps:
      - uses: actions/checkout@v4
      - name: Scan dependencies
        run: uvx dep-audit scan . --format sarif --offline > dep-audit.sarif
      - name: Upload SARIF
        uses: github/codeql-action/upload-sarif@v3
        with:
          sarif_file: dep-audit.sarif
```

### GitLab CI

```yaml
dep-audit:
  image: python:3.12-slim
  script:
    - pip install dep-audit
    - dep-audit scan . --exit-code --offline
```

### Jenkins

```groovy
stage('dep-audit') {
    sh 'uvx dep-audit scan . --exit-code --offline'
}
```

### pre-commit

dep-audit is a [pre-commit](https://pre-commit.com/) plugin. Add it to `.pre-commit-config.yaml`:

```yaml
repos:
  - repo: https://github.com/zfoq/dep-audit
    rev: 0.4.2
    hooks:
      - id: dep-audit
```

The hook only runs when lockfiles or manifests change, so it doesn't slow down unrelated commits.

```bash
pre-commit install
pre-commit run dep-audit --all-files  # verify it works
```

To pass extra flags:

```yaml
    hooks:
      - id: dep-audit
        args: [scan, ., --exit-code, --offline, --include-dev]
```

## Offline vs online mode

By default dep-audit calls [deps.dev](https://deps.dev) to:

- **Resolve transitive dependencies** — when you only have `requirements.txt` or `pyproject.toml` (no lockfile), it queries deps.dev to discover what each direct dep pulls in transitively.
- **Detect live deprecations** — checks whether packages have been marked deprecated upstream, beyond what's in dep-audit's own database.

If your project has a full lockfile (`uv.lock`, `package-lock.json`, `Cargo.lock`), transitive deps are already in the file and the network resolution is skipped automatically. `--offline` only disables the live deprecation check.

Use `--offline` in CI/pre-commit for speed and determinism.

## Remote scanning

Scan any public GitHub repo without cloning it:

```bash
dep-audit scan fastapi/fastapi
dep-audit scan https://github.com/pallets/flask
dep-audit scan django/django --ref stable/5.1.x
dep-audit scan expressjs/express --ecosystem npm --format json
```

Import usage analysis is skipped for remote scans since source code is not downloaded. Transitive dependency chains are still traced.

## Cargo workspaces

For Cargo workspace repos, point dep-audit at a specific workspace member instead of the workspace root to get accurate direct-dependency attribution:

```bash
# Workspace root — scans all deps but can't tell which are direct for each crate
dep-audit scan .

# Workspace member — accurate results for that specific crate
dep-audit scan ./crates/my-crate
dep-audit scan ./tokio          # inside a tokio-style workspace
```

## Junk database

The database covers 121 packages across all ecosystems (Python: 43, npm: 57, Cargo: 21). Each entry is a TOML file in `src/dep_audit/db/{ecosystem}/`:

```toml
name        = "pytz"
ecosystem   = "python"
type        = "stdlib_backport"   # stdlib_backport | zombie_shim | deprecated | micro_utility
replacement = "datetime.zoneinfo"
stdlib_since = "3.9"
confidence  = 0.95
flags       = ["stdlib_backport: zoneinfo available since Python 3.9"]
validated   = 2026-01-15
```

### Contributing entries

Found a package that should be flagged?

```bash
# Preview auto-generated stubs from a project scan
dep-audit db export --discovered .
dep-audit db export --discovered fastapi/fastapi
```

Review the output, fill in the details, and open a PR with the new `.toml` file.

## Development

```bash
git clone https://github.com/zfoq/dep-audit
cd dep-audit
uv sync --group dev

# Run tests
uv run pytest

# Lint and type-check
uv run ruff check src/ tests/
uv run mypy src/

# Try it on itself
uv run dep-audit scan . --offline
```

## License

MIT
