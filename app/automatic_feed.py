"""Bounded automatic announcement collection with disclosed directory fallback."""
from __future__ import annotations
import json
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import closing
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, quote, urlparse

import requests
from bs4 import BeautifulSoup
from fastapi import APIRouter

from .core import PORTFOLIO, classify, excerpt
from .storage import connection

INTERVAL_SECONDS = 15 * 60
MAX_HTML_BYTES = 2 * 1024 * 1024
SOURCE = 'BSE filing metadata via Screener'
router = APIRouter()
_worker = None
_launch_lock = threading.Lock()
_stop = threading.Event()


def attachment_key(url):
    parsed = urlparse(url)
    if parsed.hostname in {'bseindia.com','www.bseindia.com'}:
        name = parse_qs(parsed.query).get('Pname', [''])[0] or parsed.path.rsplit('/',1)[-1]
        if re.fullmatch(r'[a-fA-F0-9-]{36}\.pdf',name):
            return 'bse:' + name.lower()
    return url.split('#',1)[0]


def parse_announcements(raw, ticker, now=None, days=30):
    now = now or datetime.now(timezone.utc)
    soup = BeautifulSoup(raw,'html.parser')
    container = soup.select_one('#company-announcements-tab')
    if container is None:raise ValueError('Announcement directory layout unavailable')
    result=[]
    for anchor in container.select('li a[href]')[:50]:
        time_node = anchor.select_one('time[datetime]')
        if time_node is None:continue
        try:
            published=datetime.fromisoformat(time_node['datetime'].replace('Z','+00:00'))
            if published.tzinfo is None:continue
            published=published.astimezone(timezone.utc)
        except (ValueError,TypeError):continue
        if not now-timedelta(days=days)<=published<=now+timedelta(minutes=5):continue
        url=anchor['href'].strip();parsed=urlparse(url)
        if parsed.scheme!='https' or parsed.hostname not in {'www.bseindia.com','bseindia.com'} or parsed.username or parsed.password:continue
        is_pdf=parsed.path.lower().endswith('.pdf') or (parsed.path.lower()=='/stockinfo/annpdfopen.aspx' and
            bool(re.fullmatch(r'[a-fA-F0-9-]{36}\.pdf',parse_qs(parsed.query).get('Pname',[''])[0])))
        if not is_pdf:continue
        title=' '.join(' '.join(anchor.find_all(string=True,recursive=False)).split())[:500]
        if len(title)<4:continue
        note=anchor.select_one('div, span')
        if note:
            for t in note.select('time'):t.decompose()
        description=' '.join(note.get_text(' ',strip=True).split()).lstrip('- ')[:1200] if note else ''
        result.append({'ticker':ticker,'title':title,'published':published.isoformat(),'url':url,
            'source':SOURCE,'excerpt':('Directory note (PDF not reviewed): '+description) if description else ''})
    return result


def fetch_company(ticker, days=30):
    for suffix in ['/consolidated/','/']:
        url='https://www.screener.in/company/'+quote(ticker,safe='')+suffix
        with requests.get(url,timeout=(4,12),stream=True,allow_redirects=False,
                          headers={'User-Agent':'FINN/1.0 public-announcement-directory'}) as response:
            if response.status_code==404 and suffix!='/':continue
            response.raise_for_status()
            if response.status_code!=200:raise ValueError('Directory redirected or unavailable')
            size,parts=0,[]
            for part in response.iter_content(65536):
                size+=len(part)
                if size>MAX_HTML_BYTES:raise ValueError('Directory exceeds size limit')
                parts.append(part)
        return parse_announcements(b''.join(parts),ticker,days=days)
    raise ValueError('Company directory unavailable')


def import_rows(rows):
    added=duplicates=0
    with closing(connection()) as db:
        db.execute('BEGIN IMMEDIATE')
        with db:
            existing={}
            for row in db.execute('SELECT ticker,url FROM filings WHERE url!=""'):
                existing.setdefault(row['ticker'],set()).add(attachment_key(row['url']))
            for row in rows:
                keys=existing.setdefault(row['ticker'],set());key=attachment_key(row['url'])
                if key in keys:
                    duplicates+=1;continue
                category,score=classify(row['title'],row.get('excerpt',''))
                cur=db.execute('''INSERT OR IGNORE INTO filings
                    (ticker,published,title,url,category,score,source,excerpt) VALUES (?,?,?,?,?,?,?,?)''',
                    (row['ticker'],row['published'],row['title'],row['url'],category,score,row['source'],excerpt(row.get('excerpt',''))))
                added+=cur.rowcount;duplicates+=1-cur.rowcount;keys.add(key)
    return {'added':added,'duplicates':duplicates}


