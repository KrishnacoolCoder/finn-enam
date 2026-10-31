"""Production ASGI entry point for FINN (Docker/Render).

Import this module (app.deploy:app), not app.main:app, so the seed is restored
BEFORE app.main initializes SQLite. The existing main.py stays untouched.
A secret-protected endpoint can trigger BSE synchronization on the *deployed*
instance; without the secret, external callers cannot trigger exchange calls.
"""
from __future__ import annotations

import os
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import Header, HTTPException, Query

from .seed_db import restore_seed

restore_seed()

from .main import app  # noqa: E402 - seed must be restored first
from .storage import connection  # noqa: E402
from .live_bse import IST, sync_bse  # noqa: E402


@app.get("/health", tags=["health"])
def deployment_health():
    """Return HTTP 200 only when SQLite is queryable."""
    try:
        with connection() as db:
            db.execute("SELECT 1").fetchone()
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Database unavailable") from exc
    return {"ok": True, "product": "FINN", "database": "ready"}


@app.post("/api/bse/live-sync", tags=["admin"])
def trigger_bse_live_sync(
    days: int = Query(default=3, ge=1, le=7),
    x_finn_sync_key: str | None = Header(default=None, alias="X-FINN-Sync-Key"),
):
    """Manual sync on Render. Requires FINN_BSE_SYNC_KEY in the environment.

    The unauthenticated public UI does not automatically poll BSE. A live API
    failure returns snapshot status and keeps previous filings in SQLite.
    """
    expected = os.environ.get("FINN_BSE_SYNC_KEY", "")
    if not expected:
        raise HTTPException(status_code=503, detail="BSE sync disabled; configure FINN_BSE_SYNC_KEY")
    if not x_finn_sync_key or not secrets.compare_digest(x_finn_sync_key, expected):
        raise HTTPException(status_code=403, detail="Invalid BSE sync key")
    end = datetime.now(IST).date()
    start = end - timedelta(days=days - 1)
    return sync_bse(start, end)
