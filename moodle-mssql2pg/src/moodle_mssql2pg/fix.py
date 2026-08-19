import hashlib
from typing import Protocol

from moodle_mssql2pg.config import Config
from moodle_mssql2pg.discover import Discovered

SQL_LIST_FKS = (
    "SELECT tc.table_name, tc.constraint_name "
    "FROM information_schema.table_constraints tc "
    "WHERE tc.constraint_type = 'FOREIGN KEY' AND tc.table_schema = %s"
)
# Index dang co ben PostgreSQL, kem danh sach cot theo dung thu tu khoa.
SQL_EXISTING_INDEXES = (
    "SELECT t.relname, ix.indisunique::int, "
    "       string_agg(a.attname, ',' ORDER BY k.ord) "
    "FROM pg_index ix "
    "JOIN pg_class i ON i.oid = ix.indexrelid "
    "JOIN pg_class t ON t.oid = ix.indrelid "
    "JOIN pg_namespace n ON n.oid = t.relnamespace "
    "CROSS JOIN LATERAL unnest(ix.indkey) WITH ORDINALITY AS k(attnum, ord) "
    "JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = k.attnum "
    "WHERE n.nspname = %s AND ix.indpred IS NULL AND k.attnum > 0 "
    "GROUP BY t.relname, i.relname, ix.indisunique"
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


def restore_typemod_statements(
    schema: str, typed_columns: dict[str, list[list]]
) -> list[str]:
    """Tra lai typemod ma pgloader da bo khi tao bang.

    Hai hau qua da gap:

    1. (n)varchar(100) ben MSSQL thanh "text" ben PostgreSQL. Moodle doc metadata
       cot: "text" -> meta_type 'X' (clob), va moodle_database->where_clause() nem
       loi "textconditionsnotallowed" cho MOI dieu kien so sanh bang tren cot do.
       Site hong ngay khi khoi dong: plugin_manager->load_installed_plugins() truy
       van mdl_config_plugins theo name = 'version'.

    2. decimal(10,5) thanh "numeric" khong precision. check_database_schema.php bao
       "column 'finalgrade' size is (-1,65531), expected (10,5)".
    """
    stmts: list[str] = []
    for table in sorted(typed_columns):
        for column, pg_type in typed_columns[table]:
            stmts.append(
                f"ALTER TABLE {_q(schema)}.{_q(table)} "
                f"ALTER COLUMN {_q(column)} TYPE {pg_type};"
            )
    return stmts


PG_MAX_IDENTIFIER = 63


def safe_index_name(source_name: str) -> str:
    """Ten index hop le cho PostgreSQL, khong bao gio bi cat mat.

    PostgreSQL cat identifier o 63 ky tu. Ten index Moodle rat dai nen hai index
    khac nhau co the cat ra cung mot ten. Neu qua dai thi rut ngan va gan hau to
    bam tu ten goc de van duy nhat.
    """
    name = "".join(c if c.isalnum() or c == "_" else "_" for c in source_name)
    if len(name) <= PG_MAX_IDENTIFIER:
        return name
    digest = hashlib.sha1(source_name.encode("utf-8")).hexdigest()[:8]
    return f"{name[: PG_MAX_IDENTIFIER - 9]}_{digest}"


def missing_index_statements(
    schema: str,
    source_indexes: list[list],
    existing: set[tuple[str, int, str]],
) -> list[str]:
    """CREATE INDEX cho cac index co ben nguon nhung thieu ben PostgreSQL.

    So khop theo (bang, unique, danh sach cot) chu khong theo ten, vi pgloader
    doi ten index. Truong hop that da gap: mdl_enrol_lti_lti2_share_key co hai
    unique index, ca hai cat ra cung mot ten 63 ky tu nen chi tao duoc mot —
    mat rang buoc unique tren cot sharekey.
    """
    stmts: list[str] = []
    for table, name, is_unique, columns in source_indexes:
        key = (table, int(is_unique), columns)
        if key in existing:
            continue
        existing.add(key)
        cols = ", ".join(_q(c.strip()) for c in columns.split(","))
        unique = "UNIQUE " if int(is_unique) else ""
        stmts.append(
            f"CREATE {unique}INDEX IF NOT EXISTS {_q(safe_index_name(name))} "
            f"ON {_q(schema)}.{_q(table)} ({cols});"
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

    # 2. Restore typemod (varchar(n), numeric(p,s)) that pgloader dropped.
    for stmt in restore_typemod_statements(schema, disc.typed_columns):
        client.execute(stmt)

    # 3. Trim char/nchar padding (only on data tables).
    for stmt in trim_char_statements(schema, disc.char_columns):
        client.execute(stmt)

    # 4. Create indexes pgloader could not (63-char name collisions).
    existing = set()
    for row in client.fetch_values(SQL_EXISTING_INDEXES % f"'{schema}'"):
        parts = row.split("\t")
        if len(parts) == 3:
            existing.add((parts[0], int(parts[1]), parts[2]))
    for stmt in missing_index_statements(schema, disc.source_indexes, existing):
        client.execute(stmt)

    # 5. Normalise id sequences for every table that has an id column.
    for table in client.fetch_values(SQL_TABLES_WITH_ID % f"'{schema}'"):
        client.execute(fix_sequence_statement(schema, table))

    # 6. Planner stats.
    client.execute(vacuum_analyze_statement())