def read_sync():
    with closing(connection()) as db:
        row=db.execute("SELECT value FROM preferences WHERE key='automatic_feed'").fetchone()
    return json.loads(row['value']) if row else {'last_attempt':None,'last_success':None,'source':'snapshot'}


def save_sync(status):
    with closing(connection()) as db,db:
        db.execute('INSERT OR REPLACE INTO preferences VALUES (?,?)',('automatic_feed',json.dumps(status)))


def sync_sources(days=30):
    from .live_bse import IST,sync_bse
    now=datetime.now(timezone.utc);status=read_sync()
    status.update(last_attempt=now.isoformat(),running=True,errors=[],added=0,duplicates=0,
                  successful_companies=0,received=0)
    save_sync(status)
    try:
        today=datetime.now(IST).date()
        try:bse=sync_bse(today-timedelta(days=min(days,3)-1),today)
        except Exception as exc:bse={'source':'snapshot','added':0,'duplicates':0,'error':type(exc).__name__}
        status['bse']=bse
        status['added']+=bse.get('added',0);status['duplicates']+=bse.get('duplicates',0)
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures={pool.submit(fetch_company,ticker,days):ticker for ticker,_,_ in PORTFOLIO}
            for future in as_completed(futures):
                ticker=futures[future]
                try:
                    rows=future.result();stats=import_rows(rows)
                    status['successful_companies']+=1;status['received']+=len(rows)
                    for key in ('added','duplicates'):status[key]+=stats[key]
                except Exception as exc:
                    status['errors'].append({'ticker':ticker,'error':type(exc).__name__})
        if status['successful_companies'] or bse['source']=='live':
            status['last_success']=datetime.now(timezone.utc).isoformat();status['source']='live'
        else:status['source']='snapshot'
        if status['added']:status['last_added_at']=datetime.now(timezone.utc).isoformat()
    except Exception as exc:
        status['source']='snapshot';status['errors'].append({'error':type(exc).__name__})
    finally:
        status['running']=False;save_sync(status)
    return status


def schedule_sync():
    global _worker
    with _launch_lock:
        if _worker and _worker.is_alive():return
        last=read_sync().get('last_attempt')
        if last and (datetime.now(timezone.utc)-datetime.fromisoformat(last)).total_seconds()<INTERVAL_SECONDS:return
        _worker=threading.Thread(target=sync_sources,name='finn-announcements',daemon=True)
        _worker.start()


def start_watcher():
    if os.environ.get('FINN_AUTO_ANNOUNCEMENTS','0')!='1':return
    _stop.clear()
    def watch():
        while not _stop.is_set():
            try:schedule_sync()
            except Exception:pass
            if _stop.wait(60):return
    threading.Thread(target=watch,name='finn-announcement-clock',daemon=True).start()


def stop_watcher():
    _stop.set()


@router.get('/api/feed/status')
def feed_status():
    status=read_sync()
    with closing(connection()) as db:
        totals=db.execute("SELECT COUNT(*),COUNT(DISTINCT ticker) FROM filings WHERE source!='synthetic_demo'").fetchone()
        latest=db.execute("SELECT published FROM filings WHERE source!='synthetic_demo' ORDER BY julianday(published) DESC LIMIT 1").fetchone()
    return {**status,'running':bool(_worker and _worker.is_alive()),'interval_minutes':15,
            'filings_total':totals[0],'companies_with_filings':totals[1],'latest_publication':latest[0] if latest else None,
            'note':'Original BSE links; directory metadata is secondary and PDFs are not automatically reviewed. Rolling sources may not cover every filing. Automatic checks run while the service is awake.'}


@router.post('/api/feed/refresh')
def refresh_feed():
    schedule_sync()
    return feed_status()
