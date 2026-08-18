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
