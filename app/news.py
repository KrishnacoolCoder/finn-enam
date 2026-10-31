"""Secondary-source headline metadata only. Never used by document research."""
from __future__ import annotations

import calendar
import html
import re
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from urllib.parse import urlparse

import requests
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .core import PORTFOLIO
from .ingestion import require_token
from .storage import connection

RSS_URL = 'https://news.google.com/rss/search'
MAX_FEED_BYTES = 2 * 1024 * 1024
TICKERS = {ticker for ticker, _, _ in PORTFOLIO}
router = APIRouter()


class NewsItem(BaseModel):
    model_config = ConfigDict(extra='forbid')
    ticker: str
    title: str = Field(min_length=1, max_length=500)
    source: str = Field(min_length=1, max_length=200)
    published: datetime
    link: str = Field(min_length=1, max_length=2048)

    @field_validator('ticker')
    @classmethod
    def company(cls, value):
        value = value.strip().upper()
        if value not in TICKERS:
            raise ValueError('News must belong to a portfolio company')
        return value

    @field_validator('title', 'source')
    @classmethod
    def text(cls, value):
        value = ' '.join(html.unescape(re.sub(r'<[^>]*>', ' ', value)).split())
        if not value:
            raise ValueError('Empty metadata')
        return value

    @field_validator('published')
    @classmethod
    def timestamp(cls, value):
        if value.tzinfo is None:
            raise ValueError('Publication time must include timezone')
        return value.astimezone(timezone.utc)

    @field_validator('link')
    @classmethod
    def https_link(cls, value):
        parsed = urlparse(value)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError('An HTTPS news link is required')
        return value


def same_headline(left, right):
    def normalized(title):
        return ' '.join(re.findall(r'\w+', title.casefold()))
    a, b = normalized(left), normalized(right)
    # Distinct numbers/quarters must not disappear as fuzzy duplicates.
    if re.findall(r'\d+', a) != re.findall(r'\d+', b):
        return False
    return a == b or SequenceMatcher(None, a, b, autojunk=False).ratio() >= .90


def store_news(items):
    added = duplicates = 0
    with closing(connection()) as db:
        db.execute('BEGIN IMMEDIATE')
        with db:
            for item in items:
                stamp = item.published.isoformat()
                low = (item.published - timedelta(hours=72)).isoformat()
                high = (item.published + timedelta(hours=72)).isoformat()
                old = db.execute('SELECT title FROM news WHERE ticker=? AND '
                                 '(link=? OR published BETWEEN ? AND ?)',
                                 (item.ticker, item.link, low, high)).fetchall()
                if any(same_headline(item.title, row['title']) for row in old):
                    duplicates += 1
                    continue
                cur = db.execute('INSERT OR IGNORE INTO news(ticker,title,source,published,link) '
                                 'VALUES (?,?,?,?,?)',
                                 (item.ticker, item.title, item.source, stamp, item.link))
                added += cur.rowcount
                duplicates += 1 - cur.rowcount
    return {'received': len(items), 'added': added, 'duplicates': duplicates}


def fetch_company(ticker, company, session):
    # Fetch RSS bytes with a timeout and size limit; never fetch article links.
    import feedparser
    with session.get(RSS_URL, params={'q': company + ' NSE', 'hl': 'en-IN',
                                    'gl': 'IN', 'ceid': 'IN:en'},
                     timeout=(4, 8), stream=True) as response:
        response.raise_for_status()
        chunks, size = [], 0
        for chunk in response.iter_content(65536):
            size += len(chunk)
            if size > MAX_FEED_BYTES:
                raise ValueError('News feed too large')
            chunks.append(chunk)
    feed = feedparser.parse(b''.join(chunks))
    if feed.bozo or not feed.version:
        raise ValueError('Invalid news RSS')
    output = []
    for entry in feed.entries[:50]:
        try:
            source = entry.get('source', {}).get('title', '')
            title = entry.get('title', '')
            suffix = ' - ' + source
            if source and title.endswith(suffix):
                title = title[:-len(suffix)]
            stamp = entry.get('published_parsed') or entry.get('updated_parsed')
            if not stamp:
                continue
            output.append(NewsItem(ticker=ticker, title=title, source=source,
                                  published=datetime.fromtimestamp(calendar.timegm(stamp), timezone.utc),
                                  link=entry.get('link', '')))
        except (ValueError, TypeError, OverflowError):
            continue
    return output


def sync_news(portfolio=None, session=None):
    """Each company fails independently; no article bodies are read or stored."""
    totals = {'received': 0, 'added': 0, 'duplicates': 0, 'errors': []}
    own_session = session is None
    try:
        active = session if session is not None else requests.Session()
        for ticker, company, _ in (PORTFOLIO if portfolio is None else portfolio):
            try:
                result = store_news(fetch_company(ticker, company, active))
                for key in ('received', 'added', 'duplicates'):
                    totals[key] += result[key]
            except Exception as exc:
                totals['errors'].append({'ticker': ticker, 'error': type(exc).__name__})
    except Exception as exc:
        totals['errors'].append({'error': type(exc).__name__})
    finally:
        if own_session and 'active' in locals():
            try:
                active.close()
            except Exception:
                pass
    return totals


@router.get('/api/news')
def list_news(ticker: str | None = None, hours: int = Query(168, ge=1, le=8760),
              limit: int = Query(1000, ge=1, le=1000)):
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    params = [cutoff]
    sql = 'SELECT ticker,title,source,published,link FROM news WHERE published>=?'
    if ticker:
        sql += ' AND ticker=?'
        params.append(ticker.strip().upper())
    try:
        with closing(connection()) as db:
            return [dict(row) for row in db.execute(sql + ' ORDER BY published DESC LIMIT ?',
                                                   (*params, limit))]
    except sqlite3.Error:
        return []


@router.post('/api/ingest/news', dependencies=[Depends(require_token)])
def ingest_news(items: list[NewsItem]):
    if len(items) > 5000:
        raise HTTPException(413, 'Maximum 5000 news items per batch')
    return store_news(items)
