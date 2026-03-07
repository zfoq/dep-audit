# dep-audit

A CLI tool that identifies unnecessary dependencies in software projects. It answers the question existing tools don't ask: *"which of your dependencies can you remove because the language itself now provides that functionality, or the package is deprecated, or you never actually import it?"*

## What it finds

| Category | Examples |
|---|---|
| **Stdlib backports** | `pytz` (use `zoneinfo`), `tomli` (use `tomllib`), `typing-extensions` on 3.12+ |
| **Zombie shims** | `six`, `future` — Python 2/3 compatibility layers with Python 2 dead since 2020 |
| **Deprecated packages** | `pycrypto` → `pycryptodome`, `nose` → `pytest`, `distutils` → `setuptools` |
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
dep-audit check lazy_static --ecosystem cargo
```

## Ecosystems

| Ecosystem | Detection | Lockfiles parsed |
|---|---|---|
| **Python** | `pyproject.toml`, `requirements.txt`, `setup.py` | uv.lock, poetry.lock, pyproject.toml, requirements.txt |
| **npm** | `package.json` | package-lock.json, yarn.lock, pnpm-lock.yaml, package.json |
| **Cargo** | `Cargo.toml` | Cargo.lock, Cargo.toml |

dep-audit detects the ecosystem automatically. In multi-language repos it will scan each detected ecosystem separately.

## Commands

### `scan` — scan a project

```bash
dep-audit scan [path] [options]
```

| Option | Description |
|---|---|
| `path` | Project root or `owner/repo` GitHub shorthand (default: `.`) |
| `--format terminal\|json` | Output format (default: `terminal`) |
| `--offline` | Skip deps.dev API calls (faster, no network needed) |
| `--target-version 3.11` | Override the language version for stdlib detection |
| `--ecosystem python` | Force a specific ecosystem instead of auto-detecting |
| `--include-dev` | Include dev/test dependencies in the scan |
| `--exit-code` | Exit with code 1 if any issues are found (for CI) |
| `--ref main` | Git ref for remote repos (branch, tag, or commit SHA) |

### `check` — look up a single package

```bash
dep-audit check <package> [--ecosystem python]
```

Shows the package classification, what it can be replaced with, and live data from deps.dev (deprecated status, open advisories).

### `db` — manage the junk database

```bash
dep-audit db list python          # List all entries grouped by type
dep-audit db list cargo           # List Cargo entries
dep-audit db show pytz            # Show TOML entry for one package

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

Results are grouped into prioritised sections:

```
  ── REMOVE ────────────────────────────────────────────────────────
  six  ·  zombie_shim  ·  confidence: 1.00
    Replace with: built-in 2/3 compatible Python

  ── REPLACE ───────────────────────────────────────────────────────
  pytz  ·  stdlib_backport  ·  confidence: 1.00
    Replace with: datetime.zoneinfo (stdlib since Python 3.9)

  ── SUMMARY ───────────────────────────────────────────────────────
  2 flagged  ·  0 transitive freed  ·  scanned 12 deps
```

### JSON

```bash
dep-audit scan . --format json | jq '.classifications[] | select(.classification != "ok")'
```

The JSON schema:

```json
{
  "project": "my-app",
  "ecosystem": "python",
  "target_version": "3.11",
  "classifications": [
    {
      "name": "pytz",
      "classification": "stdlib_backport",
      "confidence": 1.0,
      "replacement": "datetime.zoneinfo (3.9+)",
      "stdlib_since": "3.9",
      "is_direct": true,
      "flags": ["zoneinfo available since 3.9"]
    }
  ]
}
```

## Configuration

dep-audit reads config from the first file it finds, in priority order:

1. **`.dep-audit.toml`** — standalone config, works for any ecosystem (JavaScript, Rust, etc.)
2. **`pyproject.toml`** — `[tool.dep-audit]` section, Python projects only

CLI flags always override config values.

**`.dep-audit.toml`** (or `[tool.dep-audit]` in `pyproject.toml`):

```toml
ignore         = ["lodash", "uuid"]   # never flag these packages
target-version = "3.11"               # language version for stdlib checks
ecosystem      = "python"             # force a specific ecosystem
offline        = true                 # always skip deps.dev API
exit-code      = true                 # always use exit code mode
```

`target-version` is auto-detected from the project manifest for all ecosystems — Python from `requires-python`, Rust from `package.rust-version` in `Cargo.toml`, and npm from `engines.node` in `package.json`. Set it explicitly only when you need to override the detected value.

