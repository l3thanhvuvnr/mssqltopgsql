import textwrap

from click.testing import CliRunner

from moodle_mssql2pg import __version__
from moodle_mssql2pg import cli as climod
from moodle_mssql2pg.cli import main
from moodle_mssql2pg.discover import Discovered


def test_version_flag_prints_version():
    result = CliRunner().invoke(main, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output


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
