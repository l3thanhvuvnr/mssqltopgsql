import pytest

from moodle_mssql2pg.generate import LoadFile
from moodle_mssql2pg.migrate import (
    MigrateError,
    State,
    migrate,
    order_load_files,
)


def _lf(name, kind):
    return LoadFile(filename=name, kind=kind, tables=[], content="")


def test_order_is_schema_then_data_then_large():
    files = [_lf("big.load", "large"), _lf("b1.load", "data"), _lf("s.load", "schema_only")]
    assert [f.filename for f in order_load_files(files)] == ["s.load", "b1.load", "big.load"]


class RecordingRunner:
    def __init__(self, fail_on=None):
        self.calls = []
        self.fail_on = fail_on

    def run(self, load_path, env, log_path):
        self.calls.append((load_path, env.get("TDSPORT")))
        return 1 if self.fail_on and self.fail_on in load_path else 0


def test_migrate_sets_tdsport_and_runs_in_order(tmp_path):
    files = [_lf("batch_1.load", "data"), _lf("batch_schema_only.load", "schema_only")]
    runner = RecordingRunner()
    ran = migrate(files, runner, tdsport=5968, out_dir=str(tmp_path))
    assert ran == ["batch_schema_only.load", "batch_1.load"]
    assert all(port == "5968" for _, port in runner.calls)


def test_migrate_resumes_and_skips_completed(tmp_path):
    files = [_lf("batch_1.load", "data"), _lf("batch_2.load", "data")]
    state = State(str(tmp_path / "state.json"))
    state.mark("batch_1.load")
    runner = RecordingRunner()
    ran = migrate(files, runner, tdsport=5968, out_dir=str(tmp_path), state=state)
    assert ran == ["batch_2.load"]


def test_migrate_raises_on_failure(tmp_path):
    files = [_lf("batch_1.load", "data")]
    runner = RecordingRunner(fail_on="batch_1")
    with pytest.raises(MigrateError) as exc:
        migrate(files, runner, tdsport=5968, out_dir=str(tmp_path))
    assert exc.value.filename == "batch_1.load"
