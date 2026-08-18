# Moodle SQL Server → PostgreSQL Migration Tool — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `moodle-mssql2pg`, a config-driven CLI (packaged in Docker) that migrates a Moodle database from SQL Server to PostgreSQL from just two connection strings, without producing Moodle schema/XMLDB errors.

**Architecture:** A Python 3 CLI orchestrates a 6-step pipeline (`discover → generate → migrate → fix → verify → report`). It uses **pgloader** as the bulk-transfer engine but owns all Moodle-safety decisions (no foreign keys, Moodle-correct casts, schema-only "empty" tables for excluded logs, sequence/padding fixes, row-count + schema verification). All DB and subprocess access sits behind thin interfaces so the logic is unit-testable without live databases.

**Tech Stack:** Python 3.10+, `click` (CLI), `pyyaml`, `pymssql` (MSSQL via FreeTDS), `psycopg2-binary` (PostgreSQL), `pytest` (tests); pgloader + FreeTDS in a Docker image.

## Global Constraints

- **Python:** `>=3.10`. Use `from __future__ import annotations` is NOT needed (3.10 supports `X | None`).
- **Runtime deps (verbatim):** `click>=8.1`, `pyyaml>=6.0`, `pymssql>=2.2`, `psycopg2-binary>=2.9`. Dev: `pytest>=7`.
- **Package layout:** `src/` layout, console entry point `moodle-mssql2pg = moodle_mssql2pg.cli:main`.
- **Environment:** Docker (base image with pgloader + FreeTDS). User runs the tool themselves; docs must be self-sufficient.
- **Docs language:** README + runbook in **Vietnamese**.
- **Moodle-safe rules (must be encoded, verbatim):**
  - Target schema `public`, table prefix `mdl_`.
  - pgloader `WITH ... no foreign keys` (Moodle creates indexes only, never FK constraints).
  - Casts: `bit → smallint`, `tinyint → smallint` (NEVER `boolean`), `uniqueidentifier → text`, `xml → text`.
  - Excluded tables (`exclude_data_tables`) → created **empty** via pgloader `schema only` (keep structure, skip data) so Moodle never reports a missing table.
  - Non-standard MSSQL port passed via `TDSPORT` env var (FreeTDS ignores port in the connstring).
  - URL-encode user/password in pgloader connstrings (passwords contain `+`, `(`).
  - Post-migration `fix`: drop stray FK constraints, `rtrim` char/nchar columns, normalize `id` sequences, `VACUUM ANALYZE`.
  - Target DB must be UTF8; never write to the source.
- **Default excluded tables (verbatim list):** `mdl_logstore_standard_log`, `mdl_log`, `mdl_log_queries`, `mdl_task_log`, `mdl_sessions`, `mdl_cache_flags`, `mdl_cache_filters`, `mdl_context_temp`, `mdl_editor_atto_autosave`, `mdl_tiny_autosave`, `mdl_lock_db`, `mdl_events_queue`, `mdl_events_queue_handlers`, `mdl_tag_correlation`, `mdl_file_conversion`, `mdl_infected_files`, `mdl_portfolio_tempdata`, `mdl_hvp_tmpfiles`, `mdl_search_index_requests`.
- **TDD:** every logic task writes a failing test first. **Commit after every task.**

---

## File Structure

```
moodle-mssql2pg/
├── pyproject.toml              # package metadata + console script
├── requirements.txt            # runtime deps
├── requirements-dev.txt        # pytest
├── config.example.yml          # template the user copies to config.yml
├── Dockerfile                  # pgloader + FreeTDS + Python + package
├── docker-compose.yml          # mount config.yml + output/, one-command run
├── .gitignore
├── README.md                   # TIẾNG VIỆT: cấu hình, chạy, runbook hậu migrate
├── src/moodle_mssql2pg/
│   ├── __init__.py             # __version__
│   ├── config.py               # Config dataclasses, YAML load, connstring URL-encode
│   ├── discover.py             # MSSQL introspection + table classification → Discovered
│   ├── generate.py             # render pgloader .load files (data + schema-only)
│   ├── migrate.py              # run pgloader per file, TDSPORT, resume state
│   ├── fix.py                  # post-migration SQL (drop FK, rtrim, sequences, vacuum)
│   ├── verify.py               # row-count compare + optional schema check
│   ├── report.py               # build report.md + PASS/FAIL summary
│   └── cli.py                  # click commands: test, discover, generate, migrate, fix, verify, run
└── tests/
    ├── test_config.py
    ├── test_discover.py
    ├── test_generate.py
    ├── test_migrate.py
    ├── test_fix.py
    ├── test_verify.py
    ├── test_report.py
    └── test_cli.py
```

All tool files live under `moodle-mssql2pg/` at the repo root (`E:\ScriptConvertToPgSQL`). The existing shell scripts and `tables.txt` stay untouched as historical reference.

---

## Task 1: Project scaffolding + CLI skeleton

**Files:**
- Create: `moodle-mssql2pg/pyproject.toml`, `moodle-mssql2pg/requirements.txt`, `moodle-mssql2pg/requirements-dev.txt`, `moodle-mssql2pg/.gitignore`
- Create: `moodle-mssql2pg/src/moodle_mssql2pg/__init__.py`, `moodle-mssql2pg/src/moodle_mssql2pg/cli.py`
- Test: `moodle-mssql2pg/tests/test_cli.py`

**Interfaces:**
- Produces: `moodle_mssql2pg.__version__: str`; `cli.main` (a `click` group) with a `--version` flag that prints the version.

- [ ] **Step 1: Initialize git + directories**

```bash
cd /e/ScriptConvertToPgSQL
git init                       # folder is not yet a git repo
mkdir -p moodle-mssql2pg/src/moodle_mssql2pg moodle-mssql2pg/tests
```

- [ ] **Step 2: Create packaging files**

`moodle-mssql2pg/pyproject.toml`:
```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "moodle-mssql2pg"
version = "0.1.0"
requires-python = ">=3.10"
dependencies = [
  "click>=8.1",
  "pyyaml>=6.0",
]

# DB drivers are only needed at migration time (in Docker), not for unit tests.
# adapters.py imports them lazily, so the whole test suite runs without them.
[project.optional-dependencies]
drivers = [
  "pymssql>=2.2",
  "psycopg2-binary>=2.9",
]

[project.scripts]
moodle-mssql2pg = "moodle_mssql2pg.cli:main"

[tool.setuptools.packages.find]
where = ["src"]
```

`moodle-mssql2pg/requirements.txt`:
```
click>=8.1
pyyaml>=6.0
pymssql>=2.2
psycopg2-binary>=2.9
```

`moodle-mssql2pg/requirements-dev.txt` (drivers NOT needed — unit tests are infra-free):
```
pytest>=7
```

`moodle-mssql2pg/.gitignore`:
```
__pycache__/
*.pyc
.pytest_cache/
output/
config.yml
*.egg-info/
build/
dist/
```

- [ ] **Step 3: Write the failing test**

`moodle-mssql2pg/tests/test_cli.py`:
```python
from click.testing import CliRunner
from moodle_mssql2pg.cli import main
from moodle_mssql2pg import __version__


def test_version_flag_prints_version():
    result = CliRunner().invoke(main, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output
```

- [ ] **Step 4: Run test to verify it fails**

Run:
```bash
cd moodle-mssql2pg && pip install -e . && pip install -r requirements-dev.txt
python -m pytest tests/test_cli.py -v
```
Expected: FAIL (`ModuleNotFoundError: moodle_mssql2pg.cli` or missing `__version__`).

- [ ] **Step 5: Implement minimal package + CLI**

`moodle-mssql2pg/src/moodle_mssql2pg/__init__.py`:
```python
__version__ = "0.1.0"
```

`moodle-mssql2pg/src/moodle_mssql2pg/cli.py`:
```python
import click

from moodle_mssql2pg import __version__


@click.group()
@click.version_option(version=__version__, prog_name="moodle-mssql2pg")
def main() -> None:
    """Chuyển đổi database Moodle từ SQL Server sang PostgreSQL."""


if __name__ == "__main__":
    main()
```

- [ ] **Step 6: Run test to verify it passes**

Run: `python -m pytest tests/test_cli.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
cd /e/ScriptConvertToPgSQL
git add moodle-mssql2pg/ docs/
git commit -m "feat: scaffold moodle-mssql2pg package and CLI skeleton"
```

---

## Task 2: Config loading, validation, and connstring URL-encoding

**Files:**
- Create: `moodle-mssql2pg/src/moodle_mssql2pg/config.py`
- Test: `moodle-mssql2pg/tests/test_config.py`

