from dataclasses import dataclass

from moodle_mssql2pg.verify import TableVerdict, verdicts_passed


@dataclass
class Report:
    passed: bool
    summary: str
    markdown: str


def _schema_check_ok(output: str | None) -> bool:
    if output is None or output.strip() == "":
        return True
    return "no differences" in output.lower()


def build_report(
    verdicts: list[TableVerdict], schema_check_output: str | None = None
) -> Report:
    counts_ok = verdicts_passed(verdicts)
    schema_ok = _schema_check_ok(schema_check_output)
    passed = counts_ok and schema_ok
    summary = "KẾT QUẢ: PASS ✅" if passed else "KẾT QUẢ: FAIL ❌"

    lines = [
        "# Báo cáo chuyển đổi Moodle MSSQL → PostgreSQL",
        "",
        f"**{summary}**",
        "",
        "| Bảng | Nguồn (MSSQL) | Đích (PG) | Trạng thái |",
        "|---|---:|---:|---|",
    ]
    for v in verdicts:
        lines.append(f"| {v.table} | {v.src_count} | {v.dst_count} | {v.status} |")

    if schema_check_output is not None:
        lines += ["", "## check_database_schema.php", "", "```", schema_check_output.strip(), "```"]

    return Report(passed=passed, summary=summary, markdown="\n".join(lines) + "\n")


def write_report(report: Report, path: str) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(report.markdown)
