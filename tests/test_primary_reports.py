import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path

import pymupdf
import pytest
import requests
from fastapi.testclient import TestClient

from app import primary_reports as pr, research, storage
from app.core import PORTFOLIO
from app.main import app


def pdf():
    doc=pymupdf.open()
    doc.new_page().insert_text((50,50),'Primary company annual report. Contents and company information.')
    doc.new_page().insert_text((50,50),'Business segments and risks: the power business faces fuel supply risks and demand uncertainty.')
    raw=doc.tobytes();doc.close();return raw


@pytest.fixture
def isolated(tmp_path,monkeypatch):
    monkeypatch.setattr(storage,'DB',tmp_path/'reports.sqlite3')
    storage.init();pr._failures.clear()
    raw=pdf()
    report={'name':'NTPC test annual report.pdf','kind':'annual_report','url':'https://company.example/annual.pdf',
            'sha256':hashlib.sha256(raw).hexdigest(),'allowed_hosts':['company.example']}
    monkeypatch.setattr(pr,'catalog',lambda:{'NTPC':[report]})
    return raw,report


def test_catalogue_covers_exact_portfolio_and_only_primary_pdf_types():
    data=json.loads(pr.CATALOG.read_text())
    assert set(data)=={ticker for ticker,_,_ in PORTFOLIO}
    for reports in data.values():
        assert reports
        for r in reports:
            assert r['kind'] in {'annual_report','transcript'}
            assert r['name'].endswith('.pdf') and r['url'].startswith('https://')
            assert len(r['sha256'])==64 and r['allowed_hosts']
            assert 'screener.in' not in r['url'] and 'news.google.com' not in r['url']


def test_autoload_idempotent_and_real_pdf_pages_in_retrieval(isolated,monkeypatch):
    raw,report=isolated;calls=[]
    monkeypatch.setattr(pr,'download',lambda r:calls.append(r) or raw)
    assert pr.ensure_reports('NTPC')['status']=='ready'
    assert pr.ensure_reports('NTPC')['loaded']==0
    assert len(calls)==1
    docs=research.list_docs('NTPC')
    assert len(docs)==1 and docs[0]['auto_loaded']==1
    results=research.retrieve('NTPC','What are the main business segments and fuel supply risks?')
    assert results and results[0]['page']==2 and results[0]['source_url']==report['url']


def test_simultaneous_selections_do_not_duplicate(isolated,monkeypatch):
    raw,_=isolated
    monkeypatch.setattr(pr,'download',lambda r:raw)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results=list(pool.map(lambda _:pr.ensure_reports('NTPC'),range(4)))
    assert sum(x['loaded'] for x in results)==1
    assert len(research.list_docs('NTPC'))==1


def test_failure_keeps_manual_report_and_backs_off(isolated,monkeypatch):
    research.ingest('NTPC','manual.txt',b'An independently uploaded annual report explains company fuel supply risks and business segments.')
    calls=[]
    def fail(r):calls.append(r);raise requests.Timeout()
    monkeypatch.setattr(pr,'download',fail)
    assert pr.ensure_reports('NTPC')['status']=='unavailable'
    assert pr.ensure_reports('NTPC')['status']=='unavailable'
    assert len(calls)==1 and len(research.list_docs('NTPC'))==1
    assert research.retrieve('NTPC','fuel supply risks')


def test_other_ticker_stays_manual_without_network(isolated,monkeypatch):
    monkeypatch.setattr(pr,'download',lambda r:pytest.fail('Unexpected download'))
    assert pr.ensure_reports('OTHER')['status']=='manual'


def test_automatic_large_report_limit_does_not_relax_manual_limit(isolated):
    raw,report=isolated
    with pytest.raises(ValueError,match='20 MB'):
        research.ingest('NTPC','manual.pdf',b'x'*(research.MAX_BYTES+1))
    with pytest.raises(ValueError,match='PDF exceeds'):
        research.ingest('NTPC','limited.pdf',raw,max_pages=1)
    assert research.ingest('NTPC',report['name'],raw,'annual_report',report['url'],auto_loaded=True,max_pages=1000)['pages']==2


def test_download_pinned_checksum_and_no_arbitrary_redirect(isolated,monkeypatch):
    raw,report=isolated
    class Reply:
        status_code=200
        headers={}
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def raise_for_status(self):pass
        def iter_content(self,*args):yield raw
    monkeypatch.setattr(pr.requests,'get',lambda *args,**kw:Reply())
    assert pr.download(report)==raw
    with pytest.raises(ValueError,match='changed'):
        pr.download(dict(report,sha256='0'*64))
    Reply.status_code=302;Reply.headers={'Location':'http://127.0.0.1/private'}
    with pytest.raises(ValueError,match='approved'):
        pr.download(report)


def test_endpoint_and_seed_restore_keep_library(isolated,monkeypatch,tmp_path):
    raw,_=isolated
    monkeypatch.setattr(pr,'download',lambda r:raw)
    with TestClient(app) as client:
        assert client.post('/api/reports/NTPC/ensure').json()['status']=='ready'
        assert client.get('/api/reports/coverage').json()['ready']==1
    from collector import export_seed
    from app.seed_db import restore_seed
    source=tmp_path/'seed.sqlite3';restored=tmp_path/'restored.sqlite3'
    export_seed(source);assert restore_seed(restored,source)
    import sqlite3
    with closing(sqlite3.connect(restored)) as db:
        assert db.execute('SELECT COUNT(*) FROM documents WHERE auto_loaded=1').fetchone()[0]==1
        assert db.execute('SELECT COUNT(*) FROM chunks').fetchone()[0]>0


def test_bad_pdf_never_creates_half_a_document(isolated,monkeypatch):
    monkeypatch.setattr(pr,'download',lambda r:b'not a PDF')
    assert pr.ensure_reports('NTPC')['status']=='unavailable'
    with closing(storage.connection()) as db:
        assert db.execute('SELECT COUNT(*) FROM documents').fetchone()[0]==0
        assert db.execute('SELECT COUNT(*) FROM chunks').fetchone()[0]==0
