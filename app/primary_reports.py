"""Auto-index a pinned catalogue of primary annual reports and earnings transcripts."""
from __future__ import annotations

import hashlib
import json
import threading
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from fastapi import APIRouter, HTTPException

from .core import PORTFOLIO
from .research import ingest
from .storage import connection

CATALOG = Path(__file__).resolve().parents[1] / 'sample_data' / 'primary_reports.json'
MAX_REPORT_BYTES = 40 * 1024 * 1024
MAX_REPORT_PAGES = 1000
TICKERS = {t for t, _, _ in PORTFOLIO}
_locks = {t: threading.Lock() for t in TICKERS}
_failures = {}
router = APIRouter()


def catalog():
    return json.loads(CATALOG.read_text(encoding='utf-8'))


def download(report):
    url = report['url']
    allowed = set(report.get('allowed_hosts', [urlparse(url).hostname]))
    for _ in range(4):
        parsed = urlparse(url)
        if parsed.scheme != 'https' or parsed.hostname not in allowed or parsed.username or parsed.password:
            raise ValueError('Report redirect is outside its approved source hosts')
        with requests.get(url, timeout=(5, 25), stream=True, allow_redirects=False) as response:
            if response.status_code in (301,302,303,307,308):
                url = urljoin(url, response.headers.get('Location', ''))
                continue
            response.raise_for_status()
            parts, size = [], 0
            for part in response.iter_content(65536):
                size += len(part)
                if size > MAX_REPORT_BYTES:raise ValueError('Primary report exceeds size limit')
                parts.append(part)
        data = b''.join(parts)
        if not data.startswith(b'%PDF-'):raise ValueError('Primary source did not return a PDF')
        if hashlib.sha256(data).hexdigest() != report['sha256']:
            raise ValueError('Report changed since catalogue review; awaiting a catalogue update')
        return data
    raise ValueError('Too many primary-source redirects')


def indexed(ticker):
    with closing(connection()) as db:
        return {r['source_url']:dict(r) for r in db.execute('''SELECT id,name,kind,source_url,pages,content_sha256
            FROM documents WHERE ticker=? AND auto_loaded=1''',(ticker,))}


@router.get('/api/reports/coverage')
def coverage():
    reports=catalog()
    companies=[]
    for ticker,name,_ in PORTFOLIO:
        saved=indexed(ticker)
        count=sum(r['url'] in saved for r in reports.get(ticker,[]))
        companies.append({'ticker':ticker,'company':name,'indexed':count,'expected':len(reports.get(ticker,[]))})
    return {'companies':companies,'ready':sum(x['indexed']>0 and x['indexed']==x['expected'] for x in companies),
            'total':len(PORTFOLIO),'catalog_as_of':'2026-11-01'}


def ensure_reports(ticker):
    ticker = ticker.strip().upper().removesuffix('.NS').removesuffix('.BO')
    if ticker not in TICKERS:
        return {'ticker':ticker,'status':'manual','loaded':0,'errors':[],
                'note':'Automatic report coverage is limited to the 20-company portfolio. Upload a primary document for other tickers.'}
    with _locks[ticker]:
        reports = catalog().get(ticker, [])
        existing = indexed(ticker)
        loaded, errors = 0, []
        for report in reports:
            if report['url'] in existing:
                continue
            key = (ticker, report['url'])
            if key in _failures and datetime.now(timezone.utc)-_failures[key] < timedelta(minutes=10):
                errors.append('Primary source temporarily unavailable; retry later.')
                continue
            try:
                data = download(report)
                result = ingest(ticker, report['name'], data, report['kind'], report['url'],
                                auto_loaded=True, max_bytes=MAX_REPORT_BYTES, max_pages=MAX_REPORT_PAGES)
                loaded += not result.get('duplicate',False)
                _failures.pop(key,None)
            except Exception as exc:
                _failures[key] = datetime.now(timezone.utc)
                errors.append(type(exc).__name__ + ': primary report could not be indexed; existing documents retained.')
        saved = indexed(ticker)
        count = sum(r['url'] in saved for r in reports)
        return {'ticker':ticker,'status':'ready' if reports and count==len(reports) else 'partial' if count else 'unavailable',
                'loaded':loaded,'indexed':count,'expected':len(reports),'errors':errors,
                'note':'Primary-source library snapshot as of 1 November 2026. Document dates are shown; this is not guaranteed latest-quarter coverage.'}


@router.post('/api/reports/{ticker}/ensure')
def ensure_endpoint(ticker:str):
    if len(ticker)>25:raise HTTPException(400,'Invalid ticker')
    return ensure_reports(ticker)
