"""Auditable, user-confirmed quarterly financials and guidance comparisons."""
from __future__ import annotations
import re
from .storage import connection

METRICS=('revenue','ebitda','pbt','pat')
BASIS=('standalone','consolidated')

def setup():
    with connection() as db:
        db.executescript('''CREATE TABLE IF NOT EXISTS quarterly_financials(
        id INTEGER PRIMARY KEY,ticker TEXT NOT NULL,period TEXT NOT NULL,
        revenue REAL,ebitda REAL,pbt REAL,pat REAL,unit TEXT NOT NULL DEFAULT 'INR crore',
        source_url TEXT NOT NULL, UNIQUE(ticker,period));
        CREATE TABLE IF NOT EXISTS guidance_targets(
        id INTEGER PRIMARY KEY,ticker TEXT NOT NULL,metric TEXT NOT NULL,period TEXT NOT NULL,
        target REAL NOT NULL,unit TEXT NOT NULL,source_url TEXT NOT NULL,statement TEXT NOT NULL,
        UNIQUE(ticker,metric,period,source_url));''')
        cols={x[1] for x in db.execute('PRAGMA table_info(quarterly_financials)')}
        if 'basis' not in cols:db.execute("ALTER TABLE quarterly_financials ADD COLUMN basis TEXT NOT NULL DEFAULT 'unknown'")
        if 'evidence_page' not in cols:db.execute('ALTER TABLE quarterly_financials ADD COLUMN evidence_page INTEGER')
        cols={x[1] for x in db.execute('PRAGMA table_info(guidance_targets)')}
        if 'target_kind' not in cols:db.execute("ALTER TABLE guidance_targets ADD COLUMN target_kind TEXT NOT NULL DEFAULT 'absolute'")

def quarter_ok(period):return bool(re.fullmatch(r'20\d\d-Q[1-4]',period))

def save_quarter(ticker,period,values,source_url,basis='unknown',evidence_page=None):
    if not quarter_ok(period):raise ValueError('Period format: 2026-Q2 (calendar year)')
    if not source_url.startswith('https://'):raise ValueError('An original primary-source HTTPS URL is required')
    if basis not in (*BASIS,'unknown'):raise ValueError('Invalid reporting basis')
    if evidence_page is not None and not 1<=evidence_page<=350:raise ValueError('Invalid PDF page')
    if not any(values.get(k) is not None for k in METRICS):raise ValueError('Provide at least one verified value')
    for m in METRICS:
        v=values.get(m)
        if v is not None and (not isinstance(v,(int,float)) or abs(v)>1e12):raise ValueError('Invalid metric value')
    with connection() as c:
        c.execute('''INSERT INTO quarterly_financials(ticker,period,revenue,ebitda,pbt,pat,source_url,basis,evidence_page)
           VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(ticker,period) DO UPDATE SET
           revenue=excluded.revenue,ebitda=excluded.ebitda,pbt=excluded.pbt,pat=excluded.pat,
           source_url=excluded.source_url,basis=excluded.basis,evidence_page=excluded.evidence_page''',
           (ticker,period,*[values.get(k) for k in METRICS],source_url,basis,evidence_page))

def growth(a,b):
    if a is None or b is None or b==0:return None
    return round((a/b-1)*100,2)

def _prior(period):
    year,q=int(period[:4]),int(period[-1]);return f'{year-1}-Q4' if q==1 else f'{year}-Q{q-1}'

def _yoy(period):return f'{int(period[:4])-1}-Q{period[-1]}'

def quarterly_snapshot(ticker):
    with connection() as db:
        rows=[dict(r) for r in db.execute('SELECT * FROM quarterly_financials WHERE ticker=? ORDER BY period DESC',(ticker,))]
    idx={x['period']:x for x in rows};result=[]
    for r in rows:
        prev,yoy=idx.get(_prior(r['period']),{}),idx.get(_yoy(r['period']),{})
        def same_basis(a,b):return bool(b) and a['basis']!='unknown' and a['basis']==b.get('basis')
        result.append({**r,'comparison':{m:{
            'qoq_pct':growth(r[m],prev.get(m)) if same_basis(r,prev) else None,
            'yoy_pct':growth(r[m],yoy.get(m)) if same_basis(r,yoy) else None
        } for m in METRICS},
        'comparison_note':'Comparison requires matching standalone/consolidated basis and available prior periods.'})
    return result

def add_target(ticker,metric,period,target,unit,source_url,statement,target_kind='absolute'):
    if metric not in METRICS or not quarter_ok(period):raise ValueError('Invalid metric or calendar quarter')
    if target_kind not in ('absolute','yoy_growth_pct'):raise ValueError('Invalid target type')
    if not source_url.startswith('https://'):raise ValueError('An original primary-source HTTPS URL is required')
    if target_kind=='absolute' and unit!='INR crore':raise ValueError('Absolute targets must use INR crore')
    with connection() as c:c.execute('''INSERT INTO guidance_targets(ticker,metric,period,target,unit,source_url,statement,target_kind)
        VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(ticker,metric,period,source_url) DO UPDATE SET
        target=excluded.target,unit=excluded.unit,statement=excluded.statement,target_kind=excluded.target_kind''',
        (ticker,metric,period,target,unit,source_url,statement,target_kind))

def guidance_comparison(ticker):
    with connection() as db:
        targets=[dict(r) for r in db.execute('SELECT * FROM guidance_targets WHERE ticker=? ORDER BY period DESC',(ticker,))]
        quarters={r['period']:dict(r) for r in db.execute('SELECT * FROM quarterly_financials WHERE ticker=?',(ticker,))}
    for r in targets:
        actual_quarter=quarters.get(r['period']); actual=None
        if actual_quarter:
            if r['target_kind']=='yoy_growth_pct':
                prev=quarters.get(_yoy(r['period']))
                if prev and prev['basis']!='unknown' and prev['basis']==actual_quarter['basis']:
                    actual=growth(actual_quarter.get(r['metric']),prev.get(r['metric']))
            else:actual=actual_quarter.get(r['metric'])
        r['actual']=actual
        r['actual_source']=actual_quarter.get('source_url') if actual_quarter else None
        r['difference']=round(actual-r['target'],2) if actual is not None else None
        r['result']='Insufficient comparable data' if actual is None else ('Met/exceeded' if actual>=r['target'] else 'Below target')
        r['note']='User-reviewed target and figures; comparison is arithmetic, not independent verification.'
    return targets
