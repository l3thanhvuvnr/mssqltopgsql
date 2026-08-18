import json

from moodle_mssql2pg.config import Options
from moodle_mssql2pg.discover import (
    Discovered,
    classify,
    discover,
    load_discovered,
    save_discovered,
)


class FakeClient:
    def __init__(self, tables, char_cols, counts):
        self._tables, self._char, self._counts = tables, char_cols, counts

    def fetch_tables(self, prefix):
        return [t for t in self._tables if t.startswith(prefix)]

    def fetch_char_columns(self, prefix):
        return self._char

    def fetch_row_counts(self, prefix):
        return self._counts


def _opts(**kw):
    return Options(exclude_data_tables=["mdl_log"], large_table_threshold=1000, **kw)


def test_classify_splits_excluded_and_large():
    tables = ["mdl_user", "mdl_log", "mdl_question_attempts"]
    counts = {"mdl_user": 500, "mdl_log": 9, "mdl_question_attempts": 5000}
    char_cols = [("mdl_user", "username"), ("mdl_log", "action")]
    d = classify(tables, counts, char_cols, _opts())

    assert d.data_tables == ["mdl_question_attempts", "mdl_user"]  # sorted, log excluded
    assert d.schema_only_tables == ["mdl_log"]
    assert d.large_tables == ["mdl_question_attempts"]  # 5000 >= 1000
    # char columns only for data tables
    assert d.char_columns == {"mdl_user": ["username"]}


def test_include_tables_restricts_set():
    tables = ["mdl_user", "mdl_course", "mdl_log"]
    counts = {"mdl_user": 1, "mdl_course": 1, "mdl_log": 1}
    d = classify(tables, counts, [], _opts(include_tables=["mdl_user"]))
    assert d.data_tables == ["mdl_user"]
    assert d.schema_only_tables == []


def test_discover_uses_client_and_prefix():
    client = FakeClient(
        tables=["mdl_user", "other_table"],
        char_cols=[("mdl_user", "username")],
        counts={"mdl_user": 3},
    )
    d = discover(client, Options(exclude_data_tables=[]))
    assert d.data_tables == ["mdl_user"]  # non-mdl_ filtered out by prefix


def test_save_and_load_roundtrip(tmp_path):
    d = Discovered(
        data_tables=["mdl_user"],
        schema_only_tables=["mdl_log"],
        large_tables=[],
        char_columns={"mdl_user": ["username"]},
        row_counts={"mdl_user": 3, "mdl_log": 9},
    )
    path = str(tmp_path / "discovered.json")
    save_discovered(d, path)
    assert load_discovered(path) == d
    # file is valid JSON
    json.loads((tmp_path / "discovered.json").read_text())