**Interfaces:**
- Produces:
  - `DEFAULT_EXCLUDE_DATA_TABLES: list[str]`
  - `@dataclass DbConn(host: str, port: int, db: str, user: str, password: str, schema: str)`
  - `@dataclass Options(table_prefix, batch_size, large_table_threshold, work_mem, maintenance_work_mem, drop_target_tables, include_tables, exclude_data_tables, moodle_codebase_path, php_bin)`
  - `@dataclass Config(source: DbConn, target: DbConn, options: Options)`
  - `load_config(path: str) -> Config` (applies `MSSQL_PASSWORD` / `PGSQL_PASSWORD` env overrides)
  - `mssql_url(c: DbConn) -> str` → `mssql://<enc-user>:<enc-pass>@<host>/<db>` (no port; port goes to TDSPORT)
  - `pgsql_url(c: DbConn) -> str` → `postgresql://<enc-user>:<enc-pass>@<host>:<port>/<db>`

- [ ] **Step 1: Write the failing tests**

`moodle-mssql2pg/tests/test_config.py`:
```python
import os
import textwrap

import pytest

from moodle_mssql2pg.config import (
    DEFAULT_EXCLUDE_DATA_TABLES,
    load_config,
    mssql_url,
    pgsql_url,
)

CONFIG_YAML = textwrap.dedent(
    """
    source_mssql:
      host: 172.100.100.200
      port: 5968
      db: LMS_INS_TEST
      user: vnr
      password: "Pw+(Example123"
      schema: dbo
    target_pgsql:
      host: 172.100.100.13
      port: 5432
      db: ins_test_13
      user: admin
      password: "changeme_pg"
      schema: public
    options:
      batch_size: 30
    """
)


def _write(tmp_path, text):
    p = tmp_path / "config.yml"
    p.write_text(text, encoding="utf-8")
    return str(p)


def test_load_config_parses_connections_and_defaults(tmp_path):
    cfg = load_config(_write(tmp_path, CONFIG_YAML))
    assert cfg.source.host == "172.100.100.200"
    assert cfg.source.port == 5968
    assert cfg.target.schema == "public"
    # defaults come from Options
    assert cfg.options.batch_size == 30
    assert cfg.options.table_prefix == "mdl_"
    assert cfg.options.large_table_threshold == 5_000_000
    # default exclude list applied when not overridden
    assert "mdl_logstore_standard_log" in cfg.options.exclude_data_tables
    assert cfg.options.exclude_data_tables == DEFAULT_EXCLUDE_DATA_TABLES


def test_missing_required_field_raises(tmp_path):
    bad = CONFIG_YAML.replace("  host: 172.100.100.200\n", "")
    with pytest.raises(ValueError):
        load_config(_write(tmp_path, bad))


def test_env_password_override(tmp_path, monkeypatch):
    monkeypatch.setenv("MSSQL_PASSWORD", "from-env")
    cfg = load_config(_write(tmp_path, CONFIG_YAML))
    assert cfg.source.password == "from-env"


def test_mssql_url_urlencodes_and_omits_port(tmp_path):
    cfg = load_config(_write(tmp_path, CONFIG_YAML))
    url = mssql_url(cfg.source)
    # "+" -> %2B and "(" -> %28 ; host present, port NOT in URL
    assert url == "mssql://vnr:Pw%2B%28Example123@172.100.100.200/LMS_INS_TEST"
    assert ":5968" not in url


def test_pgsql_url_includes_port(tmp_path):
    cfg = load_config(_write(tmp_path, CONFIG_YAML))
    assert pgsql_url(cfg.target) == "postgresql://admin:changeme_pg@172.100.100.13:5432/ins_test_13"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_config.py -v`
Expected: FAIL (`ModuleNotFoundError: moodle_mssql2pg.config`).

- [ ] **Step 3: Implement `config.py`**

`moodle-mssql2pg/src/moodle_mssql2pg/config.py`:
```python
import os
from dataclasses import dataclass, field
from urllib.parse import quote

import yaml

DEFAULT_EXCLUDE_DATA_TABLES = [
    "mdl_logstore_standard_log",
    "mdl_log",
    "mdl_log_queries",
    "mdl_task_log",
    "mdl_sessions",
    "mdl_cache_flags",
    "mdl_cache_filters",
    "mdl_context_temp",
    "mdl_editor_atto_autosave",
    "mdl_tiny_autosave",
    "mdl_lock_db",
    "mdl_events_queue",
    "mdl_events_queue_handlers",
    "mdl_tag_correlation",
    "mdl_file_conversion",
    "mdl_infected_files",
    "mdl_portfolio_tempdata",
    "mdl_hvp_tmpfiles",
    "mdl_search_index_requests",
]

_REQUIRED_CONN = ("host", "port", "db", "user", "password")


@dataclass
class DbConn:
    host: str
    port: int
    db: str
    user: str
    password: str
    schema: str


@dataclass
class Options:
    table_prefix: str = "mdl_"
    batch_size: int = 30
    large_table_threshold: int = 5_000_000
    work_mem: str = "1GB"
    maintenance_work_mem: str = "2GB"
    drop_target_tables: bool = False
    include_tables: list[str] = field(default_factory=list)
    exclude_data_tables: list[str] = field(
        default_factory=lambda: list(DEFAULT_EXCLUDE_DATA_TABLES)
    )
    moodle_codebase_path: str | None = None
    php_bin: str = "php"


@dataclass
class Config:
    source: DbConn
    target: DbConn
    options: Options


def _conn(raw: dict, default_schema: str) -> DbConn:
    for key in _REQUIRED_CONN:
        if raw.get(key) in (None, ""):
            raise ValueError(f"Thiếu trường bắt buộc trong connection: '{key}'")
    return DbConn(
        host=str(raw["host"]),
        port=int(raw["port"]),
        db=str(raw["db"]),
        user=str(raw["user"]),
        password=str(raw["password"]),
        schema=str(raw.get("schema", default_schema)),
    )


def load_config(path: str) -> Config:
    with open(path, encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}

    if "source_mssql" not in raw or "target_pgsql" not in raw:
        raise ValueError("config.yml phải có 'source_mssql' và 'target_pgsql'")

    source = _conn(raw["source_mssql"], "dbo")
    target = _conn(raw["target_pgsql"], "public")

    opts_raw = raw.get("options") or {}
    options = Options(
        **{k: v for k, v in opts_raw.items() if k in Options.__dataclass_fields__}
    )

    # env overrides for secrets
    if os.getenv("MSSQL_PASSWORD"):
        source.password = os.environ["MSSQL_PASSWORD"]
    if os.getenv("PGSQL_PASSWORD"):
        target.password = os.environ["PGSQL_PASSWORD"]

    return Config(source=source, target=target, options=options)


def mssql_url(c: DbConn) -> str:
    # FreeTDS ignores port in the URL; migrate.py exports TDSPORT instead.
    return f"mssql://{quote(c.user, safe='')}:{quote(c.password, safe='')}@{c.host}/{c.db}"


def pgsql_url(c: DbConn) -> str:
    return (
        f"postgresql://{quote(c.user, safe='')}:{quote(c.password, safe='')}"
        f"@{c.host}:{c.port}/{c.db}"
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_config.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add moodle-mssql2pg/src/moodle_mssql2pg/config.py moodle-mssql2pg/tests/test_config.py
git commit -m "feat: config loading, validation, and Moodle-safe connstring encoding"
```

---

## Task 3: Discover — MSSQL introspection + table classification

**Files:**
- Create: `moodle-mssql2pg/src/moodle_mssql2pg/discover.py`
- Test: `moodle-mssql2pg/tests/test_discover.py`

**Interfaces:**
- Consumes: `Config`, `Options` from `config.py`.
- Produces:
  - `@dataclass Discovered(data_tables: list[str], schema_only_tables: list[str], large_tables: list[str], char_columns: dict[str, list[str]], row_counts: dict[str, int])`
  - `class MssqlClient(Protocol)` with `fetch_tables(prefix) -> list[str]`, `fetch_char_columns(prefix) -> list[tuple[str, str]]`, `fetch_row_counts(prefix) -> dict[str, int]`
  - `classify(tables: list[str], row_counts: dict[str, int], char_columns: list[tuple[str, str]], options: Options) -> Discovered`
  - `discover(client: MssqlClient, options: Options) -> Discovered`
  - `save_discovered(d: Discovered, path: str) -> None`, `load_discovered(path: str) -> Discovered`
  - SQL constants: `SQL_TABLES`, `SQL_CHAR_COLUMNS`, `SQL_ROW_COUNTS`

Classification rules: `data_tables` = discovered tables minus `exclude_data_tables`; `schema_only_tables` = discovered tables ∩ `exclude_data_tables`; if `include_tables` non-empty, restrict discovered set to that intersection first. `large_tables` = data tables whose row count ≥ `large_table_threshold`. `char_columns` only kept for data tables (no point trimming empty tables).

