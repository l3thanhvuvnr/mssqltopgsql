from dataclasses import dataclass

_FAIL_STATUSES = {"missing", "mismatch"}


@dataclass
class TableVerdict:
    table: str
    src_count: int
    dst_count: int
    status: str


def compare_counts(
    src: dict[str, int], dst: dict[str, int], schema_only: set[str]
) -> list[TableVerdict]:
    verdicts: list[TableVerdict] = []
    for table in sorted(set(src) | set(dst)):
        s = src.get(table, 0)
        d = dst.get(table, 0)
        if table in schema_only:
            status = "ok_excluded" if d == 0 else "excluded_not_empty"
        elif table not in dst:
            status = "missing"
        elif s == d:
            status = "ok"
        else:
            status = "mismatch"
        verdicts.append(TableVerdict(table, s, d, status))
    return verdicts


def verdicts_passed(verdicts: list[TableVerdict]) -> bool:
    return not any(v.status in _FAIL_STATUSES for v in verdicts)


def schema_check_command(codebase_path: str, php_bin: str) -> list[str]:
    # Path is consumed by PHP on the (Linux) Moodle host — always forward slashes.
    script = codebase_path.rstrip("/") + "/admin/cli/check_database_schema.php"
    return [php_bin, script]
