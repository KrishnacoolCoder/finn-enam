from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app import storage
from app.main import app
import collector

ITEM = {'ticker': 'NTPC', 'title': 'Quarterly financial results',
        'published': '2026-11-01T10:00:00+05:30',
        'url': 'https://www.bseindia.com/xml-data/corpfiling/AttachLive/test.pdf',
        'source': 'BSE official live RSS'}
HEADERS = {'X-Ingest-Token': 'test-secret'}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, 'DB', tmp_path / 'runtime.sqlite3')
    storage.init()
    monkeypatch.setenv('INGEST_TOKEN', 'test-secret')
    with TestClient(app) as client:
        yield client


def count():
    with closing(storage.connection()) as db:
        return db.execute('SELECT COUNT(*) FROM filings').fetchone()[0]


@pytest.mark.parametrize('headers', [{}, {'X-Ingest-Token': 'wrong'}])
def test_token_rejected(client, headers):
    assert client.post('/api/ingest', json=[ITEM], headers=headers).status_code == 403
    assert count() == 0
    assert client.get('/api/ingest/status').json()['last_updated'] is None


def test_unconfigured_token(client, monkeypatch):
    monkeypatch.delenv('INGEST_TOKEN')
    assert client.post('/api/ingest', json=[ITEM], headers=HEADERS).status_code == 503


def test_idempotency_and_url_identity(client):
    first = client.post('/api/ingest', json=[ITEM, ITEM], headers=HEADERS).json()
    assert (first['added'], first['duplicates']) == (1, 1)
    changed = dict(ITEM, title='Revised headline', published='2026-11-01T04:30:00Z')
    second = client.post('/api/ingest', json=[changed], headers=HEADERS).json()
    assert (second['added'], second['duplicates'], count()) == (0, 1, 1)
    assert client.get('/api/ingest/status').json()['source'] == 'live'
    with closing(storage.connection()) as db:
        assert db.execute('SELECT score FROM filings').fetchone()[0] > 0


def test_parallel_replay(client):
    def upload(_):
        return client.post('/api/ingest', json=[ITEM], headers=HEADERS).json()
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(upload, range(4)))
    assert sum(r['added'] for r in results) == 1
    assert count() == 1


def test_invalid_batch_is_atomic(client):
    response = client.post('/api/ingest', json=[ITEM, dict(ITEM, published='bad')], headers=HEADERS)
    assert response.status_code == 422
    assert count() == 0


def test_snapshot_and_empty_preserve_timestamp(client):
    before = client.post('/api/ingest', json=[ITEM], headers=HEADERS).json()['last_updated']
    result = client.post('/api/ingest', json=[ITEM], headers={**HEADERS, 'X-Ingest-Source': 'snapshot'}).json()
    assert result['last_updated'] == before and result['source'] == 'snapshot'
    result = client.post('/api/ingest', json=[], headers=HEADERS).json()
    assert result['source'] == 'snapshot' and result['last_updated'] == before


def test_seed_export_wal_and_restore(client, tmp_path):
    with closing(storage.connection()) as db:
        db.execute('PRAGMA journal_mode=WAL')
        client.post('/api/ingest', json=[ITEM], headers=HEADERS)
        target = tmp_path / 'seed.sqlite3'
        collector.export_seed(target)
        with closing(sqlite3.connect(target)) as seed:
            assert seed.execute('SELECT COUNT(*) FROM filings').fetchone()[0] == 1
            status = json.loads(seed.execute("SELECT value FROM preferences WHERE key='feed_status'").fetchone()[0])
            assert status['source'] == 'snapshot' and status['last_updated']
    from app.seed_db import restore_seed
    restored = tmp_path / 'restored.sqlite3'
    assert restore_seed(restored, target)


def test_collector_exports_even_when_upload_fails(client, tmp_path, monkeypatch):
    from app import live_bse
    client.post('/api/ingest', json=[ITEM], headers=HEADERS)
    from app import automatic_feed
    monkeypatch.setattr(automatic_feed, 'sync_sources', lambda **kwargs: {'source': 'snapshot'})
    class Session:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def post(self, url, **kwargs):
            assert kwargs['headers']['X-Ingest-Token'] == 'test-secret'
            assert kwargs['headers']['X-Ingest-Source'] == 'snapshot'
            assert len(kwargs['json']) == 1
            assert kwargs['allow_redirects'] is False
            return type('Response', (), {'status_code': 503})()
    monkeypatch.setattr(collector.requests, 'Session', Session)
    target = tmp_path / 'seed.sqlite3'
    with pytest.raises(RuntimeError, match='HTTP 503'):
        collector.run_once('https://example.com/api/ingest', 'test-secret', seed=target)
    assert target.exists()


def test_destination():
    assert collector.destination('https://example.com/') == 'https://example.com/api/ingest'
    assert collector.destination('http://localhost:7860/api/ingest') == 'http://localhost:7860/api/ingest'
    for url in ['http://example.com', 'https://user:pass@example.com', 'https://example.com/?token=secret']:
        with pytest.raises(ValueError): collector.destination(url)