- [ ] **Step 1: Write the failing tests**

`moodle-mssql2pg/tests/test_discover.py`:
```python
import json

from moodle_mssql2pg.config import Options
from moodle_mssql2pg.discover import (
    Discovered,
    classify,
    discover,
    load_discovered,
    save_discovered,
)


class FakeClient:
    def __init__(self, tables, char_cols, counts):
        self._tables, self._char, self._counts = tables, char_cols, counts

    def fetch_tables(self, prefix):
        return [t for t in self._tables if t.startswith(prefix)]

    def fetch_char_columns(self, prefix):
        return self._char

    def fetch_row_counts(self, prefix):
        return self._counts


def _opts(**kw):
    return Options(exclude_data_tables=["mdl_log"], large_table_threshold=1000, **kw)


def test_classify_splits_excluded_and_large():
    tables = ["mdl_user", "mdl_log", "mdl_question_attempts"]
    counts = {"mdl_user": 500, "mdl_log": 9, "mdl_question_attempts": 5000}
    char_cols = [("mdl_user", "username"), ("mdl_log", "action")]
    d = classify(tables, counts, char_cols, _opts())

    assert d.data_tables == ["mdl_question_attempts", "mdl_user"]  # sorted, log excluded
    assert d.schema_only_tables == ["mdl_log"]
    assert d.large_tables == ["mdl_question_attempts"]  # 5000 >= 1000
    # char columns only for data tables
    assert d.char_columns == {"mdl_user": ["username"]}


def test_include_tables_restricts_set():
    tables = ["mdl_user", "mdl_course", "mdl_log"]
    counts = {"mdl_user": 1, "mdl_course": 1, "mdl_log": 1}
    d = classify(tables, counts, [], _opts(include_tables=["mdl_user"]))
    assert d.data_tables == ["mdl_user"]
    assert d.schema_only_tables == []


def test_discover_uses_client_and_prefix():
    client = FakeClient(
        tables=["mdl_user", "other_table"],
        char_cols=[("mdl_user", "username")],
        counts={"mdl_user": 3},
    )
    d = discover(client, Options(exclude_data_tables=[]))
    assert d.data_tables == ["mdl_user"]  # non-mdl_ filtered out by prefix


def test_save_and_load_roundtrip(tmp_path):
    d = Discovered(
        data_tables=["mdl_user"],
        schema_only_tables=["mdl_log"],
        large_tables=[],
        char_columns={"mdl_user": ["username"]},
        row_counts={"mdl_user": 3, "mdl_log": 9},
    )
    path = str(tmp_path / "discovered.json")
    save_discovered(d, path)
    assert load_discovered(path) == d
    # file is valid JSON
    json.loads((tmp_path / "discovered.json").read_text())
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_discover.py -v`
Expected: FAIL (`ModuleNotFoundError: moodle_mssql2pg.discover`).

- [ ] **Step 3: Implement `discover.py`**

`moodle-mssql2pg/src/moodle_mssql2pg/discover.py`:
```python
import json
from dataclasses import asdict, dataclass
from typing import Protocol

from moodle_mssql2pg.config import Options

SQL_TABLES = (
    "SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES "
    "WHERE TABLE_TYPE = 'BASE TABLE' AND TABLE_NAME LIKE %s ORDER BY TABLE_NAME"
)
SQL_CHAR_COLUMNS = (
    "SELECT TABLE_NAME, COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
    "WHERE DATA_TYPE IN ('char', 'nchar') AND TABLE_NAME LIKE %s "
    "ORDER BY TABLE_NAME, ORDINAL_POSITION"
)
# Fast row counts from partition stats (avoids full COUNT(*) on huge tables).
SQL_ROW_COUNTS = (
    "SELECT t.name AS table_name, SUM(p.rows) AS n "
    "FROM sys.tables t "
    "JOIN sys.partitions p ON p.object_id = t.object_id AND p.index_id IN (0, 1) "
    "WHERE t.name LIKE %s GROUP BY t.name"
)


class MssqlClient(Protocol):
    def fetch_tables(self, prefix: str) -> list[str]: ...
    def fetch_char_columns(self, prefix: str) -> list[tuple[str, str]]: ...
    def fetch_row_counts(self, prefix: str) -> dict[str, int]: ...


@dataclass
class Discovered:
    data_tables: list[str]
    schema_only_tables: list[str]
    large_tables: list[str]
    char_columns: dict[str, list[str]]
    row_counts: dict[str, int]


def classify(
    tables: list[str],
    row_counts: dict[str, int],
    char_columns: list[tuple[str, str]],
    options: Options,
) -> Discovered:
    table_set = set(tables)
    if options.include_tables:
        table_set &= set(options.include_tables)

    exclude = set(options.exclude_data_tables)
    data_tables = sorted(t for t in table_set if t not in exclude)
    schema_only_tables = sorted(t for t in table_set if t in exclude)

    large_tables = sorted(
        t for t in data_tables if row_counts.get(t, 0) >= options.large_table_threshold
    )

    data_set = set(data_tables)
    char_map: dict[str, list[str]] = {}
    for table, column in char_columns:
        if table in data_set:
            char_map.setdefault(table, []).append(column)

    return Discovered(
        data_tables=data_tables,
        schema_only_tables=schema_only_tables,
        large_tables=large_tables,
        char_columns=char_map,
        row_counts={t: row_counts.get(t, 0) for t in table_set},
    )


def discover(client: MssqlClient, options: Options) -> Discovered:
    prefix = options.table_prefix
    tables = client.fetch_tables(prefix)
    char_columns = client.fetch_char_columns(prefix)
    row_counts = client.fetch_row_counts(prefix)
    return classify(tables, row_counts, char_columns, options)


def save_discovered(d: Discovered, path: str) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(asdict(d), fh, ensure_ascii=False, indent=2)


def load_discovered(path: str) -> Discovered:
    with open(path, encoding="utf-8") as fh:
        return Discovered(**json.load(fh))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_discover.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add moodle-mssql2pg/src/moodle_mssql2pg/discover.py moodle-mssql2pg/tests/test_discover.py
git commit -m "feat: MSSQL discovery and Moodle-aware table classification"
```

---

## Task 4: Generate — render pgloader `.load` files

**Files:**
- Create: `moodle-mssql2pg/src/moodle_mssql2pg/generate.py`
- Test: `moodle-mssql2pg/tests/test_generate.py`

**Interfaces:**
- Consumes: `Config`, `mssql_url`, `pgsql_url` (config.py); `Discovered` (discover.py).
- Produces:
  - `@dataclass LoadFile(filename: str, kind: str, tables: list[str], content: str)` — `kind` ∈ `{"schema_only", "data", "large"}`
  - `CAST_BLOCK: str`
  - `render_load(config: Config, tables: list[str], mode: str) -> str` — `mode` ∈ `{"data", "schema_only"}`
  - `chunked(items: list[str], size: int) -> list[list[str]]`
  - `plan_load_files(config: Config, disc: Discovered) -> list[LoadFile]`
  - `write_load_files(load_files: list[LoadFile], out_dir: str) -> list[str]` (returns written paths)

- [ ] **Step 1: Write the failing tests**

