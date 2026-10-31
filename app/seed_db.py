"""Restore a checked seed SQLite database before FINN initializes its runtime DB.

The committed seed remains unchanged. An existing runtime database is never
intentionally overwritten. Hugging Face Spaces' normal container disk is not
persistent, so data written after startup may disappear after restart.
"""
from __future__ import annotations

import os
import shutil
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEED = ROOT / "seed" / "finn.sqlite3"


def runtime_database_path() -> Path:
    data_dir = Path(os.environ.get("FINN_DATA_DIR", str(ROOT / "data"))).expanduser()
    return data_dir / "finn.sqlite3"


def _check_database(path: Path) -> None:
    """Validate SQLite structure and integrity, closing the handle on Windows."""
    uri = f"file:{path.resolve().as_posix()}?mode=ro"
    # `with sqlite3.connect(...)` manages a transaction, NOT connection close.
    # `closing` is essential before renaming/deleting the temporary DB on Windows.
    with closing(sqlite3.connect(uri, uri=True)) as db:
        result = db.execute("PRAGMA quick_check").fetchone()
        if result is None or result[0] != "ok":
            raise ValueError("FINN seed failed SQLite integrity check")
        tables = {
            row[0]
            for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        if not {"filings", "documents", "chunks", "preferences"}.issubset(tables):
            raise ValueError("FINN seed is missing required tables")


def restore_seed(target: Path | None = None, source: Path | None = None) -> bool:
    """Copy seed on first start; return True only when a new DB is installed."""
    target = Path(target) if target is not None else runtime_database_path()
    source = Path(source) if source is not None else SEED

    if target.exists():
        return False
    if not source.is_file():
        raise FileNotFoundError(
            f"FINN seed missing: {source}. Generate seed/finn.sqlite3 before deployment."
        )

    _check_database(source)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=".finn-seed-", suffix=".sqlite3", dir=target.parent
    )
    os.close(fd)

    try:
        shutil.copyfile(source, tmp_name)
        _check_database(Path(tmp_name))

        # One Uvicorn worker is used by the Dockerfile. If an existing DB was
        # created since the first check, do not intentionally replace it.
        if target.exists():
            return False
        os.replace(tmp_name, target)
        return True
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
