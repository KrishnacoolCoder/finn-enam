"""All mock-only tests: never contact BSE or alter the real FINN database."""
from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import date

import pytest
import requests

from app import live_bse


class Response:
    def __init__(self, payload=None, status=200):
        self.payload, self.status = payload, status

    def raise_for_status(self):
        if self.status >= 400:
            raise requests.HTTPError(f"{self.status} Forbidden")

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, pages=None, fail_for=None):
        self.pages = pages or {}
        self.fail_for = fail_for
        self.calls = []

    def get(self, url, *, params, timeout):
        self.calls.append((url, dict(params), timeout))
        assert url.endswith('/AnnGetData/w')
        if self.fail_for == params['strScrip']:
            return Response(status=403)
        return Response(self.pages.get((params['strScrip'], params['pageno']),
                                       {'Table': [], 'Table1': [{'ROWCNT': 0}]}))


def _row(*, code='532555', attachment=None, url=None, title='Unaudited Financial Results for quarter ended September 2026'):
    record = {
        'SCRIP_CD': code,
        'NEWSSUB': title,
        'HEADLINE': 'Results for the quarter ended September 2026',
        'DissemDT': '2026-10-31T15:35:47',
        'ATTACHMENTNAME': attachment or 'ntpc-filing.pdf',
    }
    if url:
        record['PDF_LINK'] = url
    return record


@pytest.fixture()
def isolated_db(tmp_path, monkeypatch):
    db_path = tmp_path / 'filings.sqlite3'
    def connect():
        db = sqlite3.connect(db_path)
        db.row_factory = sqlite3.Row
        return db
    with closing(connect()) as db:
        db.execute('''CREATE TABLE filings (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          ticker TEXT NOT NULL, published TEXT NOT NULL,
          title TEXT NOT NULL, url TEXT DEFAULT '', category TEXT NOT NULL,
          score INTEGER NOT NULL, source TEXT NOT NULL DEFAULT 'user',
          excerpt TEXT DEFAULT '', UNIQUE(ticker,published,title))''')
        db.commit()
    monkeypatch.setattr(live_bse, 'connection', connect)
    portfolio = tmp_path / 'portfolio.json'
    portfolio.write_text(json.dumps({'NTPC': '532555'}), encoding='utf-8')
    return connect, portfolio


def test_success_uses_existing_classifier_grouping_and_preserves_pdf(isolated_db):
    connect, portfolio = isolated_db
    direct = 'https://www.bseindia.com/xml-data/corpann/official-filing.pdf'
    fake = FakeSession({('532555', 1): {'Table': [_row(url=direct)],
                                       'Table1': [{'ROWCNT': 1}]}})
    result = live_bse.sync_bse('2026-10-30', '2026-10-31', portfolio_file=portfolio, session=fake)
    assert (result['source'], result['added'], result['grouped_events']) == ('live', 1, 1)
    assert result['error'] is None and result['derived_pdf_urls'] == 0
    assert fake.calls[0][1]['strPrevDate'] == '20261030'
    assert fake.calls[0][1]['strToDate'] == '20261031'
    assert isinstance(fake.calls[0][2], tuple)
    with closing(connect()) as db:
        saved = dict(db.execute('SELECT * FROM filings').fetchone())
    assert saved['ticker'] == 'NTPC'
    assert saved['url'] == direct
    assert saved['score'] == 94 and saved['category'] == 'results'
    result2 = live_bse.sync_bse('2026-10-30', '2026-10-31', portfolio_file=portfolio, session=fake)
    assert result2['source'] == 'live' and result2['added'] == 0 and result2['duplicates'] == 1
    with closing(connect()) as db:
        assert db.execute('SELECT COUNT(*) FROM filings').fetchone()[0] == 1


def test_pdf_fallback_only_for_known_attachment_name(isolated_db):
    _, portfolio = isolated_db
    fake = FakeSession({('532555', 1): {'Table': [_row()], 'Table1': [{'ROWCNT': 1}]}})
    result = live_bse.sync_bse(date(2026, 10, 31), date(2026, 10, 31),
                               portfolio_file=portfolio, session=fake)
    assert result['source'] == 'live' and result['derived_pdf_urls'] == 1
    assert live_bse._pdf_url({'ATTACHMENTNAME': '../../secret.pdf'}) == ('', False)
    assert live_bse._pdf_url({'PDF_LINK': 'https://evil.example/xml-data/corpann/a.pdf'}) == ('', False)


def test_empty_response_retains_existing_filings(isolated_db):
    connect, portfolio = isolated_db
    with closing(connect()) as db:
        db.execute('''INSERT INTO filings (ticker,published,title,url,category,score,source,excerpt)
            VALUES (?,?,?,?,?,?,?,?)''', ('NTPC', '2026-10-30T10:00:00+05:30', 'Old snapshot',
                                            'https://www.bseindia.com/xml-data/corpann/old.pdf',
                                            'unclassified', 10, 'BSE official RSS snapshot', ''))
        db.commit()
    status = live_bse.sync_bse('2026-10-31', '2026-10-31',
                               portfolio_file=portfolio, session=FakeSession())
    assert status['source'] == 'snapshot' and status['error'] and status['added'] == 0
    with closing(connect()) as db:
        assert db.execute('SELECT COUNT(*) FROM filings').fetchone()[0] == 1


