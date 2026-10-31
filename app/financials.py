"""Source-linked quarterly observations with explicit human review status."""
from __future__ import annotations
import math,re
from contextlib import closing, nullcontext
from urllib.parse import urlparse
from .storage import connection
METRICS=('revenue','ebitda','pbt','pat')
BASIS=('standalone','consolidated')

def setup(db=None):
    with (closing(connection()) if db is None else nullcontext(db)) as c, c:
        c.executescript('''CREATE TABLE IF NOT EXISTS quarterly_financials(
        id INTEGER PRIMARY KEY,ticker TEXT NOT NULL,period TEXT NOT NULL,
        revenue REAL,ebitda REAL,pbt REAL,pat REAL,unit TEXT NOT NULL DEFAULT 'INR crore',
        source_url TEXT NOT NULL, UNIQUE(ticker,period));
        CREATE TABLE IF NOT EXISTS guidance_targets(
        id INTEGER PRIMARY KEY,ticker TEXT NOT NULL,metric TEXT NOT NULL,period TEXT NOT NULL,
        target REAL NOT NULL,unit TEXT NOT NULL,source_url TEXT NOT NULL,statement TEXT NOT NULL,
        UNIQUE(ticker,metric,period,source_url));''')
        additions={
          'quarterly_financials':{'basis':"TEXT NOT NULL DEFAULT 'unknown'",'evidence_page':'INTEGER',
            'verified':'INTEGER NOT NULL DEFAULT 0','evidence_note':"TEXT NOT NULL DEFAULT ''"},
          'guidance_targets':{'target_kind':"TEXT NOT NULL DEFAULT 'absolute'",'quote':"TEXT NOT NULL DEFAULT ''",
            'basis':"TEXT NOT NULL DEFAULT 'unknown'",'tolerance':'REAL NOT NULL DEFAULT 0'}}
        for table,columns in additions.items():
            existing={r[1] for r in c.execute(f'PRAGMA table_info({table})')}
            for name,declaration in columns.items():
                if name not in existing:c.execute(f'ALTER TABLE {table} ADD COLUMN {name} {declaration}')

def quarter_ok(period):return bool(re.fullmatch(r'20\d\d-Q[1-4]',period))
def primary_url(value):
    p=urlparse(value)
    if p.scheme!='https' or not p.hostname or p.username or p.password:
        raise ValueError('An original primary-source HTTPS URL is required')
def number(v):return type(v) in (int,float) and math.isfinite(v) and abs(v)<=1e12

def save_quarter(ticker,period,values,source_url,basis='unknown',evidence_page=None,
                 verified=False,evidence_note='',db=None):
    if not quarter_ok(period):raise ValueError('Period format: 2026-Q3 (calendar year)')
    primary_url(source_url)
    if basis not in (*BASIS,'unknown'):raise ValueError('Invalid reporting basis')
    if evidence_page is not None and not 1<=evidence_page<=350:raise ValueError('Invalid PDF page')
    if not any(values.get(k) is not None for k in METRICS):raise ValueError('Provide at least one source-linked value')
    if any(values.get(m) is not None and not number(values[m]) for m in METRICS):raise ValueError('Invalid metric value')
    if verified and (basis=='unknown' or evidence_page is None):raise ValueError('User verification requires a reporting basis and PDF page')
    if len(evidence_note)>3000:raise ValueError('Evidence note too long')
    def write(c):
        c.execute('''INSERT INTO quarterly_financials
        (ticker,period,revenue,ebitda,pbt,pat,source_url,basis,evidence_page,verified,evidence_note)
        VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(ticker,period) DO UPDATE SET
        revenue=excluded.revenue,ebitda=excluded.ebitda,pbt=excluded.pbt,pat=excluded.pat,
        source_url=excluded.source_url,basis=excluded.basis,evidence_page=excluded.evidence_page,
        verified=excluded.verified,evidence_note=excluded.evidence_note''',
        (ticker,period,*[values.get(k) for k in METRICS],source_url,basis,evidence_page,int(verified),evidence_note))
    if db is not None:write(db)
    else:
        with closing(connection()) as c,c:write(c)

def growth(a,b):
    if a is None or b is None or not number(a) or not number(b) or b<=0:return None
    return round((a/b-1)*100,2)

def growth_note(a,b):
    if a is None or b is None:return 'Missing comparable value'
    if b==0:return 'Zero base; percentage not meaningful'
    if b<0:
        if a>0:return 'Loss to profit; percentage not meaningful'
        if a==0:return 'Loss to break-even; percentage not meaningful'
        return ('Loss narrowed' if a>b else 'Loss widened' if a<b else 'Loss unchanged')+'; negative base'
    return 'Profit to loss' if a<0 else 'Comparable positive base'

