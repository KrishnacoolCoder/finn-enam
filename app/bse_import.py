"""Offline BSE RSS snapshot importer. No attempts to evade exchange access restrictions."""
from __future__ import annotations
import xml.etree.ElementTree as ET
from datetime import datetime,timedelta,timezone
from urllib.parse import urlparse
from .core import PORTFOLIO,classify,excerpt
from .storage import connection

IST=timezone(timedelta(hours=5,minutes=30))
# Verified NSE equity identifiers matched to their BSE equity scrip codes.
EQUITY_CODES={'RELIANCE':'500325','HDFCBANK':'500180','ICICIBANK':'532174','SBIN':'500112',
'TCS':'532540','INFY':'500209','WIPRO':'507685','ONGC':'500312','MARUTI':'532500',
'M&M':'500520','HINDUNILVR':'500696','ITC':'500875','SUNPHARMA':'524715',
'DRREDDY':'500124','LT':'500510','ADANIPORTS':'532921','BHARTIARTL':'532454',
'TATASTEEL':'500470','TITAN':'500114','NTPC':'532555'}
REVERSE={v:k for k,v in EQUITY_CODES.items()}
MAX_XML_BYTES=8*1024*1024

def parse_feed(data:bytes):
    if len(data)>MAX_XML_BYTES:raise ValueError('Feed exceeds the 8 MB safety limit')
    if b'<!DOCTYPE' in data.upper() or b'<!ENTITY' in data.upper():raise ValueError('DTD and entities not supported')
    try:root=ET.fromstring(data.decode('utf-8-sig'))
    except (ET.ParseError,UnicodeError) as exc:raise ValueError('Not valid UTF-8 RSS/XML') from exc
    if root.tag!='rss' or root.find('channel') is None:raise ValueError('Expected a BSE RSS feed')
    results=[]
    for item in root.findall('./channel/item'):
        code=(item.findtext('scripcode') or '').strip()
        title=(item.findtext('title') or '').strip()
        description=(item.findtext('description') or '').strip()
        url=(item.findtext('link') or '').strip()
        timestamp=(item.findtext('pubDate') or '').strip()
        if not code.isdigit() or not title or not timestamp:continue
        try:dt=datetime.strptime(timestamp,'%d-%b-%Y %H:%M:%S').replace(tzinfo=IST)
        except ValueError:continue
        parsed=urlparse(url)
        if parsed.scheme!='https' or parsed.hostname not in ('www.bseindia.com','bseindia.com'):url=''
        results.append({'code':code,'name':title.rsplit(' (',1)[0], 'description':description,
                        'url':url,'published':dt.isoformat()})
    return results

def import_bse(data:bytes,scope='portfolio'):
    if scope not in ('portfolio','all'):raise ValueError('scope must be portfolio or all')
    items=parse_feed(data)
    added=skipped=duplicates=0
    selected=[]
    seen=set()
    for record in items:
        ticker=REVERSE.get(record['code'])
        if scope=='portfolio' and not ticker:
            skipped+=1;continue
        # For expanded feed, BSE instrument codes are unambiguous; do not invent NSE tickers.
        symbol=ticker or 'BSE'+record['code']
        if scope=='all' and record['code'] not in REVERSE and record['code'].startswith(('9','7')):
            skipped+=1;continue # debt securities: avoid misrepresenting them as ordinary equity
        identity=(symbol,record['url'] or (record['published'],record['description']))
        if identity in seen:duplicates+=1;continue
        seen.add(identity)
        description=record['description'] or 'Exchange disclosure: open the original PDF for details.'
        title=(description[:170].strip() or 'Corporate announcement')
        category,score=classify(title,description)
        selected.append((symbol,record['published'],title[:500],record['url'],category,score,
                         'BSE official RSS snapshot',excerpt(description)))
    with connection() as db:
        for row in selected:
            if row[3] and db.execute('SELECT 1 FROM filings WHERE ticker=? AND url=?',(row[0],row[3])).fetchone():
                duplicates+=1;continue
            result=db.execute('INSERT OR IGNORE INTO filings(ticker,published,title,url,category,score,source,excerpt) VALUES(?,?,?,?,?,?,?,?)',row)
            if result.rowcount:added+=1
            else:duplicates+=1
    return {'received':len(items),'eligible':len(selected),'added':added,'duplicates':duplicates,
            'out_of_scope':skipped,'scope':scope,'mode':'official BSE RSS snapshot — manually uploaded; not live synchronization',
            'note':'Only feed text classified. Linked PDFs have not been automatically analysed.'}
