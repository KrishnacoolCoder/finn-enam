import ast
import inspect
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone

import pytest
import requests
from fastapi.testclient import TestClient

from app import research, screener_context as sc, storage
from app.main import app

HTML = '''<html><h1>Test Company</h1><div id="company-info" data-consolidated="true"></div>
<ul id="top-ratios"><li><span class="name">Market Cap</span><span class="value">Rs 1,000 Cr.</span></li></ul>
<section id="quarters"><h2>Quarterly Results</h2>Consolidated Figures in Rs. Crores
<table><thead><tr><th></th><th>Jun 2025</th><th>Sep 2025</th><th>Dec 2025</th><th>Mar 2026</th><th>Jun 2026</th><th>Sep 2026</th></tr></thead>
<tbody><tr><td>Sales +</td><td>10</td><td>20</td><td>30</td><td></td><td>50</td><td>60</td></tr>
<tr><td>OPM %</td><td>1%</td><td>2%</td><td>3%</td><td>4%</td><td>5%</td><td>-6%</td></tr>
</tbody></table></section><script>bad()</script></html>'''


@pytest.fixture
def database(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, 'DB', tmp_path/'context.sqlite3')
    storage.init()
    sc._failures.clear()


def parsed():
    return sc.parse_snapshot(HTML, 'NTPC', 'consolidated', 'https://www.screener.in/company/NTPC/consolidated/')


def test_parse_keeps_periods_basis_units_blanks_and_labels():
    data = parsed()
    assert data['basis'] == 'consolidated'
    assert data['periods'] == ['Sep 2025','Dec 2025','Mar 2026','Jun 2026','Sep 2026']
    assert data['quarterly_rows'][0] == {'metric':'Sales','values':['20','30','','50','60']}
    assert data['quarterly_rows'][1]['values'][-1] == '-6%'
    assert 'Unverified' in data['verification']
    assert 'bad()' not in json.dumps(data)
    assert sc.parse_snapshot(HTML.replace('Consolidated','Standalone'), 'NTPC','standalone','https://www.screener.in/company/NTPC/')['basis']=='standalone'


@pytest.mark.parametrize('markup', ['<html>Login or access denied</html>',
    HTML.replace('<td>60</td>',''), HTML.replace('Consolidated Figures','Unknown Figures')])
def test_parser_rejects_missing_or_misaligned_data(markup):
    with pytest.raises(ValueError): sc.parse_snapshot(markup,'NTPC','consolidated','https://www.screener.in/')


def test_caches_without_writing_research_or_reviewed_financials(database,monkeypatch):
    calls=[]
    monkeypatch.setattr(sc,'fetch_snapshot',lambda *args: calls.append(args) or parsed())
    assert sc.snapshot('NTPC')['status']=='fetched'
    assert sc.snapshot('NTPC')['status']=='cached'
    assert len(calls)==1
    with closing(storage.connection()) as db:
        assert db.execute('SELECT COUNT(*) FROM chunks').fetchone()[0]==0
        assert db.execute('SELECT COUNT(*) FROM documents').fetchone()[0]==0
        assert db.execute('SELECT COUNT(*) FROM filings').fetchone()[0]==0


def test_failure_uses_stale_cache_without_refreshing_timestamp(database,monkeypatch):
    data=parsed();data['fetched_at']=(datetime.now(timezone.utc)-timedelta(days=1)).isoformat()
    with closing(storage.connection()) as db,db:
        db.execute('INSERT INTO company_context VALUES (?,?,?,?)',('NTPC','consolidated',json.dumps(data),data['fetched_at']))
    def fail(*args): raise requests.Timeout()
    monkeypatch.setattr(sc,'fetch_snapshot',fail)
    result=sc.snapshot('NTPC')
    assert result['stale'] and result['fetched_at']==data['fetched_at']
    assert sc.snapshot('NTPC')['status']=='stale'


def test_unavailable_does_not_crash_and_backoff_avoids_repeated_requests(database,monkeypatch):
    calls=[]
    def fail(*args): calls.append(args);raise requests.HTTPError('403')
    monkeypatch.setattr(sc,'fetch_snapshot',fail)
    assert sc.snapshot('NTPC')['status']=='unavailable'
    assert sc.snapshot('NTPC')['status']=='unavailable'
    assert len(calls)==1


def test_requests_are_fixed_host_encoded_bounded_and_no_redirects(monkeypatch):
    class Response:
        status_code=200
        headers={'Content-Type':'text/html'}
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def iter_content(self,size):yield HTML.encode()
    def get(url,**kwargs):
        assert url=='https://www.screener.in/company/M%26M/consolidated/'
        assert kwargs['allow_redirects'] is False
        assert kwargs['timeout']==(4,12) and kwargs['stream']
        return Response()
    monkeypatch.setattr(sc.requests,'get',get)
    assert sc.fetch_snapshot('M&M','consolidated')['ticker']=='M&M'


def test_api_and_invalid_ticker(database,monkeypatch):
    monkeypatch.setattr(sc,'fetch_snapshot',lambda *args:parsed())
    with TestClient(app) as client:
        assert client.get('/api/company-context/NTPC').json()['status']=='fetched'
        assert client.get('/api/company-context/NTPC?basis=bad').status_code==422
        assert client.get('/api/company-context/BAD%3F').status_code==400


def test_research_does_not_import_or_read_company_context(database,monkeypatch):
    tree=ast.parse(inspect.getsource(research))
    imports=[n.module for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)]
    imports += [a.name for n in ast.walk(tree) if isinstance(n,ast.Import) for a in n.names]
    assert not any('screener' in (name or '') for name in imports)
    def guarded():
        db=storage.connection()
        db.set_authorizer(lambda action,table,*rest:sqlite3.SQLITE_DENY if action==sqlite3.SQLITE_READ and table=='company_context' else sqlite3.SQLITE_OK)
        return db
    monkeypatch.setattr(research,'connection',guarded)
    monkeypatch.delenv('OPENAI_API_KEY',raising=False)
    assert research.answer('NTPC','Sales and profit')['mode']=='no_sources'
    research.ingest('NTPC','annual.txt',b'Primary annual report: company sales were 100 crore and net profit was 20 crore for the year.')
    assert research.retrieve('NTPC','sales and net profit')
