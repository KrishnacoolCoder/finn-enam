"""Make a small public seed from existing source-backed BSE filings.

Only BSE RSS snapshot filings with official HTTPS URLs are retained.
Documents, chunks, settings, financial figures and market alerts are removed.
No real data is invented. SQLite's backup API safely snapshots WAL databases.

Usage from the project root:
    python scripts/make_seed.py
    python scripts/make_seed.py --source-db C:/path/to/finn.sqlite3
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = Path(os.environ.get("FINN_DATA_DIR", str(ROOT / "data"))) / "finn.sqlite3"
DEFAULT_DESTINATION = ROOT / "seed" / "finn.sqlite3"
CLEAR_TABLES = (
    "chunks", "documents", "preferences", "market_alerts",
    "quarterly_financials", "guidance_targets",
)


def is_official_filings_source(row: sqlite3.Row) -> bool:
    parsed = urlparse(row["url"] or "")
    return (
        row["source"] == "BSE official RSS snapshot"
        and parsed.scheme == "https"
        and parsed.hostname in {"www.bseindia.com", "bseindia.com"}
    )


def make_seed(source: Path, destination: Path, max_filings: int = 40) -> int:
    source, destination = Path(source), Path(destination)
    if not source.is_file():
        raise FileNotFoundError(f"Live database missing: {source}")
    if source.resolve() == destination.resolve():
        raise ValueError("Source and destination must be different files")
    if not 1 <= max_filings <= 200:
        raise ValueError("max_filings must be between 1 and 200")

    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=".finn-public-seed-", suffix=".sqlite3", dir=destination.parent
    )
    os.close(fd)

    try:
        # Explicitly close both SQLite connections before replacing files.
        with closing(sqlite3.connect(str(source))) as current:
            with closing(sqlite3.connect(tmp_name)) as public:
                current.backup(public)

        with closing(sqlite3.connect(tmp_name)) as public:
            public.row_factory = sqlite3.Row
            original = public.execute(
                "SELECT id,source,url FROM filings ORDER BY published DESC,id DESC"
            ).fetchall()
            allowed = [
                row["id"] for row in original if is_official_filings_source(row)
            ][:max_filings]
            if not allowed:
                raise ValueError(
                    "No BSE source-backed filings with official HTTPS links found. "
                    "Import the original BSE snapshot first; do not create fictional data."
                )

            # The row deletion and table clearing are one transaction.
            with public:
                public.execute(
                    "DELETE FROM filings WHERE id NOT IN ("
                    + ",".join("?" for _ in allowed) + ")",
                    allowed,
                )
                existing_tables = {
                    row[0]
                    for row in public.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    )
                }
                for table in CLEAR_TABLES:
                    if table in existing_tables:
                        public.execute(f"DELETE FROM {table}")

            # VACUUM needs a connection with no pending transaction.
            public.execute("VACUUM")
            result = public.execute("PRAGMA integrity_check").fetchone()[0]
            if result != "ok":
                raise ValueError(f"Seed integrity check failed: {result}")
            retained = public.execute("SELECT COUNT(*) FROM filings").fetchone()[0]

        # All SQLite handles to tmp_name have been closed at this point.
        os.replace(tmp_name, destination)
        return retained
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-db", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--out", type=Path, default=DEFAULT_DESTINATION)
    parser.add_argument("--max-filings", type=int, default=40)
    arguments = parser.parse_args()
    count = make_seed(arguments.source_db, arguments.out, arguments.max_filings)
    print(f"Saved {count} genuine BSE-linked filings to {arguments.out}")
    print(f"Seed size: {arguments.out.stat().st_size:,} bytes")
    print("Review the records and URLs before publishing this file publicly.")


if __name__ == "__main__":
    main()
