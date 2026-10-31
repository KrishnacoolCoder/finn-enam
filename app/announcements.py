"""Best-effort import of publicly accessible NSE corporate announcements.

NSE's website endpoint is undocumented and can become unavailable. Never
represent an access-denied or malformed response as a successful empty feed.
"""
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse
import requests
from .core import classify, excerpt
from .storage import connection

IST = timezone(timedelta(hours=5, minutes=30))
NSE_API = 'https://www.nseindia.com/api/corporate-announcements'


def _published(raw):
    if not raw:
        return None
    value = str(raw).strip()
    for fmt in ('%d-%b-%Y %H:%M:%S', '%d-%b-%Y %H:%M',
                '%d-%b-%Y', '%d-%m-%Y %H:%M:%S', '%d-%m-%Y',
                '%Y-%m-%d %H:%M:%S'):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=IST).isoformat()
        except ValueError:
            pass
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return (parsed if parsed.tzinfo else parsed.replace(tzinfo=IST)).isoformat()
    except ValueError:
        return None


def fetch_nse(symbol, days=7):
    today = datetime.now(IST).date()
    headers = {
        'User-Agent': 'Mozilla/5.0 FINN/1.0',
        'Accept': 'application/json, text/plain, */*',
        'Accept-Language': 'en-IN,en;q=0.9',
        'Referer': 'https://www.nseindia.com/companies-listing/corporate-filings-announcements',
    }
    session = requests.Session()
    session.headers.update(headers)
    try:
        # Ordinary web session, not a bypass for exchange access restrictions.
        session.get('https://www.nseindia.com/', timeout=12).raise_for_status()
        response = session.get(NSE_API, params={
            'index': 'equities', 'symbol': symbol,
            'from_date': (today - timedelta(days=days)).strftime('%d-%m-%Y'),
            'to_date': today.strftime('%d-%m-%Y'),
        }, timeout=20)
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise RuntimeError(f'NSE announcements unavailable: {str(exc)[:180]}') from exc
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and isinstance(payload.get('data'), list):
        return payload['data']
    raise RuntimeError('NSE returned an unexpected response; no filings imported')


def sync_nse(symbol, days=7):
    records = fetch_nse(symbol, days)
    added = skipped = 0
    for item in records[:200]:
        if not isinstance(item, dict):
            skipped += 1
            continue
        ticker = str(item.get('symbol') or item.get('sm_name') or symbol).upper().strip()
        if ticker != symbol:
            skipped += 1
            continue
        title = str(item.get('desc') or item.get('subject') or item.get('attchmntText') or '').strip()
        detail = str(item.get('attchmntText') or item.get('an_dt') or '').strip()
        published = _published(item.get('an_dt') or item.get('sort_date') or item.get('broadcastDateTime'))
        url = str(item.get('attchmntFile') or item.get('attachmentURL') or '').strip()
        parsed = urlparse(url)
        if parsed.scheme != 'https' or not parsed.hostname or not parsed.hostname.endswith(('nseindia.com', 'nse.co.in')):
            url = ''
        if not title or not published:
            skipped += 1
            continue
        category, score = classify(title, detail)
        with connection() as db:
            cursor = db.execute('''INSERT OR IGNORE INTO filings
                (ticker,published,title,url,category,score,source,excerpt)
                VALUES (?,?,?,?,?,?,?,?)''',
                (ticker, published, title[:500], url, category, score, 'NSE automated', excerpt(detail)))
            added += cursor.rowcount
    return {'ticker': symbol, 'received': len(records), 'added': added,
            'duplicates_or_skipped': len(records) - added,
            'source': 'NSE', 'note': 'NSE is an unofficial website API and may block requests.'}
