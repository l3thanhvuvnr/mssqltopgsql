from moodle_mssql2pg.verify import (
    compare_counts,
    schema_check_command,
    verdicts_passed,
)


def test_compare_counts_statuses():
    src = {"mdl_user": 10, "mdl_course": 5, "mdl_log": 999, "mdl_gone": 3}
    dst = {"mdl_user": 10, "mdl_course": 4, "mdl_log": 0}
    verdicts = {v.table: v.status for v in compare_counts(src, dst, {"mdl_log"})}
    assert verdicts["mdl_user"] == "ok"
    assert verdicts["mdl_course"] == "mismatch"
    assert verdicts["mdl_log"] == "ok_excluded"   # excluded and empty
    assert verdicts["mdl_gone"] == "missing"       # in src, absent in dst


def test_excluded_but_not_empty_flagged():
    verdicts = compare_counts({"mdl_log": 5}, {"mdl_log": 5}, {"mdl_log"})
    assert verdicts[0].status == "excluded_not_empty"


def test_verdicts_passed():
    ok = compare_counts({"a": 1}, {"a": 1}, set())
    bad = compare_counts({"a": 1}, {"a": 2}, set())
    assert verdicts_passed(ok) is True
    assert verdicts_passed(bad) is False


def test_schema_check_command():
    cmd = schema_check_command("/var/www/moodle", "php")
    assert cmd == ["php", "/var/www/moodle/admin/cli/check_database_schema.php"]