`moodle-mssql2pg/tests/test_generate.py`:
```python
import textwrap

from moodle_mssql2pg.config import load_config
from moodle_mssql2pg.discover import Discovered
from moodle_mssql2pg.generate import (
    chunked,
    plan_load_files,
    render_load,
    write_load_files,
)

CONFIG_YAML = textwrap.dedent(
    """
    source_mssql:
      host: h1
      port: 5968
      db: SRC
      user: vnr
      password: "p+("
      schema: dbo
    target_pgsql:
      host: h2
      port: 5432
      db: DST
      user: admin
      password: pw
      schema: public
    options:
      batch_size: 2
      exclude_data_tables: [mdl_log]
    """
)


def _cfg(tmp_path):
    p = tmp_path / "config.yml"
    p.write_text(CONFIG_YAML, encoding="utf-8")
    return load_config(str(p))


def test_chunked():
    assert chunked(["a", "b", "c"], 2) == [["a", "b"], ["c"]]


def test_render_data_load_is_moodle_safe(tmp_path):
    cfg = _cfg(tmp_path)
    out = render_load(cfg, ["mdl_user", "mdl_course"], "data")
    assert "no foreign keys" in out
    assert "reset sequences" in out
    assert "schema only" not in out
    assert "type bit to smallint" in out
    assert "type tinyint to smallint" in out
    assert "boolean" not in out
    assert "ALTER SCHEMA 'dbo' RENAME TO 'public'" in out
    assert "INCLUDING ONLY TABLE NAMES LIKE 'mdl_user', 'mdl_course' IN SCHEMA 'dbo'" in out
    # credentials URL-encoded (p+( -> p%2B%28)
    assert "mssql://vnr:p%2B%28@h1/SRC" in out
    assert ":5968" not in out


def test_render_schema_only_load(tmp_path):
    cfg = _cfg(tmp_path)
    out = render_load(cfg, ["mdl_log"], "schema_only")
    assert "schema only" in out
    assert "reset sequences" not in out


def test_plan_load_files_orders_schema_data_large(tmp_path):
    cfg = _cfg(tmp_path)
    disc = Discovered(
        data_tables=["mdl_a", "mdl_b", "mdl_c", "mdl_big"],
        schema_only_tables=["mdl_log"],
        large_tables=["mdl_big"],
        char_columns={},
        row_counts={},
    )
    files = plan_load_files(cfg, disc)
    kinds = [f.kind for f in files]
    # one schema-only file, batches of 2 for the 3 normal tables, one per large table
    assert kinds[0] == "schema_only"
    assert "large" in kinds
    # normal (non-large) data tables are batched by size=2 -> tables a,b,c => 2 files
    data_files = [f for f in files if f.kind == "data"]
    assert [f.tables for f in data_files] == [["mdl_a", "mdl_b"], ["mdl_c"]]
    large_files = [f for f in files if f.kind == "large"]
    assert large_files[0].tables == ["mdl_big"]


def test_write_load_files(tmp_path):
    cfg = _cfg(tmp_path)
    disc = Discovered(["mdl_a"], ["mdl_log"], [], {}, {})
    files = plan_load_files(cfg, disc)
    out_dir = tmp_path / "out"
    paths = write_load_files(files, str(out_dir))
    assert all((out_dir / p.split("/")[-1]).exists() for p in paths)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_generate.py -v`
Expected: FAIL (`ModuleNotFoundError: moodle_mssql2pg.generate`).

- [ ] **Step 3: Implement `generate.py`**

`moodle-mssql2pg/src/moodle_mssql2pg/generate.py`:
```python
import os
from dataclasses import dataclass

from moodle_mssql2pg.config import Config, mssql_url, pgsql_url
from moodle_mssql2pg.discover import Discovered

CAST_BLOCK = (
    "CAST type bit to smallint drop typemod,\n"
    "     type tinyint to smallint drop typemod,\n"
    "     type uniqueidentifier to text,\n"
    "     type xml to text"
)


@dataclass
class LoadFile:
    filename: str
    kind: str  # "schema_only" | "data" | "large"
    tables: list[str]
    content: str


def chunked(items: list[str], size: int) -> list[list[str]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def render_load(config: Config, tables: list[str], mode: str) -> str:
    opts = ["create tables", "create indexes"]
    if mode == "data":
        opts.append("reset sequences")
    opts.append("no foreign keys")
    if mode == "schema_only":
        opts.append("schema only")
    if config.options.drop_target_tables:
        opts.append("include drop")
    with_clause = ",\n     ".join(opts)

    src_schema = config.source.schema
    tgt_schema = config.target.schema
    names = ", ".join(f"'{t}'" for t in tables)

    return (
        "LOAD DATABASE\n"
        f"     FROM {mssql_url(config.source)}\n"
        f"     INTO {pgsql_url(config.target)}\n\n"
        f"WITH {with_clause}\n\n"
        f"SET work_mem to '{config.options.work_mem}', "
        f"maintenance_work_mem to '{config.options.maintenance_work_mem}'\n\n"
        f"{CAST_BLOCK}\n\n"
        f"ALTER SCHEMA '{src_schema}' RENAME TO '{tgt_schema}'\n\n"
        f"INCLUDING ONLY TABLE NAMES LIKE {names} IN SCHEMA '{src_schema}';\n"
    )


def plan_load_files(config: Config, disc: Discovered) -> list[LoadFile]:
    files: list[LoadFile] = []

    if disc.schema_only_tables:
        files.append(
            LoadFile(
                filename="batch_schema_only.load",
                kind="schema_only",
                tables=list(disc.schema_only_tables),
                content=render_load(config, disc.schema_only_tables, "schema_only"),
            )
        )

    large = set(disc.large_tables)
    normal = [t for t in disc.data_tables if t not in large]
    for i, batch in enumerate(chunked(normal, config.options.batch_size), start=1):
        files.append(
            LoadFile(
                filename=f"batch_{i}.load",
                kind="data",
                tables=batch,
                content=render_load(config, batch, "data"),
            )
        )

    for table in disc.large_tables:
        files.append(
            LoadFile(
                filename=f"batch_{table}.load",
                kind="large",
                tables=[table],
                content=render_load(config, [table], "data"),
            )
        )

    return files


def write_load_files(load_files: list[LoadFile], out_dir: str) -> list[str]:
    os.makedirs(out_dir, exist_ok=True)
    paths: list[str] = []
    for lf in load_files:
        path = os.path.join(out_dir, lf.filename)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(lf.content)
        paths.append(path)
    return paths
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_generate.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add moodle-mssql2pg/src/moodle_mssql2pg/generate.py moodle-mssql2pg/tests/test_generate.py
git commit -m "feat: render Moodle-safe pgloader .load files (data + schema-only)"
```

---

## Task 5: Migrate — run pgloader per file with TDSPORT and resume

**Files:**
- Create: `moodle-mssql2pg/src/moodle_mssql2pg/migrate.py`
- Test: `moodle-mssql2pg/tests/test_migrate.py`

**Interfaces:**
- Consumes: `LoadFile` (generate.py).
- Produces:
  - `class PgloaderRunner(Protocol)` with `run(load_path: str, env: dict[str, str], log_path: str) -> int`
  - `class State(path: str)` with `.is_done(name) -> bool`, `.mark(name) -> None`
  - `order_load_files(load_files: list[LoadFile]) -> list[LoadFile]` (schema_only → data → large)
  - `class MigrateError(Exception)` (attr `.filename`)
  - `migrate(load_files, runner, tdsport, out_dir, state=None) -> list[str]` (returns filenames run this call)

- [ ] **Step 1: Write the failing tests**

`moodle-mssql2pg/tests/test_migrate.py`:
```python
import pytest

from moodle_mssql2pg.generate import LoadFile
from moodle_mssql2pg.migrate import (
    MigrateError,
    State,
    migrate,
    order_load_files,
)


def _lf(name, kind):
    return LoadFile(filename=name, kind=kind, tables=[], content="")


def test_order_is_schema_then_data_then_large():
    files = [_lf("big.load", "large"), _lf("b1.load", "data"), _lf("s.load", "schema_only")]
    assert [f.filename for f in order_load_files(files)] == ["s.load", "b1.load", "big.load"]


class RecordingRunner:
    def __init__(self, fail_on=None):
        self.calls = []
        self.fail_on = fail_on

    def run(self, load_path, env, log_path):
        self.calls.append((load_path, env.get("TDSPORT")))
        return 1 if self.fail_on and self.fail_on in load_path else 0


def test_migrate_sets_tdsport_and_runs_in_order(tmp_path):
    files = [_lf("batch_1.load", "data"), _lf("batch_schema_only.load", "schema_only")]
    runner = RecordingRunner()
    ran = migrate(files, runner, tdsport=5968, out_dir=str(tmp_path))
    assert ran == ["batch_schema_only.load", "batch_1.load"]
    assert all(port == "5968" for _, port in runner.calls)


def test_migrate_resumes_and_skips_completed(tmp_path):
    files = [_lf("batch_1.load", "data"), _lf("batch_2.load", "data")]
    state = State(str(tmp_path / "state.json"))
    state.mark("batch_1.load")
    runner = RecordingRunner()
    ran = migrate(files, runner, tdsport=5968, out_dir=str(tmp_path), state=state)
    assert ran == ["batch_2.load"]


def test_migrate_raises_on_failure(tmp_path):
    files = [_lf("batch_1.load", "data")]
    runner = RecordingRunner(fail_on="batch_1")
    with pytest.raises(MigrateError) as exc:
        migrate(files, runner, tdsport=5968, out_dir=str(tmp_path))
    assert exc.value.filename == "batch_1.load"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_migrate.py -v`
Expected: FAIL (`ModuleNotFoundError: moodle_mssql2pg.migrate`).

- [ ] **Step 3: Implement `migrate.py`**

