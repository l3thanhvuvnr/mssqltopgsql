import json
import os
import subprocess
from typing import Protocol

from moodle_mssql2pg.generate import LoadFile

_ORDER = {"schema_only": 0, "data": 1, "large": 2}


class PgloaderRunner(Protocol):
    def run(self, load_path: str, env: dict[str, str], log_path: str) -> int: ...


class MigrateError(Exception):
    def __init__(self, filename: str):
        super().__init__(f"pgloader thất bại ở file: {filename}")
        self.filename = filename


class State:
    def __init__(self, path: str):
        self.path = path
        self.done: set[str] = set()
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                self.done = set(json.load(fh))

    def is_done(self, name: str) -> bool:
        return name in self.done

    def mark(self, name: str) -> None:
        self.done.add(name)
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump(sorted(self.done), fh)


def order_load_files(load_files: list[LoadFile]) -> list[LoadFile]:
    return sorted(load_files, key=lambda lf: _ORDER[lf.kind])


class SubprocessPgloaderRunner:
    """Real runner: invokes the pgloader binary."""

    def __init__(self, pgloader_bin: str = "pgloader"):
        self.pgloader_bin = pgloader_bin

    def run(self, load_path: str, env: dict[str, str], log_path: str) -> int:
        with open(log_path, "w", encoding="utf-8") as log:
            proc = subprocess.run(
                [self.pgloader_bin, load_path],
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
        return proc.returncode


def migrate(
    load_files: list[LoadFile],
    runner: PgloaderRunner,
    tdsport: int,
    out_dir: str,
    state: State | None = None,
) -> list[str]:
    os.makedirs(out_dir, exist_ok=True)
    env = dict(os.environ)
    env["TDSPORT"] = str(tdsport)

    ran: list[str] = []
    for lf in order_load_files(load_files):
        if state and state.is_done(lf.filename):
            continue
        log_path = os.path.join(out_dir, f"{lf.filename}.log")
        code = runner.run(os.path.join(out_dir, lf.filename), env, log_path)
        if code != 0:
            raise MigrateError(lf.filename)
        if state:
            state.mark(lf.filename)
        ran.append(lf.filename)
    return ran