### Inline ignores

Suppress a single package in `requirements.txt` by adding a comment:

```
requests==2.31.0
six==1.16.0  # dep-audit: ignore
```

### CLI flag

Pass `--ignore` directly on the command line (can be repeated):

```bash
dep-audit scan . --ignore six --ignore pytz
```

This is the easiest option for pre-commit `args`:

```yaml
hooks:
  - id: dep-audit
    args: [scan, ., --exit-code, --offline, --ignore, lodash, --ignore, uuid]
```

## Offline vs online mode

By default dep-audit calls [deps.dev](https://deps.dev) to:

- **Resolve transitive dependencies** — when you only have `requirements.txt` or `pyproject.toml` (no lockfile), it queries deps.dev to discover what each direct dep pulls in transitively.
- **Detect live deprecations** — checks whether packages have been marked deprecated upstream, beyond what's in dep-audit's own junk database.

If your project has a full lockfile (`uv.lock`, `package-lock.json`, `Cargo.lock`), transitive deps are already known from the file and the network calls for resolution are skipped automatically. `--offline` only disables the live deprecation check on top.

Use `--offline` in CI/pre-commit for speed and determinism. Drop it when you want live deprecation data or when scanning projects that only have `requirements.txt`.

## CI integration

dep-audit auto-detects the target language version from the project manifest — no flag needed for most projects:

| Ecosystem | Detected from | Example |
|---|---|---|
| Python | `requires-python` in `pyproject.toml` | `>=3.11` → `3.11` |
| Rust | `package.rust-version` in `Cargo.toml` | `1.70` |
| npm | `engines.node` in `package.json` | `>=18.0.0` → `18.0` |

If the field is absent, dep-audit falls back to a conservative default (Python: running interpreter, Rust: 1.80, Node: 22). Override any of these with `--target-version` or `target-version` in `.dep-audit.toml`.

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

dep-audit is a [pre-commit](https://pre-commit.com/) plugin. Add it to `.pre-commit-config.yaml` and pre-commit handles installation automatically:

```yaml
repos:
  - repo: https://github.com/zfoq/dep-audit
    rev: 0.2.1  # git tag — run `pre-commit autoupdate` to get the latest
    hooks:
      - id: dep-audit
```

The hook only runs when lockfiles or manifests change, so it doesn't slow down unrelated commits.

```bash
pre-commit install
pre-commit run dep-audit --all-files  # verify it works
```

To pass extra flags (e.g. include dev dependencies):

```yaml
    hooks:
      - id: dep-audit
        args: [scan, ., --exit-code, --offline, --include-dev]
```

## Ignoring false positives

If dep-audit flags a package you intentionally keep, add it to the ignore list:

**pyproject.toml** (whole project):

```toml
[tool.dep-audit]
ignore = ["typing-extensions"]  # needed for runtime type hints on 3.10
```

**requirements.txt** (per-line):

```
typing-extensions>=4.0  # dep-audit: ignore
```

Both methods are equivalent — use whichever fits your workflow.

## Remote scanning

Scan any public GitHub repo without cloning it. dep-audit fetches only the lockfiles it needs.

```bash
# Shorthand
dep-audit scan fastapi/fastapi

# Full URL
dep-audit scan https://github.com/pallets/flask

# Specific branch or tag
dep-audit scan django/django --ref stable/5.1.x

# JSON output for scripting
dep-audit scan expressjs/express --ecosystem npm --format json
```

Import usage analysis is skipped for remote scans since source code is not downloaded. Transitive dependency chains are still traced.

## Junk database

The junk database lives in `src/dep_audit/db/{ecosystem}/` as TOML files. Each file describes one package:

```toml
name        = "pytz"
ecosystem   = "python"
type        = "stdlib_backport"   # stdlib_backport | zombie_shim | deprecated | micro_utility
replacement = "datetime.zoneinfo (3.9+)"
stdlib_since = "3.9"
confidence  = 1.0
flags       = ["zoneinfo available since 3.9", "pytz has quirky non-standard API"]
validated   = 2025-01-15
```

### Contributing entries

Found a package that should be flagged?

```bash
# Preview auto-generated stubs from a project
dep-audit db export --discovered .

# Or from a remote repo
dep-audit db export --discovered fastapi/fastapi
```

Copy the output, fill in the details, and open a PR with the new `.toml` file.

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
