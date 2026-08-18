from moodle_mssql2pg.report import build_report, write_report
from moodle_mssql2pg.verify import TableVerdict


def _v(table, s, d, status):
    return TableVerdict(table, s, d, status)


def test_report_passes_when_all_ok():
    r = build_report([_v("mdl_user", 5, 5, "ok"), _v("mdl_log", 9, 0, "ok_excluded")])
    assert r.passed is True
    assert "PASS" in r.summary
    assert "mdl_user" in r.markdown


def test_report_fails_on_mismatch():
    r = build_report([_v("mdl_course", 5, 4, "mismatch")])
    assert r.passed is False
    assert "FAIL" in r.summary
    assert "mdl_course" in r.markdown


def test_schema_check_differences_fail_report():
    ok = build_report([_v("a", 1, 1, "ok")], schema_check_output="No differences found")
    bad = build_report([_v("a", 1, 1, "ok")], schema_check_output="Table mdl_x is missing")
    assert ok.passed is True
    assert bad.passed is False


def test_write_report(tmp_path):
    r = build_report([_v("a", 1, 1, "ok")])
    path = str(tmp_path / "report.md")
    write_report(r, path)
    assert "a" in (tmp_path / "report.md").read_text(encoding="utf-8")
