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