`moodle-mssql2pg/src/moodle_mssql2pg/migrate.py`:
```python
import json
import os
import subprocess
from typing import Protocol

from moodle_mssql2pg.generate import LoadFile

_ORDER = {"schema_only": 0, "data": 1, "large": 2}


class PgloaderRunner(Protocol):
    def run(self, load_path: str, env: dict[str, str], log_path: str) -> int: ...


class MigrateError(Exception):
    def __init__(self, filename: str):
        super().__init__(f"pgloader thất bại ở file: {filename}")
        self.filename = filename


class State:
    def __init__(self, path: str):
        self.path = path
        self.done: set[str] = set()
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                self.done = set(json.load(fh))

    def is_done(self, name: str) -> bool:
        return name in self.done

    def mark(self, name: str) -> None:
        self.done.add(name)
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump(sorted(self.done), fh)


def order_load_files(load_files: list[LoadFile]) -> list[LoadFile]:
    return sorted(load_files, key=lambda lf: _ORDER[lf.kind])


class SubprocessPgloaderRunner:
    """Real runner: invokes the pgloader binary."""

    def __init__(self, pgloader_bin: str = "pgloader"):
        self.pgloader_bin = pgloader_bin

    def run(self, load_path: str, env: dict[str, str], log_path: str) -> int:
        with open(log_path, "w", encoding="utf-8") as log:
            proc = subprocess.run(
                [self.pgloader_bin, load_path],
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
        return proc.returncode


def migrate(
    load_files: list[LoadFile],
    runner: PgloaderRunner,
    tdsport: int,
    out_dir: str,
    state: State | None = None,
) -> list[str]:
    os.makedirs(out_dir, exist_ok=True)
    env = dict(os.environ)
    env["TDSPORT"] = str(tdsport)

    ran: list[str] = []
    for lf in order_load_files(load_files):
        if state and state.is_done(lf.filename):
            continue
        log_path = os.path.join(out_dir, f"{lf.filename}.log")
        code = runner.run(os.path.join(out_dir, lf.filename), env, log_path)
        if code != 0:
            raise MigrateError(lf.filename)
        if state:
            state.mark(lf.filename)
        ran.append(lf.filename)
    return ran
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_migrate.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add moodle-mssql2pg/src/moodle_mssql2pg/migrate.py moodle-mssql2pg/tests/test_migrate.py
git commit -m "feat: pgloader runner with TDSPORT injection and resumable state"
```

---

## Task 6: Fix — post-migration Moodle-correctness SQL

**Files:**
- Create: `moodle-mssql2pg/src/moodle_mssql2pg/fix.py`
- Test: `moodle-mssql2pg/tests/test_fix.py`

**Interfaces:**
- Consumes: `Config` (for target schema), `Discovered` (char columns).
- Produces:
  - `class PgClient(Protocol)` with `execute(sql: str) -> None`, `fetch_values(sql: str) -> list[str]`
  - `SQL_LIST_FKS: str`, `SQL_TABLES_WITH_ID: str`
  - `drop_fk_statements(schema: str, fk_rows: list[tuple[str, str]]) -> list[str]`  (rows = (table, constraint))
  - `trim_char_statements(schema: str, char_columns: dict[str, list[str]]) -> list[str]`
  - `fix_sequence_statement(schema: str, table: str) -> str`
  - `vacuum_analyze_statement() -> str`
  - `run_fix(config: Config, disc: Discovered, client: PgClient) -> None`

- [ ] **Step 1: Write the failing tests**

`moodle-mssql2pg/tests/test_fix.py`:
```python
from moodle_mssql2pg.fix import (
    drop_fk_statements,
    fix_sequence_statement,
    trim_char_statements,
    vacuum_analyze_statement,
)


def test_drop_fk_statements():
    stmts = drop_fk_statements("public", [("mdl_user", "fk_user_ctx")])
    assert stmts == [
        'ALTER TABLE "public"."mdl_user" DROP CONSTRAINT IF EXISTS "fk_user_ctx";'
    ]


def test_trim_char_statements_one_per_column():
    stmts = trim_char_statements("public", {"mdl_user": ["country", "lang"]})
    assert stmts == [
        'UPDATE "public"."mdl_user" SET "country" = rtrim("country") '
        'WHERE "country" <> rtrim("country");',
        'UPDATE "public"."mdl_user" SET "lang" = rtrim("lang") '
        'WHERE "lang" <> rtrim("lang");',
    ]


def test_fix_sequence_statement_mentions_setval_and_table():
    stmt = fix_sequence_statement("public", "mdl_user")
    assert "setval" in stmt
    assert "mdl_user" in stmt
    assert "pg_get_serial_sequence" in stmt


def test_vacuum_analyze():
    assert vacuum_analyze_statement() == "VACUUM ANALYZE;"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_fix.py -v`
Expected: FAIL (`ModuleNotFoundError: moodle_mssql2pg.fix`).

- [ ] **Step 3: Implement `fix.py`**

`moodle-mssql2pg/src/moodle_mssql2pg/fix.py`:
```python
from typing import Protocol

from moodle_mssql2pg.config import Config
from moodle_mssql2pg.discover import Discovered

SQL_LIST_FKS = (
    "SELECT tc.table_name, tc.constraint_name "
    "FROM information_schema.table_constraints tc "
    "WHERE tc.constraint_type = 'FOREIGN KEY' AND tc.table_schema = %s"
)
SQL_TABLES_WITH_ID = (
    "SELECT table_name FROM information_schema.columns "
    "WHERE table_schema = %s AND column_name = 'id' ORDER BY table_name"
)


class PgClient(Protocol):
    def execute(self, sql: str) -> None: ...
    def fetch_values(self, sql: str) -> list[str]: ...


def _q(ident: str) -> str:
    return '"' + ident.replace('"', '""') + '"'


def drop_fk_statements(schema: str, fk_rows: list[tuple[str, str]]) -> list[str]:
    return [
        f"ALTER TABLE {_q(schema)}.{_q(table)} "
        f"DROP CONSTRAINT IF EXISTS {_q(constraint)};"
        for table, constraint in fk_rows
    ]


def trim_char_statements(schema: str, char_columns: dict[str, list[str]]) -> list[str]:
    stmts: list[str] = []
    for table in sorted(char_columns):
        for column in char_columns[table]:
            col = _q(column)
            stmts.append(
                f"UPDATE {_q(schema)}.{_q(table)} SET {col} = rtrim({col}) "
                f"WHERE {col} <> rtrim({col});"
            )
    return stmts


def fix_sequence_statement(schema: str, table: str) -> str:
    # Idempotent: reuse pgloader's sequence if present, else create one; then setval.
    return (
        "DO $$\n"
        "DECLARE seqname text;\n"
        "BEGIN\n"
        f"  seqname := pg_get_serial_sequence('{schema}.{table}', 'id');\n"
        "  IF seqname IS NULL THEN\n"
        f"    EXECUTE format('CREATE SEQUENCE IF NOT EXISTS %I.%I', '{schema}', '{table}_id_seq');\n"
        f"    EXECUTE format('ALTER TABLE %I.%I ALTER COLUMN id SET DEFAULT nextval(%L)', "
        f"'{schema}', '{table}', '{schema}.{table}_id_seq');\n"
        f"    EXECUTE format('ALTER SEQUENCE %I.%I OWNED BY %I.%I.id', "
        f"'{schema}', '{table}_id_seq', '{schema}', '{table}');\n"
        f"    seqname := '{schema}.{table}_id_seq';\n"
        "  END IF;\n"
        f"  PERFORM setval(seqname, COALESCE((SELECT max(id) FROM {schema}.{table}), 0) + 1, false);\n"
        "END $$;"
    )


def vacuum_analyze_statement() -> str:
    return "VACUUM ANALYZE;"


def run_fix(config: Config, disc: Discovered, client: PgClient) -> None:
    schema = config.target.schema

    # 1. Drop any stray FK constraints (Moodle uses indexes only).
    fk_rows = [tuple(r.split("\t")) for r in client.fetch_values(SQL_LIST_FKS % f"'{schema}'")]
    for stmt in drop_fk_statements(schema, fk_rows):  # type: ignore[arg-type]
        client.execute(stmt)

    # 2. Trim char/nchar padding (only on data tables).
    for stmt in trim_char_statements(schema, disc.char_columns):
        client.execute(stmt)

    # 3. Normalise id sequences for every table that has an id column.
    for table in client.fetch_values(SQL_TABLES_WITH_ID % f"'{schema}'"):
        client.execute(fix_sequence_statement(schema, table))

    # 4. Planner stats.
    client.execute(vacuum_analyze_statement())
```

