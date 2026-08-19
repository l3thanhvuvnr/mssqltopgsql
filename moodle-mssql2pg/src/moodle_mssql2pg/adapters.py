import pymssql
import psycopg2

from moodle_mssql2pg.config import Config
from moodle_mssql2pg.discover import (
    SQL_CHAR_COLUMNS,
    SQL_ROW_COUNTS,
    SQL_TABLES,
    SQL_SOURCE_INDEXES,
    SQL_TYPED_COLUMNS,
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

    def fetch_typed_columns(self, prefix: str) -> list[tuple]:
        return [tuple(r) for r in self._rows(SQL_TYPED_COLUMNS, f"{prefix}%")]

    def fetch_source_indexes(self, prefix: str) -> list[tuple]:
        return [tuple(r) for r in self._rows(SQL_SOURCE_INDEXES, f"{prefix}%")]

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
