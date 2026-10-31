"""Authenticated laptop uploads and durable feed freshness metadata."""
from __future__ import annotations

import json
import os
import re
import secrets
from contextlib import closing
from datetime import datetime, timezone
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field, field_validator

from .core import classify, excerpt
from .storage import connection

router = APIRouter()


def require_token(x_ingest_token: str | None = Header(default=None)):
    expected = os.environ.get('INGEST_TOKEN', '')
    if not expected:
        raise HTTPException(503, 'Ingestion disabled; configure INGEST_TOKEN')
    if not x_ingest_token or not secrets.compare_digest(
        x_ingest_token.encode(), expected.encode()
    ):
        raise HTTPException(403, 'Invalid ingestion token')


class Announcement(BaseModel):
    ticker: str = Field(min_length=1, max_length=25)
    title: str = Field(min_length=1, max_length=500)
    published: datetime
    url: str = Field(min_length=1, max_length=2048)
    source: str = Field(default='laptop collector', max_length=120)
    excerpt: str = Field(default='', max_length=4000)
    description: str = Field(default='', max_length=4000)

    @field_validator('ticker')
    @classmethod
    def ticker_valid(cls, value):
        value = value.strip().upper().removesuffix('.NS').removesuffix('.BO')
        if not re.fullmatch(r'[A-Z0-9&_-]{1,25}', value):
            raise ValueError('Invalid ticker')
        return value

    @field_validator('title')
    @classmethod
    def title_valid(cls, value):
        if not value.strip():
            raise ValueError('Title must not be blank')
        return value.strip()

    @field_validator('published')
    @classmethod
    def date_valid(cls, value):
        if value.tzinfo is None:
            raise ValueError('published requires a timezone')
        return value.astimezone(timezone.utc)

    @field_validator('url')
    @classmethod
    def url_valid(cls, value):
        parsed = urlparse(value)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError('An HTTPS source URL is required')
        return value


def read_status():
    with closing(connection()) as db:
        row = db.execute("SELECT value FROM preferences WHERE key='feed_status'").fetchone()
    return json.loads(row['value']) if row else {
        'last_updated': None, 'last_attempt': None, 'source': 'snapshot'
    }


@router.get('/api/ingest/status')
def feed_status():
    return read_status()


@router.post('/api/ingest', dependencies=[Depends(require_token)])
def ingest_announcements(
    announcements: list[Announcement],
    x_ingest_source: str = Header(default='live', pattern='^(live|snapshot)$'),
):
    if len(announcements) > 5000:
        raise HTTPException(413, 'Maximum 5000 announcements per batch')
    added = duplicates = 0
    now = datetime.now(timezone.utc).isoformat()
    with closing(connection()) as db:
        # Serialize the URL check and insert across simultaneous uploads/workers.
        db.execute('BEGIN IMMEDIATE')
        with db:
            for item in announcements:
                old = db.execute('SELECT 1 FROM filings WHERE ticker=? AND url=?',
                                 (item.ticker, item.url)).fetchone()
                if old:
                    duplicates += 1
                    continue
                detail = item.description or item.excerpt
                category, score = classify(item.title, detail)
                cursor = db.execute('''INSERT OR IGNORE INTO filings
                    (ticker,published,title,url,category,score,source,excerpt)
                    VALUES (?,?,?,?,?,?,?,?)''',
                    (item.ticker, item.published.isoformat(), item.title, item.url,
                     category, score, item.source, excerpt(detail)))
                added += cursor.rowcount
                duplicates += 1 - cursor.rowcount
            row = db.execute("SELECT value FROM preferences WHERE key='feed_status'").fetchone()
            status = json.loads(row['value']) if row else {'last_updated': None}
            # Timestamp means last successful live collection, including duplicates.
            # Replaying a snapshot or an empty fallback never makes it fresh.
            if announcements and x_ingest_source == 'live':
                status['last_updated'] = now
            status.update(last_attempt=now, source=x_ingest_source if announcements else 'snapshot')
            db.execute('INSERT OR REPLACE INTO preferences VALUES (?,?)',
                       ('feed_status', json.dumps(status)))
    return {'received': len(announcements), 'added': added,
            'duplicates': duplicates, **status}