> Note: `run_fix` is exercised end-to-end by the CLI integration; its unit-tested parts are the pure statement generators above. The concrete `PgClient` (psycopg2) is implemented in Task 9.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_fix.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add moodle-mssql2pg/src/moodle_mssql2pg/fix.py moodle-mssql2pg/tests/test_fix.py
git commit -m "feat: post-migration fix SQL (drop FK, trim char, fix sequences, vacuum)"
```

---

## Task 7: Verify — row-count comparison + schema-check hook

**Files:**
- Create: `moodle-mssql2pg/src/moodle_mssql2pg/verify.py`
- Test: `moodle-mssql2pg/tests/test_verify.py`

**Interfaces:**
- Produces:
  - `@dataclass TableVerdict(table: str, src_count: int, dst_count: int, status: str)` — status ∈ `{"ok", "ok_excluded", "excluded_not_empty", "mismatch", "missing"}`
  - `compare_counts(src: dict[str, int], dst: dict[str, int], schema_only: set[str]) -> list[TableVerdict]`
  - `verdicts_passed(verdicts: list[TableVerdict]) -> bool` (fail on `missing`/`mismatch`)
  - `schema_check_command(codebase_path: str, php_bin: str) -> list[str]`

- [ ] **Step 1: Write the failing tests**

`moodle-mssql2pg/tests/test_verify.py`:
```python
from moodle_mssql2pg.verify import (
    compare_counts,
    schema_check_command,
    verdicts_passed,
)


def test_compare_counts_statuses():
    src = {"mdl_user": 10, "mdl_course": 5, "mdl_log": 999, "mdl_gone": 3}
    dst = {"mdl_user": 10, "mdl_course": 4, "mdl_log": 0}
    verdicts = {v.table: v.status for v in compare_counts(src, dst, {"mdl_log"})}
    assert verdicts["mdl_user"] == "ok"
    assert verdicts["mdl_course"] == "mismatch"
    assert verdicts["mdl_log"] == "ok_excluded"   # excluded and empty
    assert verdicts["mdl_gone"] == "missing"       # in src, absent in dst


def test_excluded_but_not_empty_flagged():
    verdicts = compare_counts({"mdl_log": 5}, {"mdl_log": 5}, {"mdl_log"})
    assert verdicts[0].status == "excluded_not_empty"


def test_verdicts_passed():
    ok = compare_counts({"a": 1}, {"a": 1}, set())
    bad = compare_counts({"a": 1}, {"a": 2}, set())
    assert verdicts_passed(ok) is True
    assert verdicts_passed(bad) is False


