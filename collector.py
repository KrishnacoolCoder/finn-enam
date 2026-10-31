"""Collect on the laptop, back up SQLite, then upload to FINN."""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import tempfile
import time
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import requests

from app import storage
from app.seed_db import SEED, restore_seed, _check_database


def export_seed(target=SEED):
    """Online SQLite backup includes committed WAL data; atomic Windows replacement."""
    target = Path(target).resolve()
    if target == storage.DB.resolve():
        raise ValueError('Seed destination must differ from runtime database')
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.collector-', suffix='.sqlite3', dir=target.parent)
    os.close(fd)
    try:
        with closing(storage.connection()) as source, closing(sqlite3.connect(name)) as dest:
            source.backup(dest)
            # Restored data is a snapshot, even if collected live before export.
            row = dest.execute("SELECT value FROM preferences WHERE key='feed_status'").fetchone()
            status = json.loads(row[0]) if row else {'last_updated': None, 'last_attempt': None}
            status['source'] = 'snapshot'
            dest.execute('INSERT OR REPLACE INTO preferences VALUES (?,?)',
                         ('feed_status', json.dumps(status)))
            dest.commit()
        _check_database(Path(name))
        os.replace(name, target)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def destination(value):
    parsed = urlsplit(value)
    if (not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment
        or (parsed.scheme != 'https' and not (
            parsed.scheme == 'http' and parsed.hostname in {'localhost', '127.0.0.1', '::1'}))):
        raise ValueError('Use an HTTPS app URL (HTTP allowed for localhost only)')
    path = parsed.path.rstrip('/')
    if not path.endswith('/api/ingest'):
        path += '/api/ingest'
    return urlunsplit((parsed.scheme, parsed.netloc, path, '', ''))


def run_once(url, token, *, days=30, seed=SEED):
    from app.automatic_feed import sync_sources
    result = sync_sources(days=days)
    now = datetime.now(timezone.utc).isoformat()
    previous = json.loads(storage.get_setting('feed_status', '{"last_updated": null}'))
    if result['source'] == 'live':
        previous['last_updated'] = now
    previous.update(last_attempt=now, source=result['source'])
    storage.set_setting('feed_status', json.dumps(previous))
    # News is optional context; neither collection nor upload may break filings.
    news_result = {'errors': []}
    try:
        from app.news import sync_news
        news_result = sync_news()
    except Exception as exc:
        news_result['errors'].append({'error': type(exc).__name__})
    # Export before upload so a host outage cannot prevent the local backup.
    export_seed(seed)
    with closing(storage.connection()) as db:
        rows = [dict(row) for row in db.execute('''SELECT ticker,title,published,url,source,excerpt
            FROM filings WHERE url LIKE 'https://%' AND source != 'synthetic_demo'
            ORDER BY id''')]
    totals = {'added': 0, 'duplicates': 0}
    # Replay local history as well as today's rows: repairs missed uploads/restarts.
    batches = [rows[i:i + 500] for i in range(0, len(rows), 500)] or [[]]
    with requests.Session() as session:
        for batch in batches:
            response = session.post(url, json=batch, headers={
                'X-Ingest-Token': token, 'X-Ingest-Source': result['source']
            }, timeout=(5, 60), allow_redirects=False)
            if not 200 <= response.status_code < 300:
                raise RuntimeError(f'Upload failed (HTTP {response.status_code}); local seed exported')
            body = response.json()
            for key in totals:
                totals[key] += body[key]
        try:
            with closing(storage.connection()) as db:
                news_rows = [dict(row) for row in db.execute('''SELECT ticker,title,source,published,link
                    FROM news ORDER BY published DESC LIMIT 5000''')]
            news_result['uploaded'] = 0
            for start in range(0, len(news_rows), 500):
                batch = news_rows[start:start + 500]
                response = session.post(url.rstrip('/') + '/news', json=batch,
                    headers={'X-Ingest-Token': token}, timeout=(5, 60), allow_redirects=False)
                if not 200 <= response.status_code < 300:
                    raise RuntimeError(f'News upload HTTP {response.status_code}')
                news_result['uploaded'] += len(batch)
        except Exception as exc:
            news_result['errors'].append({'upload_error': type(exc).__name__})
    return {'collection': result, 'upload': totals, 'news': news_result, 'seed': str(seed)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('url', help='Deployed app base URL or /api/ingest URL')
    parser.add_argument('--loop', type=float, metavar='MINUTES', help='Repeat; e.g. --loop 15')
    parser.add_argument('--days', type=int, default=30)
    parser.add_argument('--seed', type=Path, default=SEED)
    args = parser.parse_args(argv)
    if args.loop is not None and (not 0 < args.loop < float('inf')):
        parser.error('--loop must be a positive finite number of minutes')
    if not 1 <= args.days <= 31:
        parser.error('--days must be between 1 and 31')
    token = os.environ.get('INGEST_TOKEN', '')
    if not token:
        parser.error('Set INGEST_TOKEN in your environment')
    try:
        url = destination(args.url)
    except ValueError as exc:
        parser.error(str(exc))
    restore_seed()
    storage.init()
    try:
        while True:
            try:
                print(json.dumps(run_once(url, token, days=args.days, seed=args.seed), indent=2), flush=True)
            except (requests.RequestException, RuntimeError, ValueError, OSError, sqlite3.Error) as exc:
                # Do not print request objects, headers, or secrets.
                print(f'Collector cycle failed: {type(exc).__name__}; local data retained.', flush=True)
                if args.loop is None:
                    return 1
            if args.loop is None:
                return 0
            time.sleep(args.loop * 60)
    except KeyboardInterrupt:
        return 0


if __name__ == '__main__':
    raise SystemExit(main())
