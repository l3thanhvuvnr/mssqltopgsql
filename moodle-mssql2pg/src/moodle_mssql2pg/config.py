import os
from dataclasses import dataclass, field

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


# pgloader does NOT percent-decode connection strings: whatever sits between ":"
# and "@" is sent to the server verbatim. Percent-encoding here silently breaks
# login (verified: real password "a#!" must be written "a#!"; "a%23%21" is
# rejected by the server as a wrong password). So credentials go in literally.
#
# "@" and "/" terminate the URI grammar and pgloader offers no escape for them,
# so fail loudly at config time instead of midway through a migration.
_PGLOADER_UNSAFE = "@/"


def _literal(value: str, field_name: str) -> str:
    bad = sorted({c for c in value if c in _PGLOADER_UNSAFE})
    if bad:
        chars = " ".join(f"'{c}'" for c in bad)
        raise ValueError(
            f"{field_name} chứa ký tự {chars} — pgloader không biểu diễn được ký tự "
            "này trong connection string và cũng không hỗ trợ escape. Hãy dùng một "
            "tài khoản khác không chứa các ký tự đó."
        )
    return value


def mssql_url(c: DbConn) -> str:
    # FreeTDS ignores port in the URL; migrate.py exports TDSPORT instead.
    return (
        f"mssql://{_literal(c.user, 'user MSSQL')}"
        f":{_literal(c.password, 'password MSSQL')}@{c.host}/{c.db}"
    )


def pgsql_url(c: DbConn) -> str:
    return (
        f"postgresql://{_literal(c.user, 'user PostgreSQL')}"
        f":{_literal(c.password, 'password PostgreSQL')}"
        f"@{c.host}:{c.port}/{c.db}"
    )
