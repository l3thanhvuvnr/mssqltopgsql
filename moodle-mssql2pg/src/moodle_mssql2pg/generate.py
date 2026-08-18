import os
from dataclasses import dataclass

from moodle_mssql2pg.config import Config, mssql_url, pgsql_url
from moodle_mssql2pg.discover import Discovered

CAST_BLOCK = (
    "CAST type bit to smallint drop typemod,\n"
    "     type tinyint to smallint drop typemod,\n"
    "     type uniqueidentifier to text,\n"
    "     type xml to text"
)


@dataclass
class LoadFile:
    filename: str
    kind: str  # "schema_only" | "data" | "large"
    tables: list[str]
    content: str


def chunked(items: list[str], size: int) -> list[list[str]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def render_load(config: Config, tables: list[str], mode: str) -> str:
    opts = ["create tables", "create indexes"]
    if mode == "data":
        opts.append("reset sequences")
    opts.append("no foreign keys")
    if mode == "schema_only":
        opts.append("schema only")
    if config.options.drop_target_tables:
        opts.append("include drop")
    with_clause = ",\n     ".join(opts)

    src_schema = config.source.schema
    tgt_schema = config.target.schema
    names = ", ".join(f"'{t}'" for t in tables)

    return (
        "LOAD DATABASE\n"
        f"     FROM {mssql_url(config.source)}\n"
        f"     INTO {pgsql_url(config.target)}\n\n"
        f"WITH {with_clause}\n\n"
        f"SET work_mem to '{config.options.work_mem}', "
        f"maintenance_work_mem to '{config.options.maintenance_work_mem}'\n\n"
        f"{CAST_BLOCK}\n\n"
        f"ALTER SCHEMA '{src_schema}' RENAME TO '{tgt_schema}'\n\n"
        f"INCLUDING ONLY TABLE NAMES LIKE {names} IN SCHEMA '{src_schema}';\n"
    )


def plan_load_files(config: Config, disc: Discovered) -> list[LoadFile]:
    files: list[LoadFile] = []

    if disc.schema_only_tables:
        files.append(
            LoadFile(
                filename="batch_schema_only.load",
                kind="schema_only",
                tables=list(disc.schema_only_tables),
                content=render_load(config, disc.schema_only_tables, "schema_only"),
            )
        )

    large = set(disc.large_tables)
    normal = [t for t in disc.data_tables if t not in large]
    for i, batch in enumerate(chunked(normal, config.options.batch_size), start=1):
        files.append(
            LoadFile(
                filename=f"batch_{i}.load",
                kind="data",
                tables=batch,
                content=render_load(config, batch, "data"),
            )
        )

    for table in disc.large_tables:
        files.append(
            LoadFile(
                filename=f"batch_{table}.load",
                kind="large",
                tables=[table],
                content=render_load(config, [table], "data"),
            )
        )

    return files


def write_load_files(load_files: list[LoadFile], out_dir: str) -> list[str]:
    os.makedirs(out_dir, exist_ok=True)
    paths: list[str] = []
    for lf in load_files:
        path = os.path.join(out_dir, lf.filename)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(lf.content)
        paths.append(path)
    return paths