def _prior(period):
    y,q=int(period[:4]),int(period[-1]);return f'{y-1}-Q4' if q==1 else f'{y}-Q{q-1}'
def _yoy(period):return f'{int(period[:4])-1}-Q{period[-1]}'
def period_label(period):
    return f'{("Jan–Mar","Apr–Jun","Jul–Sep","Oct–Dec")[int(period[-1])-1]} {period[:4]}'

def quarterly_snapshot(ticker):
    with closing(connection()) as db:
        rows=[dict(r) for r in db.execute('SELECT * FROM quarterly_financials WHERE ticker=? ORDER BY period DESC',(ticker,))]
    idx={r['period']:r for r in rows}
    for row in rows:
        row['verified']=bool(row['verified']);row['verification_label']='Verified by user' if row['verified'] else 'Unverified'
        row['period_label']=period_label(row['period']);row['comparison']={}
        for m in METRICS:
            detail={}
            for kind,period in [('qoq',_prior(row['period'])),('yoy',_yoy(row['period']))]:
                base=idx.get(period)
                comparable=bool(base) and row['basis'] in BASIS and row['basis']==base['basis'] and row['unit']==base['unit']
                a,b=row[m],base.get(m) if base else None
                detail.update({kind+'_pct':growth(a,b) if comparable else None,
                  kind+'_period':period,kind+'_label':period_label(period),
                  kind+'_note':growth_note(a,b) if comparable else 'Missing period or reporting basis/units differ',
                  kind+'_delta':round(a-b,2) if comparable and a is not None and b is not None else None,
                  kind+'_verified':bool(comparable and a is not None and b is not None and row['verified'] and base['verified'])})
            row['comparison'][m]=detail
        row['comparison_note']='Percentages require a positive base and matching basis/units. Verification is a user assertion.'
    return rows

def add_target(ticker,metric,period,target,unit,source_url,statement,target_kind='absolute',
               quote='',basis='unknown',tolerance=0):
    if metric not in METRICS or not quarter_ok(period):raise ValueError('Invalid metric or calendar quarter')
    if target_kind not in ('absolute','yoy_growth_pct'):raise ValueError('Invalid target type')
    primary_url(source_url)
    if unit!=('INR crore' if target_kind=='absolute' else 'percent'):raise ValueError('Target units must match target type')
    if basis not in BASIS:raise ValueError('Guidance requires standalone or consolidated basis')
    if not number(target) or not number(tolerance) or tolerance<0:raise ValueError('Invalid target or tolerance')
    if not statement.strip() or not quote.strip():raise ValueError('A guidance statement and exact source quote are required')
    with closing(connection()) as c,c:
        c.execute('''INSERT INTO guidance_targets
        (ticker,metric,period,target,unit,source_url,statement,target_kind,quote,basis,tolerance)
        VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(ticker,metric,period,source_url) DO UPDATE SET
        target=excluded.target,unit=excluded.unit,statement=excluded.statement,target_kind=excluded.target_kind,
        quote=excluded.quote,basis=excluded.basis,tolerance=excluded.tolerance''',
        (ticker,metric,period,target,unit,source_url,statement,target_kind,quote,basis,tolerance))

def guidance_comparison(ticker):
    with closing(connection()) as db:
        targets=[dict(r) for r in db.execute('SELECT * FROM guidance_targets WHERE ticker=? ORDER BY period DESC',(ticker,))]
        quarters={r['period']:dict(r) for r in db.execute('SELECT * FROM quarterly_financials WHERE ticker=?',(ticker,))}
    for t in targets:
        row=quarters.get(t['period']);actual=None;verified=False
        if row and t['basis'] in BASIS and t['basis']==row['basis'] and t['quote']:
            verified=bool(row['verified'])
            if t['target_kind']=='yoy_growth_pct':
                prev=quarters.get(_yoy(t['period']))
                if prev and prev['basis']==t['basis'] and prev['unit']==row['unit']:
                    actual=growth(row[t['metric']],prev[t['metric']]);verified=verified and bool(prev['verified'])
            elif row['unit']==t['unit']:actual=row[t['metric']]
        diff=round(actual-t['target'],2) if actual is not None else None
        if actual is None:verified=False
        t.update(actual=actual,actual_source=row['source_url'] if row else None,difference=diff,
          period_label=period_label(t['period']),actual_verified=verified,
          result='Insufficient comparable data' if diff is None else 'in line' if abs(diff)<=t['tolerance'] else 'delivered' if diff>0 else 'missed',
          note='Arithmetic comparison; higher is better. Tolerance uses Rs crore or percentage points. Quote is user-transcribed, not independently authenticated.')
    return targets
