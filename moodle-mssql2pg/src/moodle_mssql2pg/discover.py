import json
from dataclasses import asdict, dataclass, field
from typing import Protocol

from moodle_mssql2pg.config import Options

SQL_TABLES = (
    "SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES "
    "WHERE TABLE_TYPE = 'BASE TABLE' AND TABLE_NAME LIKE %s ORDER BY TABLE_NAME"
)
# Cot co do dai gioi han: pgloader bo typemod va tao ra "text", nhung Moodle doc
# metadata cot de quyet dinh meta_type. Cot "text" bi coi la clob (X) va Moodle
# tu choi moi dieu kien so sanh bang -> loi "textconditionsnotallowed".
# Cung van de voi decimal(10,5): pgloader tao ra "numeric" khong precision, Moodle
# bao 'size is (-1,65531), expected (10,5)'.
# CHARACTER_MAXIMUM_LENGTH = -1 nghia la (n)varchar(max) — truong hop do "text" moi
# dung, nen loai ra khoi truy van nay.
SQL_TYPED_COLUMNS = (
    "SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE, CHARACTER_MAXIMUM_LENGTH, "
    "NUMERIC_PRECISION, NUMERIC_SCALE FROM INFORMATION_SCHEMA.COLUMNS "
    "WHERE TABLE_NAME LIKE %s AND ("
    "      (DATA_TYPE IN ('nvarchar', 'varchar', 'nchar', 'char') "
    "       AND CHARACTER_MAXIMUM_LENGTH > 0) "
    "   OR DATA_TYPE IN ('decimal', 'numeric')) "
    "ORDER BY TABLE_NAME, ORDINAL_POSITION"
)


def pg_type_with_typemod(
    data_type: str, char_len, precision, scale
) -> str | None:
    """Kieu PostgreSQL kem typemod tuong ung voi cot MSSQL, None neu khong can."""
    dt = (data_type or "").lower()
    if dt in ("nvarchar", "varchar", "nchar", "char") and char_len and int(char_len) > 0:
        return f"varchar({int(char_len)})"
    if dt in ("decimal", "numeric") and precision:
        return f"numeric({int(precision)},{int(scale or 0)})"
    return None
# Index cua nguon (khong tinh primary key, chi lay cot khoa — bo cot INCLUDE).
# Can doi chieu vi pgloader dat ten index kieu "idx_<oid>_<ten-goc>" roi PostgreSQL
# cat con 63 ky tu; hai index dai ten giong nhau o dau se cat ra CUNG mot ten va
# cai thu hai khong tao duoc (loi 42P07 relation already exists).
SQL_SOURCE_INDEXES = (
    "SELECT t.name, i.name, CAST(i.is_unique AS INT), "
    "  STUFF(( SELECT ',' + c.name FROM sys.index_columns ic "
    "          JOIN sys.columns c ON c.object_id = ic.object_id "
    "                            AND c.column_id = ic.column_id "
    "          WHERE ic.object_id = i.object_id AND ic.index_id = i.index_id "
    "            AND ic.is_included_column = 0 "
    "          ORDER BY ic.key_ordinal FOR XML PATH('')), 1, 1, '') "
    "FROM sys.indexes i JOIN sys.tables t ON t.object_id = i.object_id "
    "WHERE i.index_id > 0 AND i.is_primary_key = 0 AND i.has_filter = 0 "
    "  AND t.name LIKE %s ORDER BY t.name, i.name"
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
    def fetch_typed_columns(self, prefix: str) -> list[tuple]: ...
    def fetch_source_indexes(self, prefix: str) -> list[tuple]: ...
    def fetch_row_counts(self, prefix: str) -> dict[str, int]: ...


@dataclass
class Discovered:
    data_tables: list[str]
    schema_only_tables: list[str]
    large_tables: list[str]
    char_columns: dict[str, list[str]]
    row_counts: dict[str, int]
    # {ten_bang: [[ten_cot, "varchar(100)"], ...]} — list de serialise JSON duoc.
    typed_columns: dict[str, list[list]] = field(default_factory=dict)
    # [[bang, ten_index, unique(0/1), "cot1,cot2"], ...]
    source_indexes: list[list] = field(default_factory=list)


def classify(
    tables: list[str],
    row_counts: dict[str, int],
    char_columns: list[tuple[str, str]],
    options: Options,
    typed_columns: list[tuple] | None = None,
    source_indexes: list[tuple] | None = None,
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

    typed_map: dict[str, list[list]] = {}
    for table, column, data_type, char_len, precision, scale in typed_columns or []:
        if table not in data_set:
            continue
        pg_type = pg_type_with_typemod(data_type, char_len, precision, scale)
        if pg_type:
            typed_map.setdefault(table, []).append([column, pg_type])

    return Discovered(
        data_tables=data_tables,
        schema_only_tables=schema_only_tables,
        large_tables=large_tables,
        char_columns=char_map,
        row_counts={t: row_counts.get(t, 0) for t in table_set},
        typed_columns=typed_map,
        source_indexes=[
            [t, n, int(u), cols]
            for t, n, u, cols in (source_indexes or [])
            if t in data_set and cols
        ],
    )


def discover(client: MssqlClient, options: Options) -> Discovered:
    prefix = options.table_prefix
    tables = client.fetch_tables(prefix)
    char_columns = client.fetch_char_columns(prefix)
    row_counts = client.fetch_row_counts(prefix)
    typed_columns = client.fetch_typed_columns(prefix)
    source_indexes = client.fetch_source_indexes(prefix)
    return classify(
        tables, row_counts, char_columns, options, typed_columns, source_indexes
    )


def save_discovered(d: Discovered, path: str) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(asdict(d), fh, ensure_ascii=False, indent=2)


def load_discovered(path: str) -> Discovered:
    with open(path, encoding="utf-8") as fh:
        return Discovered(**json.load(fh))
