"""Public Screener numeric snapshots. Never inserted into primary-source research."""
from __future__ import annotations

import json
import re
import sqlite3
import threading
from contextlib import closing
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup
from fastapi import APIRouter, HTTPException, Query

from .storage import connection

router = APIRouter()
CACHE_HOURS = 6
MAX_BYTES = 2 * 1024 * 1024
_lock = threading.RLock()
_failures = {}


def text(node, limit=200):
    return ' '.join(node.get_text(' ', strip=True).split())[:limit] if node else ''


def parse_snapshot(raw, ticker, basis, url):
    soup = BeautifulSoup(raw, 'html.parser')
    for tag in soup(['script', 'style', 'sup']):
        tag.decompose()
    identity = soup.select_one('#company-info')
    if identity is None:
        raise ValueError('Company page unavailable or layout changed')
    label = text(soup.select_one('#quarters'), 200)
    match = re.search(r'Quarterly Results\s+(Standalone|Consolidated)\b', label)
    if not match:
        raise ValueError('Reporting basis unavailable')
    actual_basis = match.group(1).lower()
    if actual_basis != basis:
        raise ValueError('Requested reporting basis not available')
    ratios = []
    for row in soup.select('#top-ratios li')[:16]:
        name, value = text(row.select_one('.name')), text(row.select_one('.value'))
        if name and value:
            ratios.append({'name': name, 'value': value})
    table = soup.select_one('#quarters table')
    periods, rows = [], []
    if table:
        headers = table.select('thead th') or table.select('tr:first-child th')
        all_periods = [text(th, 40) for th in headers][1:]
        # Preserve reported labels/units, blanks and signs; no invented EBITDA/PAT mapping.
        if not all_periods or len(all_periods) > 40:
            raise ValueError('Quarter headers unavailable')
        first = max(0, len(all_periods) - 5)
        periods = all_periods[first:]
        for row in table.select('tbody tr'):
            cells = row.find_all('td', recursive=False)
            if not cells:
                continue
            label = text(cells[0]).rstrip('+ ').strip()
            if label == 'Raw PDF':
                continue
            values = [text(cell, 60) for cell in cells[1:]]
            if len(values) != len(all_periods):
                raise ValueError('Quarter table shape changed')
            rows.append({'metric': label, 'values': values[first:]})
    if not ratios or not rows:
        raise ValueError('Public financial snapshot missing')
    return {'ticker': ticker, 'company': text(soup.select_one('h1'), 150),
            'basis': actual_basis, 'source': 'Screener.in', 'source_url': url,
            'fetched_at': datetime.now(timezone.utc).isoformat(), 'ratios': ratios,
            'periods': periods, 'quarterly_rows': rows,
            'unit_note': 'Rs crore except percentages and per-share figures; labels as reported by Screener.',
            'verification': 'Unverified secondary source',
            'note': 'Display only. Not used in document Q&A, reviewed quarterly observations, or guidance verdicts. Fetch time is not the market-data time.'}


def fetch_snapshot(ticker, basis):
    suffix = '/consolidated/' if basis == 'consolidated' else '/'
    url = 'https://www.screener.in/company/' + quote(ticker, safe='') + suffix
    # Only public HTML. No login, challenge handling, or hidden endpoints.
    with requests.get(url, timeout=(4, 12), stream=True, allow_redirects=False,
                      headers={'User-Agent': 'FINN/1.0 public-company-context'}) as response:
        if response.status_code != 200:
            raise ValueError(f'Public company page returned HTTP {response.status_code}')
        if 'text/html' not in response.headers.get('Content-Type', ''):
            raise ValueError('Expected public company HTML')
        size, parts = 0, []
        for chunk in response.iter_content(65536):
            size += len(chunk)
            if size > MAX_BYTES:
                raise ValueError('Company page exceeds size limit')
            parts.append(chunk)
    return parse_snapshot(b''.join(parts), ticker, basis, url)


def snapshot(ticker, basis='consolidated'):
    ticker = ticker.strip().upper().removesuffix('.NS').removesuffix('.BO')
    if not re.fullmatch(r'[A-Z0-9&_-]{1,25}', ticker):
        raise HTTPException(400, 'Invalid ticker')
    if basis not in ('standalone', 'consolidated'):
        raise HTTPException(400, 'Invalid reporting basis')
    key = (ticker, basis)
    with _lock:
        cached = None
        try:
            with closing(connection()) as db:
                row = db.execute('SELECT payload FROM company_context WHERE ticker=? AND basis=?', key).fetchone()
            if row:
                cached = json.loads(row['payload'])
                if datetime.now(timezone.utc) - datetime.fromisoformat(cached['fetched_at']) < timedelta(hours=CACHE_HOURS):
                    return {**cached, 'status': 'cached', 'stale': False}
        except (sqlite3.Error, ValueError, KeyError, TypeError):
            cached = None
        failed_at = _failures.get(key)
        if failed_at and datetime.now(timezone.utc) - failed_at < timedelta(minutes=5):
            return {**(cached or {}), 'ticker': ticker, 'basis': basis,
                    'status': 'stale' if cached else 'unavailable', 'stale': bool(cached),
                    'error': 'Screener is temporarily unavailable; retry after five minutes.'}
        try:
            data = fetch_snapshot(ticker, basis)
            try:
                with closing(connection()) as db, db:
                    db.execute('INSERT OR REPLACE INTO company_context VALUES (?,?,?,?)',
                               (*key, json.dumps(data), data['fetched_at']))
            except sqlite3.Error:
                pass  # Display fetched data even if cache persistence fails.
            _failures.pop(key, None)
            return {**data, 'status': 'fetched', 'stale': False}
        except (requests.RequestException, ValueError, OSError):
            _failures[key] = datetime.now(timezone.utc)
            return {**(cached or {}), 'ticker': ticker, 'basis': basis,
                    'status': 'stale' if cached else 'unavailable', 'stale': bool(cached),
                    'error': 'Screener could not be fetched. Other FINN features remain available.'}


@router.get('/api/company-context/{ticker}')
def company_context(ticker: str, basis: str = Query('consolidated', pattern='^(standalone|consolidated)$')):
    return snapshot(ticker, basis)
