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
