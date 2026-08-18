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


def test_mssql_url_keeps_password_literal_and_omits_port(tmp_path):
    cfg = load_config(_write(tmp_path, CONFIG_YAML))
    url = mssql_url(cfg.source)
    # pgloader sends the URI verbatim, so "+" and "(" must NOT become %2B / %28
    assert url == "mssql://vnr:Pw+(Example123@172.100.100.200/LMS_INS_TEST"
    assert ":5968" not in url


@pytest.mark.parametrize("bad_password", ["pw@word", "pw/word"])
def test_password_pgloader_cannot_express_is_rejected(tmp_path, bad_password):
    text = CONFIG_YAML.replace('"Pw+(Example123"', f'"{bad_password}"')
    cfg = load_config(_write(tmp_path, text))
    with pytest.raises(ValueError, match="pgloader"):
        mssql_url(cfg.source)


def test_pgsql_url_includes_port(tmp_path):
    cfg = load_config(_write(tmp_path, CONFIG_YAML))
    assert pgsql_url(cfg.target) == "postgresql://admin:changeme_pg@172.100.100.13:5432/ins_test_13"
