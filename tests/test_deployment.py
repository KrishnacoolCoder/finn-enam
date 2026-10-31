"""Deployment regression tests; never require network or Docker."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.seed_db import restore_seed
from scripts.make_seed import make_seed


def _make_database(path: Path) -> None:
    with sqlite3.connect(path) as db:
        db.executescript("""
            CREATE TABLE filings (id INTEGER PRIMARY KEY, ticker TEXT, title TEXT,
                published TEXT, source TEXT, url TEXT);
            CREATE TABLE documents (id INTEGER PRIMARY KEY);
            CREATE TABLE chunks (id INTEGER PRIMARY KEY);
            CREATE TABLE preferences (key TEXT PRIMARY KEY, value TEXT);
            CREATE TABLE market_alerts (id INTEGER PRIMARY KEY);
            CREATE TABLE quarterly_financials (id INTEGER PRIMARY KEY);
            CREATE TABLE guidance_targets (id INTEGER PRIMARY KEY);
        """)
        db.execute("INSERT INTO filings VALUES(1,'NTPC','Original filing','2026-10-31',"
                   "'BSE official RSS snapshot',"
                   "'https://www.bseindia.com/xml-data/corpfiling/AttachLive/sample.pdf')")
        db.execute("INSERT INTO filings VALUES(2,'LT','Fictional','2026-10-31',"
                   "'synthetic_demo','')")
        db.execute("INSERT INTO documents VALUES(1)")
        db.execute("INSERT INTO chunks VALUES(1)")
        db.execute("INSERT INTO preferences VALUES('token','secret')")


def test_restore_seed_on_missing_db(tmp_path):
    seed, runtime = tmp_path / "seed.sqlite3", tmp_path / "runtime" / "finn.sqlite3"
    _make_database(seed)
    assert restore_seed(runtime, seed) is True
    with sqlite3.connect(runtime) as db:
        assert db.execute("SELECT COUNT(*) FROM filings").fetchone()[0] == 2


def test_restore_seed_never_overwrites_existing_database(tmp_path):
    seed, runtime = tmp_path / "seed.sqlite3", tmp_path / "runtime.sqlite3"
    _make_database(seed)
    _make_database(runtime)
    with sqlite3.connect(runtime) as db:
        db.execute("DELETE FROM filings")
    assert restore_seed(runtime, seed) is False
    with sqlite3.connect(runtime) as db:
        assert db.execute("SELECT COUNT(*) FROM filings").fetchone()[0] == 0


def test_missing_or_invalid_seed_is_rejected(tmp_path):
    with pytest.raises(FileNotFoundError):
        restore_seed(tmp_path / "runtime.sqlite3", tmp_path / "absent.sqlite3")
    invalid = tmp_path / "invalid.sqlite3"
    invalid.write_bytes(b"not a database")
    with pytest.raises(sqlite3.DatabaseError):
        restore_seed(tmp_path / "runtime.sqlite3", invalid)


def test_seed_sanitizes_synthetic_private_rows(tmp_path):
    runtime, seed = tmp_path / "live.sqlite3", tmp_path / "seed" / "finn.sqlite3"
    _make_database(runtime)
    assert make_seed(runtime, seed) == 1
    with sqlite3.connect(seed) as db:
        assert db.execute("SELECT COUNT(*) FROM filings").fetchone()[0] == 1
        assert db.execute("SELECT ticker FROM filings").fetchone()[0] == "NTPC"
        for table in ("documents", "chunks", "preferences", "market_alerts",
                      "quarterly_financials", "guidance_targets"):
            assert db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0


def test_health_route():
    from app.deploy import app
    with TestClient(app) as client:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["ok"] is True
        assert response.json()["database"] == "ready"
        assert client.get("/api/health").status_code == 200


def test_readme_metadata_preserves_content_and_is_idempotent(tmp_path):
    from scripts.prepare_hf_readme import prepare_readme
    path = tmp_path / "README.md"
    path.write_text("# My existing custom README\n", encoding="utf8")
    assert prepare_readme(path) is True
    assert "sdk: docker" in path.read_text(encoding="utf8")
    assert "app_port: 7860" in path.read_text(encoding="utf8")
    assert "# My existing custom README" in path.read_text(encoding="utf8")
    assert prepare_readme(path) is False


def test_restored_database_can_be_replaced_after_connection_closes(tmp_path):
    """Regression for WinError 32: temporary SQLite handles must be closed."""
    seed = tmp_path / "seed.sqlite3"
    live = tmp_path / "data" / "finn.sqlite3"
    _make_database(seed)
    assert restore_seed(live, seed) is True
    assert restore_seed(live, seed) is False
    assert not list(live.parent.glob(".finn-seed-*.sqlite3"))
    with sqlite3.connect(live) as db:
        assert db.execute("PRAGMA quick_check").fetchone()[0] == "ok"


def test_seed_regeneration_replaces_an_existing_seed(tmp_path):
    """Windows permits os.replace only after all SQLite handles are closed."""
    runtime = tmp_path / "live.sqlite3"
    seed = tmp_path / "seed" / "finn.sqlite3"
    _make_database(runtime)
    assert make_seed(runtime, seed) == 1
    assert make_seed(runtime, seed) == 1
    assert not list(seed.parent.glob(".finn-public-seed-*.sqlite3"))
    with sqlite3.connect(seed) as db:
        assert db.execute("SELECT COUNT(*) FROM filings").fetchone()[0] == 1