def test_schema_check_command():
    cmd = schema_check_command("/var/www/moodle", "php")
    assert cmd == ["php", "/var/www/moodle/admin/cli/check_database_schema.php"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_verify.py -v`
Expected: FAIL (`ModuleNotFoundError: moodle_mssql2pg.verify`).

- [ ] **Step 3: Implement `verify.py`**

`moodle-mssql2pg/src/moodle_mssql2pg/verify.py`:
```python
from dataclasses import dataclass

_FAIL_STATUSES = {"missing", "mismatch"}


@dataclass
class TableVerdict:
    table: str
    src_count: int
    dst_count: int
    status: str


def compare_counts(
    src: dict[str, int], dst: dict[str, int], schema_only: set[str]
) -> list[TableVerdict]:
    verdicts: list[TableVerdict] = []
    for table in sorted(set(src) | set(dst)):
        s = src.get(table, 0)
        d = dst.get(table, 0)
        if table in schema_only:
            status = "ok_excluded" if d == 0 else "excluded_not_empty"
        elif table not in dst:
            status = "missing"
        elif s == d:
            status = "ok"
        else:
            status = "mismatch"
        verdicts.append(TableVerdict(table, s, d, status))
    return verdicts


def verdicts_passed(verdicts: list[TableVerdict]) -> bool:
    return not any(v.status in _FAIL_STATUSES for v in verdicts)


def schema_check_command(codebase_path: str, php_bin: str) -> list[str]:
    # Path is consumed by PHP on the (Linux) Moodle host — always forward slashes.
    script = codebase_path.rstrip("/") + "/admin/cli/check_database_schema.php"
    return [php_bin, script]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_verify.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add moodle-mssql2pg/src/moodle_mssql2pg/verify.py moodle-mssql2pg/tests/test_verify.py
git commit -m "feat: row-count verification and Moodle schema-check command"
```

---

## Task 8: Report — build report.md + PASS/FAIL summary

**Files:**
- Create: `moodle-mssql2pg/src/moodle_mssql2pg/report.py`
- Test: `moodle-mssql2pg/tests/test_report.py`

**Interfaces:**
- Consumes: `TableVerdict`, `verdicts_passed` (verify.py).
- Produces:
  - `@dataclass Report(passed: bool, summary: str, markdown: str)`
  - `build_report(verdicts: list[TableVerdict], schema_check_output: str | None = None) -> Report`
  - `write_report(report: Report, path: str) -> None`

`schema_check_output` is considered clean when it is `None`, empty, or contains the phrase "no differences" (case-insensitive); otherwise it counts against `passed`.

- [ ] **Step 1: Write the failing tests**

`moodle-mssql2pg/tests/test_report.py`:
```python
from moodle_mssql2pg.report import build_report, write_report
from moodle_mssql2pg.verify import TableVerdict


def _v(table, s, d, status):
    return TableVerdict(table, s, d, status)


def test_report_passes_when_all_ok():
    r = build_report([_v("mdl_user", 5, 5, "ok"), _v("mdl_log", 9, 0, "ok_excluded")])
    assert r.passed is True
    assert "PASS" in r.summary
    assert "mdl_user" in r.markdown


def test_report_fails_on_mismatch():
    r = build_report([_v("mdl_course", 5, 4, "mismatch")])
    assert r.passed is False
    assert "FAIL" in r.summary
    assert "mdl_course" in r.markdown


def test_schema_check_differences_fail_report():
    ok = build_report([_v("a", 1, 1, "ok")], schema_check_output="No differences found")
    bad = build_report([_v("a", 1, 1, "ok")], schema_check_output="Table mdl_x is missing")
    assert ok.passed is True
    assert bad.passed is False


def test_write_report(tmp_path):
    r = build_report([_v("a", 1, 1, "ok")])
    path = str(tmp_path / "report.md")
    write_report(r, path)
    assert "a" in (tmp_path / "report.md").read_text(encoding="utf-8")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_report.py -v`
Expected: FAIL (`ModuleNotFoundError: moodle_mssql2pg.report`).

- [ ] **Step 3: Implement `report.py`**

`moodle-mssql2pg/src/moodle_mssql2pg/report.py`:
```python
from dataclasses import dataclass

from moodle_mssql2pg.verify import TableVerdict, verdicts_passed


@dataclass
class Report:
    passed: bool
    summary: str
    markdown: str


def _schema_check_ok(output: str | None) -> bool:
    if output is None or output.strip() == "":
        return True
    return "no differences" in output.lower()


def build_report(
    verdicts: list[TableVerdict], schema_check_output: str | None = None
) -> Report:
    counts_ok = verdicts_passed(verdicts)
    schema_ok = _schema_check_ok(schema_check_output)
    passed = counts_ok and schema_ok
    summary = "KẾT QUẢ: PASS ✅" if passed else "KẾT QUẢ: FAIL ❌"

    lines = [
        "# Báo cáo chuyển đổi Moodle MSSQL → PostgreSQL",
        "",
        f"**{summary}**",
        "",
        "| Bảng | Nguồn (MSSQL) | Đích (PG) | Trạng thái |",
        "|---|---:|---:|---|",
    ]
    for v in verdicts:
        lines.append(f"| {v.table} | {v.src_count} | {v.dst_count} | {v.status} |")

    if schema_check_output is not None:
        lines += ["", "## check_database_schema.php", "", "```", schema_check_output.strip(), "```"]

    return Report(passed=passed, summary=summary, markdown="\n".join(lines) + "\n")


def write_report(report: Report, path: str) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(report.markdown)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_report.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add moodle-mssql2pg/src/moodle_mssql2pg/report.py moodle-mssql2pg/tests/test_report.py
git commit -m "feat: PASS/FAIL migration report"
```

---

## Task 9: CLI wiring + real DB/subprocess adapters

**Files:**
- Modify: `moodle-mssql2pg/src/moodle_mssql2pg/cli.py`
- Create: `moodle-mssql2pg/src/moodle_mssql2pg/adapters.py`
- Modify: `moodle-mssql2pg/tests/test_cli.py`

**Interfaces:**
- Consumes: everything above.
- Produces (adapters.py): `PymssqlClient` (implements `MssqlClient`), `Psycopg2Client` (implements `fix.PgClient` + row counts via `fetch_counts`), `connect_mssql(cfg)`, `connect_pgsql(cfg)`.
- Produces (cli.py): commands `test`, `discover`, `generate`, `migrate`, `fix`, `verify`, `run` (with `--config` default `config.yml`, `--output` default `output/`, and `run --dry-run`). Orchestration order in `run`: discover → generate → migrate → fix → verify → report.

Note: adapters touch real drivers, so they are covered by the smoke test in Task 10, not unit tests. Unit tests here assert the `run --dry-run` orchestration stops after `generate` using a monkeypatched pipeline.

- [ ] **Step 1: Write the failing test (dry-run orchestration)**

Append to `moodle-mssql2pg/tests/test_cli.py`:
```python
import textwrap

from click.testing import CliRunner

from moodle_mssql2pg import cli as climod
from moodle_mssql2pg.cli import main
from moodle_mssql2pg.discover import Discovered

_CFG = textwrap.dedent(
    """
    source_mssql: {host: h, port: 5968, db: S, user: u, password: p, schema: dbo}
    target_pgsql: {host: h, port: 5432, db: D, user: u, password: p, schema: public}
    options: {exclude_data_tables: [mdl_log]}
    """
)


def test_run_dry_run_stops_after_generate(tmp_path, monkeypatch):
    cfg_path = tmp_path / "config.yml"
    cfg_path.write_text(_CFG, encoding="utf-8")

    # Fake discover so no real DB is needed.
    monkeypatch.setattr(
        climod,
        "_discover_step",
        lambda cfg, out: Discovered(["mdl_user"], ["mdl_log"], [], {}, {"mdl_user": 1}),
    )
    called = {"migrate": False}
    monkeypatch.setattr(climod, "_migrate_step", lambda *a, **k: called.__setitem__("migrate", True))

    result = CliRunner().invoke(
        main, ["run", "--config", str(cfg_path), "--output", str(tmp_path / "out"), "--dry-run"]
    )
    assert result.exit_code == 0, result.output
    assert called["migrate"] is False
    assert (tmp_path / "out" / "batch_schema_only.load").exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_cli.py::test_run_dry_run_stops_after_generate -v`
Expected: FAIL (`AttributeError: module ... has no attribute '_discover_step'`).

- [ ] **Step 3: Implement adapters**

`moodle-mssql2pg/src/moodle_mssql2pg/adapters.py`:
```python
import pymssql
import psycopg2

from moodle_mssql2pg.config import Config
from moodle_mssql2pg.discover import (
    SQL_CHAR_COLUMNS,
    SQL_ROW_COUNTS,
    SQL_TABLES,
)


class PymssqlClient:
    def __init__(self, cfg: Config):
        c = cfg.source
        self._conn = pymssql.connect(
            server=c.host, port=str(c.port), user=c.user,
            password=c.password, database=c.db,
        )

    def _rows(self, sql: str, param):
        cur = self._conn.cursor()
        cur.execute(sql, (param,))
        return cur.fetchall()

    def fetch_tables(self, prefix: str) -> list[str]:
        return [r[0] for r in self._rows(SQL_TABLES, f"{prefix}%")]

    def fetch_char_columns(self, prefix: str) -> list[tuple[str, str]]:
        return [(r[0], r[1]) for r in self._rows(SQL_CHAR_COLUMNS, f"{prefix}%")]

    def fetch_row_counts(self, prefix: str) -> dict[str, int]:
        return {r[0]: int(r[1]) for r in self._rows(SQL_ROW_COUNTS, f"{prefix}%")}

    def close(self):
        self._conn.close()


class Psycopg2Client:
    def __init__(self, cfg: Config):
        c = cfg.target
        self._conn = psycopg2.connect(
            host=c.host, port=c.port, dbname=c.db, user=c.user, password=c.password
        )
        self._conn.autocommit = True
        self._schema = c.schema

    def execute(self, sql: str) -> None:
        with self._conn.cursor() as cur:
            cur.execute(sql)

    def fetch_values(self, sql: str) -> list[str]:
        with self._conn.cursor() as cur:
            cur.execute(sql)
            rows = cur.fetchall()
        # For multi-column rows (FK list), join with tab so fix.run_fix can split.
        return ["\t".join(str(x) for x in row) for row in rows]

    def fetch_counts(self, tables: list[str]) -> dict[str, int]:
        counts: dict[str, int] = {}
        with self._conn.cursor() as cur:
            for t in tables:
                cur.execute(f'SELECT count(*) FROM "{self._schema}"."{t}"')
                counts[t] = int(cur.fetchone()[0])
        return counts

    def close(self):
        self._conn.close()
```

- [ ] **Step 4: Implement CLI orchestration**

Replace `moodle-mssql2pg/src/moodle_mssql2pg/cli.py` with:
```python
import os

import click

from moodle_mssql2pg import __version__
from moodle_mssql2pg.config import Config, load_config
from moodle_mssql2pg.discover import Discovered, discover, load_discovered, save_discovered
from moodle_mssql2pg.fix import run_fix
from moodle_mssql2pg.generate import plan_load_files, write_load_files
from moodle_mssql2pg.migrate import State, SubprocessPgloaderRunner, migrate
from moodle_mssql2pg.report import build_report, write_report
from moodle_mssql2pg.verify import compare_counts, schema_check_command

_CONFIG = click.option("--config", "config_path", default="config.yml", show_default=True)
_OUTPUT = click.option("--output", "out_dir", default="output", show_default=True)


def _discover_step(cfg: Config, out_dir: str) -> Discovered:
    from moodle_mssql2pg.adapters import PymssqlClient

    client = PymssqlClient(cfg)
    try:
        disc = discover(client, cfg.options)
    finally:
        client.close()
    save_discovered(disc, os.path.join(out_dir, "discovered.json"))
    return disc


def _generate_step(cfg: Config, disc: Discovered, out_dir: str) -> list:
    files = plan_load_files(cfg, disc)
    write_load_files(files, out_dir)
    return files


def _migrate_step(cfg: Config, files: list, out_dir: str) -> None:
    runner = SubprocessPgloaderRunner()
    state = State(os.path.join(out_dir, "migrate_state.json"))
    migrate(files, runner, cfg.source.port, out_dir, state=state)


def _fix_step(cfg: Config, disc: Discovered) -> None:
    from moodle_mssql2pg.adapters import Psycopg2Client

    client = Psycopg2Client(cfg)
    try:
        run_fix(cfg, disc, client)
    finally:
        client.close()


def _verify_step(cfg: Config, disc: Discovered, out_dir: str) -> bool:
    from moodle_mssql2pg.adapters import Psycopg2Client

    client = Psycopg2Client(cfg)
    try:
        dst = client.fetch_counts(disc.data_tables + disc.schema_only_tables)
    finally:
        client.close()
    verdicts = compare_counts(disc.row_counts, dst, set(disc.schema_only_tables))

    schema_output = None
    if cfg.options.moodle_codebase_path:
        import subprocess

        cmd = schema_check_command(cfg.options.moodle_codebase_path, cfg.options.php_bin)
        schema_output = subprocess.run(cmd, capture_output=True, text=True).stdout

    report = build_report(verdicts, schema_output)
    write_report(report, os.path.join(out_dir, "report.md"))
    click.echo(report.summary)
    return report.passed


@click.group()
@click.version_option(version=__version__, prog_name="moodle-mssql2pg")
def main() -> None:
    """Chuyển đổi database Moodle từ SQL Server sang PostgreSQL."""


@main.command()
@_CONFIG
def test(config_path: str) -> None:
    """Kiểm tra 2 kết nối (không đụng dữ liệu)."""
    from moodle_mssql2pg.adapters import PymssqlClient, Psycopg2Client

    cfg = load_config(config_path)
    PymssqlClient(cfg).close()
    Psycopg2Client(cfg).close()
    click.echo("Kết nối MSSQL và PostgreSQL OK ✅")


@main.command(name="run")
@_CONFIG
@_OUTPUT
@click.option("--dry-run", is_flag=True, help="Chỉ discover + generate, không nạp dữ liệu.")
def run_cmd(config_path: str, out_dir: str, dry_run: bool) -> None:
    """Chạy toàn bộ pipeline."""
    cfg = load_config(config_path)
    os.makedirs(out_dir, exist_ok=True)

    disc = _discover_step(cfg, out_dir)
    files = _generate_step(cfg, disc, out_dir)
    if dry_run:
        click.echo(f"[dry-run] Đã tạo {len(files)} file .load trong {out_dir}")
        return
    _migrate_step(cfg, files, out_dir)
    _fix_step(cfg, disc)
    passed = _verify_step(cfg, disc, out_dir)
    raise SystemExit(0 if passed else 1)


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/ -v`
Expected: PASS (all tests, including the new dry-run test).

- [ ] **Step 6: Commit**

```bash
git add moodle-mssql2pg/src/moodle_mssql2pg/cli.py moodle-mssql2pg/src/moodle_mssql2pg/adapters.py moodle-mssql2pg/tests/test_cli.py
git commit -m "feat: CLI orchestration (run/test/dry-run) with pymssql/psycopg2 adapters"
```

---

## Task 10: Docker packaging + config template + smoke test

**Files:**
- Create: `moodle-mssql2pg/Dockerfile`, `moodle-mssql2pg/docker-compose.yml`, `moodle-mssql2pg/config.example.yml`

**Interfaces:**
- Produces: a runnable image whose entrypoint is `moodle-mssql2pg`; `docker compose run --rm migrator run` is the one-command experience.

- [ ] **Step 1: Create the config template**

`moodle-mssql2pg/config.example.yml` (copy the block from the design spec §5 verbatim, including the full `exclude_data_tables` default list and the commented optional tier). At minimum it must contain the two connection blocks and the `options` block with `exclude_data_tables` defaults. Copy from `docs/superpowers/specs/2026-07-07-moodle-mssql-to-pgsql-migration-design.md` section 5.

- [ ] **Step 2: Create the Dockerfile**

`moodle-mssql2pg/Dockerfile`:
```dockerfile
# pgloader maintainer image already bundles pgloader + FreeTDS on Debian.
FROM dimitri/pgloader:latest

RUN apt-get update && apt-get install -y --no-install-recommends \
      python3 python3-pip \
      freetds-dev freetds-bin \
      postgresql-client \
      php-cli \
      gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml requirements.txt ./
COPY src ./src
RUN pip3 install --no-cache-dir --break-system-packages ".[drivers]"

ENTRYPOINT ["moodle-mssql2pg"]
CMD ["--help"]
```

- [ ] **Step 3: Create docker-compose.yml**

`moodle-mssql2pg/docker-compose.yml`:
```yaml
services:
  migrator:
    build: .
    # Truy cập IP nội bộ (172.100.100.x) — bật host network trên Linux nếu cần:
    # network_mode: host
    volumes:
      - ./config.yml:/app/config.yml:ro
      - ./output:/app/output
```

- [ ] **Step 4: Smoke test the image**

Run:
```bash
cd moodle-mssql2pg
docker build -t moodle-mssql2pg .
docker run --rm moodle-mssql2pg --version
docker run --rm moodle-mssql2pg run --help
```
Expected: build succeeds; `--version` prints `0.1.0`; `run --help` shows the `--dry-run` option.

> If `dimitri/pgloader:latest` fails to pull or run, fall back to `FROM debian:bookworm-slim` and add `pgloader` via `apt-get install -y pgloader`; if the apt build misbehaves at migrate time, document building pgloader from source in the README (already noted as a known issue).

- [ ] **Step 5: Commit**

```bash
git add moodle-mssql2pg/Dockerfile moodle-mssql2pg/docker-compose.yml moodle-mssql2pg/config.example.yml
git commit -m "feat: Docker packaging and config template"
```

---

## Task 11: README + post-migration runbook (Vietnamese)

**Files:**
- Create: `moodle-mssql2pg/README.md`

**Interfaces:** none (documentation).

- [ ] **Step 1: Write the README**

`moodle-mssql2pg/README.md` must contain these sections (in Vietnamese), with real content:

```markdown
# moodle-mssql2pg — Chuyển database Moodle từ SQL Server sang PostgreSQL

Công cụ tự động chuyển database Moodle từ SQL Server sang PostgreSQL. Bạn chỉ
cần cấu hình 2 connection rồi chạy một lệnh.

## 1. Yêu cầu
- Docker (khuyến nghị) — image đã có sẵn pgloader + FreeTDS + Python.
- Truy cập mạng tới cả 2 database.

## 2. Cấu hình
1. Copy `config.example.yml` thành `config.yml`.
2. Điền 2 khối `source_mssql` và `target_pgsql` (host, port, db, user, password).
3. (Tùy chọn) chỉnh `options.exclude_data_tables`, `batch_size`, `moodle_codebase_path`.

> Mật khẩu có ký tự đặc biệt (`+`, `(`) vẫn điền bình thường — công cụ tự
> URL-encode. Có thể đặt mật khẩu qua biến môi trường `MSSQL_PASSWORD` /
> `PGSQL_PASSWORD` để không lưu trong file.

## 3. Chạy
```bash
docker compose run --rm migrator test           # kiểm tra 2 kết nối
docker compose run --rm migrator run --dry-run  # xem trước file .load
docker compose run --rm migrator run            # chạy thật
```
Kết quả: DB PostgreSQL đã chuyển + `output/report.md` (PASS/FAIL, số dòng từng bảng).

## 4. Bảng loại trừ (quan trọng)
Các bảng trong `exclude_data_tables` (log, cache, session, temp…) vẫn được
**tạo bảng RỖNG** (giữ cấu trúc) nhưng **bỏ dữ liệu** — Moodle không báo thiếu
bảng. Mặc định đã loại `mdl_logstore_standard_log`, `mdl_log`, … (xem
`config.example.yml`).

## 5. Runbook sau khi chuyển xong (để Moodle chạy không lỗi)
1. Sửa `config.php` của Moodle: `$CFG->dbtype = 'pgsql'`, `dbhost`, `dbname`,
   `dbuser`, `dbpass`, `dbport`, `$CFG->prefix = 'mdl_'`.
2. **Copy `moodledata`** sang server mới (`rsync -a`) — database KHÔNG chứa nội
   dung file thật (ảnh, tài liệu). Bỏ qua bước này là ảnh/file sẽ hỏng.
3. `php admin/cli/purge_caches.php`
4. `php admin/cli/check_database_schema.php` → kỳ vọng "no differences".
5. Test: đăng nhập, tạo thử 1 bản ghi (kiểm tra sequence), chạy
   `php admin/cli/cron.php`.

## 6. Xử lý sự cố
- `out of shared memory`: tăng `max_locks_per_transaction` (vd 128) trên PG rồi
  chạy lại (`run` sẽ resume, bỏ qua batch đã xong).
- Bảng lớn chạy lâu: đã tự tách file riêng; có thể tăng `large_table_threshold`.
- pgloader lỗi: xem log trong `output/<file>.load.log`.
```

- [ ] **Step 2: Verify the runbook is complete**

Run:
```bash
grep -c "moodledata" moodle-mssql2pg/README.md      # >= 1 (bước copy file bắt buộc)
grep -c "check_database_schema" moodle-mssql2pg/README.md   # >= 1
```
Expected: both ≥ 1.

- [ ] **Step 3: Commit**

```bash
git add moodle-mssql2pg/README.md
git commit -m "docs: Vietnamese README with configuration and post-migration runbook"
```

---

## Task 12: Full test-suite gate

**Files:** none (verification only).

- [ ] **Step 1: Run the whole suite**

Run:
```bash
cd moodle-mssql2pg && python -m pytest tests/ -v
```
Expected: all tests PASS across `test_config`, `test_discover`, `test_generate`, `test_migrate`, `test_fix`, `test_verify`, `test_report`, `test_cli`.

- [ ] **Step 2: Commit any final touch-ups**

```bash
git add -A && git commit -m "chore: full test suite green" || echo "nothing to commit"
```

---

## Self-Review

**Spec coverage check (spec §→task):**
- §4 pipeline `discover/generate/migrate/fix/verify/report` → Tasks 3,4,5,6,7,8 ✓
- §5 config (2 connections + options + exclude list) → Task 2 + Task 10 (template) ✓
- §6.1 discover (tables, char cols, row counts, classification) → Task 3 ✓
- §6.2 generate (schema-only for excluded, batching, large tables, casts, URL-encode) → Task 4 ✓
- §6.3 migrate (TDSPORT, resume, fail-fast, logs) → Task 5 ✓
- §6.4 fix (drop FK, trim char, sequences, vacuum) → Task 6 ✓
- §6.5 verify (row counts, excluded=empty OK, schema check) → Task 7 + Task 9 ✓
- §6.6 report (PASS/FAIL) → Task 8 ✓
- §7 Moodle-safe rules → Global Constraints + Tasks 4,6 ✓
- §8 large tables → Task 3 (detection) + Task 4 (own file) ✓
- §9 error handling/resume/safety → Task 5 (resume, fail-fast) + adapters read-only source ✓
- §10 verification evidence → Tasks 7,8,9 ✓
- §11 Docker → Task 10 ✓
- §12 runbook → Task 11 ✓
- §13 file structure → File Structure section + all tasks ✓
- §16 success criteria → Task 12 gate + runbook ✓

No gaps found.

**Placeholder scan:** No "TBD/TODO/handle edge cases/similar to Task N". Task 10 Step 1 references copying the config block verbatim from the spec §5 — that content is fully specified in the spec, not a placeholder.

**Type consistency:** `Config/DbConn/Options` (config.py) used consistently; `Discovered` fields (`data_tables`, `schema_only_tables`, `large_tables`, `char_columns`, `row_counts`) identical across discover/generate/verify/cli; `LoadFile.kind` values `{schema_only,data,large}` match `migrate._ORDER`; `TableVerdict.status` values consistent between verify and report; `mssql_url/pgsql_url` signatures stable. Consistent.