def test_403_or_second_scrip_failure_never_partially_imports(isolated_db):
    connect, portfolio = isolated_db
    portfolio.write_text(json.dumps({'NTPC': '532555', 'LT': '500510'}), encoding='utf-8')
    pages = {('532555', 1): {'Table': [_row()], 'Table1': [{'ROWCNT': 1}]}}
    fake = FakeSession(pages, fail_for='500510')
    result = live_bse.sync_bse('2026-10-31', '2026-10-31',
                               portfolio_file=portfolio, session=fake)
    assert result['source'] == 'snapshot' and '403' in result['error']
    assert result['added'] == 0
    with closing(connect()) as db:
        assert db.execute('SELECT COUNT(*) FROM filings').fetchone()[0] == 0


def test_malformed_json_and_bad_code_are_not_live(isolated_db):
    _, portfolio = isolated_db
    fake = FakeSession({('532555', 1): {'unexpected': []}})
    status = live_bse.sync_bse('2026-10-31', '2026-10-31', portfolio_file=portfolio, session=fake)
    assert status['source'] == 'snapshot' and status['error']
    fake = FakeSession({('532555', 1): {'Table': [_row(code='999999')],
                                       'Table1': [{'ROWCNT': 1}]}})
    status = live_bse.sync_bse('2026-10-31', '2026-10-31', portfolio_file=portfolio, session=fake)
    assert status['source'] == 'snapshot' and status['added'] == 0


def test_pagination_fetches_every_page(isolated_db):
    _, portfolio = isolated_db
    a = _row(title='Unaudited Financial Results for quarter ended September 2026')
    b = _row(title='Dividend record date', attachment='ntpc-dividend.pdf')
    fake = FakeSession({
        ('532555', 1): {'Table': [a], 'Table1': [{'ROWCNT': 2}]},
        ('532555', 2): {'Table': [b], 'Table1': [{'ROWCNT': 2}]},
    })
    result = live_bse.sync_bse('2026-10-31', '2026-10-31', portfolio_file=portfolio, session=fake)
    assert result['source'] == 'live' and result['added'] == 2
    assert result['grouped_events'] == 2 and len(fake.calls) == 2


def test_portfolio_json_validated(tmp_path):
    file = tmp_path / 'portfolio.json'
    file.write_text(json.dumps({'NTPC': '', 'LT': '500510'}), encoding='utf-8')
    assert live_bse.load_portfolio(file) == {'LT': '500510'}
    file.write_text(json.dumps({'NTPC': 'wrong'}), encoding='utf-8')
    with pytest.raises(ValueError, match='six-digit'):
        live_bse.load_portfolio(file)
    file.write_text(json.dumps({'UNKNOWN': '123456'}), encoding='utf-8')
    with pytest.raises(ValueError, match='Unknown NSE'):
        live_bse.load_portfolio(file)


def test_retry_policy_does_not_retry_403():
    session = live_bse.make_session()
    retry = session.get_adapter('https://').max_retries
    assert 403 not in retry.status_forcelist
    assert {429, 500, 503}.issubset(set(retry.status_forcelist))
    assert 'www.bseindia.com' in session.headers['Referer']
    session.close()


def test_deployed_sync_requires_key(monkeypatch):
    from fastapi.testclient import TestClient
    from app.deploy import app
    monkeypatch.delenv('FINN_BSE_SYNC_KEY', raising=False)
    with TestClient(app) as client:
        response = client.post('/api/bse/live-sync?days=3')
        assert response.status_code == 503
    monkeypatch.setenv('FINN_BSE_SYNC_KEY', 'this-is-only-a-test-value')
    with TestClient(app) as client:
        response = client.post('/api/bse/live-sync?days=3',
                               headers={'X-FINN-Sync-Key': 'wrong-value'})
        assert response.status_code == 403


def test_deployed_sync_calls_same_pipeline_when_authorized(monkeypatch):
    from fastapi.testclient import TestClient
    import app.deploy as deployment
    monkeypatch.setenv('FINN_BSE_SYNC_KEY', 'this-is-only-a-test-value')
    calls = []
    def fake_sync(start, end):
        calls.append((start, end))
        return {'source': 'snapshot', 'fetched_at': '2026-10-31T00:00:00+00:00',
                'error': '403 Forbidden', 'added': 0}
    monkeypatch.setattr(deployment, 'sync_bse', fake_sync)
    with TestClient(deployment.app) as client:
        response = client.post('/api/bse/live-sync?days=3',
                               headers={'X-FINN-Sync-Key': 'this-is-only-a-test-value'})
        assert response.status_code == 200
        assert response.json()['source'] == 'snapshot'
        assert response.json()['added'] == 0
    assert len(calls) == 1
    assert (calls[0][1] - calls[0][0]).days == 2
