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
    # credentials literal — pgloader does not percent-decode the URI
    assert "mssql://vnr:p+(@h1/SRC" in out
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
