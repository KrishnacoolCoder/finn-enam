"""Deployment ASGI entry point.

Import this module (app.deploy:app), not app.main:app, so the seed is copied
BEFORE app.main calls init() at import time. Existing app/main.py is unchanged.
"""
from __future__ import annotations

from fastapi import HTTPException

from .seed_db import restore_seed

restore_seed()

from .main import app  # noqa: E402 - the seed must be restored first
from .storage import connection  # noqa: E402


@app.get("/health", tags=["health"])
def deployment_health():
    """Return 200 only if the app can query its SQLite database."""
    try:
        with connection() as db:
            db.execute("SELECT 1").fetchone()
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Database unavailable") from exc
    return {"ok": True, "product": "FINN", "database": "ready"}
