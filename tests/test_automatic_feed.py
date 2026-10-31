from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime,timedelta,timezone

import pytest
import requests
from fastapi.testclient import TestClient

from app import automatic_feed as feed,live_bse,storage
from app.main import app

GUID='12345678-1234-1234-1234-123456789abc'
URL=f'https://www.bseindia.com/stockinfo/AnnPdfOpen.aspx?Pname={GUID}.pdf'
NOW=datetime(2026,11,1,12,tzinfo=timezone.utc)


def html(url=URL,stamp='2026-10-31T18:00:00+05:30'):
    return f'''<div id="company-announcements-tab"><ul><li><a href="{url}">
      Quarterly Financial Results<div><time datetime="{stamp}">31 Oct</time> - Results released for the quarter.</div>
      </a></li></ul></div>'''


@pytest.fixture
def database(tmp_path,monkeypatch):
    monkeypatch.setattr(storage,'DB',tmp_path/'automatic.sqlite3');storage.init()
    monkeypatch.setenv('INGEST_TOKEN','feed-secret')
    monkeypatch.setenv('FINN_AUTO_ANNOUNCEMENTS','0')
    monkeypatch.setattr(feed,'_worker',None)


def test_metadata_dates_and_primary_links():
    rows=feed.parse_announcements(html(),'NTPC',now=NOW,days=7)
    assert len(rows)==1 and rows[0]['published']=='2026-10-31T12:30:00+00:00'
    assert rows[0]['title']=='Quarterly Financial Results' and rows[0]['url']==URL
    assert 'PDF not reviewed' in rows[0]['excerpt']
    assert rows[0]['source']==feed.SOURCE


@pytest.mark.parametrize('url,stamp',[
    ('https://bseindia.com.evil.test/filing.pdf','2026-10-31T10:00:00Z'),
    ('javascript:alert(1)','2026-10-31T10:00:00Z'),
    (URL,'not a date'),(URL,'2026-10-31T10:00:00'),
    (URL,'2025-10-31T10:00:00Z'),(URL,'2026-11-02T10:00:00Z')])
def test_invalid_source_or_date_is_not_imported(url,stamp):
    assert feed.parse_announcements(html(url,stamp),'NTPC',now=NOW,days=7)==[]


def test_cross_transport_and_concurrent_deduplication(database):
    rows=feed.parse_announcements(html(),'NTPC',now=NOW)
    old=dict(rows[0],url=f'https://www.bseindia.com/xml-data/corpfiling/AttachLive/{GUID}.pdf')
    assert feed.import_rows([old])['added']==1
    with ThreadPoolExecutor(max_workers=3) as pool:
        results=list(pool.map(lambda _:feed.import_rows(rows),range(3)))
    assert sum(r['added'] for r in results)==0
    with closing(storage.connection()) as db:
        assert db.execute('SELECT COUNT(*) FROM filings').fetchone()[0]==1


def test_one_company_and_bse_failure_do_not_stop_other_sources(database,monkeypatch):
    monkeypatch.setattr(feed,'PORTFOLIO',[('NTPC','NTPC','Power'),('LT','Larsen','Industrial')])
    def bse_failure(*args,**kwargs):raise requests.Timeout()
    monkeypatch.setattr(live_bse,'sync_bse',bse_failure)
    def fetch(ticker,days):
        if ticker=='LT':raise requests.HTTPError('403')
        return feed.parse_announcements(html(),ticker,now=NOW)
    monkeypatch.setattr(feed,'fetch_company',fetch)
    result=feed.sync_sources()
    assert result['added']==1 and result['successful_companies']==1
    assert result['source']=='live' and result['bse']['error']=='Timeout'
    assert result['errors']==[{'ticker':'LT','error':'HTTPError'}]
    assert feed.sync_sources()['added']==0


def test_all_failures_preserve_previous_rows_and_success_time(database,monkeypatch):
    feed.import_rows(feed.parse_announcements(html(),'NTPC',now=NOW))
    feed.save_sync({'last_success':'2026-10-31T00:00:00+00:00','source':'live'})
    monkeypatch.setattr(feed,'PORTFOLIO',[('NTPC','NTPC','Power')])
    monkeypatch.setattr(live_bse,'sync_bse',lambda *args:{'source':'snapshot','added':0,'duplicates':0})
    def fail(*args):raise requests.Timeout()
    monkeypatch.setattr(feed,'fetch_company',fail)
    result=feed.sync_sources()
    assert result['source']=='snapshot' and result['last_success']=='2026-10-31T00:00:00+00:00'
    assert feed.feed_status()['filings_total']==1


def test_scheduler_rate_limits_and_watcher_disabled_in_local_mode(database,monkeypatch):
    calls=[]
    monkeypatch.setattr(feed,'sync_sources',lambda:calls.append(1))
    feed.save_sync({'last_attempt':datetime.now(timezone.utc).isoformat()})
    feed.schedule_sync();feed.start_watcher()
    assert not calls
    assert feed._worker is None


def test_hosted_watcher_starts_and_stops(database,monkeypatch):
    import threading
    started=threading.Event()
    monkeypatch.setenv('FINN_AUTO_ANNOUNCEMENTS','1')
    monkeypatch.setattr(feed,'schedule_sync',started.set)
    feed.start_watcher()
    assert started.wait(2)
    feed.stop_watcher()
    assert feed._stop.is_set()


def test_timezone_window_respects_same_instant(database):
    now=datetime.now(timezone.utc)
    # A +05:30 timestamp older than 24h must not slip through lexical comparison.
    old=(now-timedelta(hours=25)).astimezone(timezone(timedelta(hours=5,minutes=30)))
    row={'ticker':'NTPC','title':'Quarterly Results','published':old.isoformat(),'url':URL,'source':'test','excerpt':''}
    feed.import_rows([row])
    with TestClient(app) as client:
        assert client.get('/api/filings?hours=24').json()==[]
        assert len(client.get('/api/filings?hours=72').json())==1


def test_authenticated_replay_uses_document_identity_and_updates_live_state(database):
    rows=feed.parse_announcements(html(),'NTPC',now=NOW)
    with TestClient(app) as client:
        auth={'X-Ingest-Token':'feed-secret'}
        assert client.post('/api/ingest',json=rows,headers=auth).json()['added']==1
        alt=dict(rows[0],url=f'https://www.bseindia.com/xml-data/corpfiling/AttachHis/{GUID}.pdf')
        assert client.post('/api/ingest',json=[alt],headers=auth).json()['duplicates']==1
        status=client.get('/api/feed/status').json()
        assert status['source']=='live' and status['last_success'] and status['filings_total']==1
        assert client.get('/api/research/ask').status_code==405
