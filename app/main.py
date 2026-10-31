from __future__ import annotations
import os,re,json,time,threading,uuid
from pathlib import Path
from datetime import datetime,timezone,timedelta
from urllib.parse import urlparse
from fastapi import FastAPI,HTTPException,UploadFile,File,Form,Query
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel,Field,field_validator
import requests
from .core import PORTFOLIO,CATEGORIES,classify,assess_filing,signals,excerpt
from .storage import init,connection,get_setting,set_setting,DATA
from .research import ingest,list_docs,answer,guidance,MAX_BYTES
from .announcements import sync_nse
from .bse_import import import_bse,MAX_XML_BYTES
from .financials import setup as setup_financials,save_quarter,quarterly_snapshot,add_target,guidance_comparison,METRICS
from .pdf_financials import discover_pdf, MAX_PDF_BYTES
from .briefing import build_digest, markdown_digest
from .management import extract_management_change, linked_pdf_text

app=FastAPI(title='FINN | Investment Intelligence',version='4.0.0')
from .ingestion import router as ingestion_router
app.include_router(ingestion_router)
from .news import router as news_router
app.include_router(news_router)
from .screener_context import router as company_context_router
app.include_router(company_context_router)
from .primary_reports import router as primary_reports_router
app.include_router(primary_reports_router)
from .automatic_feed import router as automatic_feed_router
app.include_router(automatic_feed_router)
init()
setup_financials()
STATIC=Path(__file__).resolve().parents[1]/'static'
TICKERS={t for t,_,_ in PORTFOLIO}
_cache={}
_cache_lock=threading.Lock()

def ticker_check(value):
    t=value.strip().upper().removesuffix('.NS').removesuffix('.BO')
    if not re.fullmatch(r'[A-Z0-9&_-]{1,25}',t):raise HTTPException(400,'Invalid NSE ticker')
    return t

def market_data(ticker):
    now=time.monotonic()
    with _cache_lock:
        cached=_cache.get(ticker)
        if cached and now-cached[0]<900:return cached[1]
    try:
        import yfinance as yf
        frame=yf.Ticker(ticker+'.NS').history(period='3mo',interval='1d',auto_adjust=True)
        if frame.empty or len(frame)<2:raise ValueError('No market data returned')
        recent=frame.tail(45)
        closes=[float(v) for v in recent['Close'].tolist()]
        volumes=[int(v) for v in recent['Volume'].tolist()]
        price_threshold=float(get_setting('price_threshold','5'))
        volume_threshold=float(get_setting('volume_threshold','2'))
        sig=signals(closes,volumes,price_threshold,volume_threshold)
        result={'ticker':ticker,'price':round(closes[-1],2),'previous_close':round(closes[-2],2),'currency':'INR','date':str(recent.index[-1].date()),'history':[{'date':str(d.date()),'close':round(float(c),2)} for d,c in zip(recent.index,closes)],**sig,'status':'live_eod','error':None}
    except Exception as exc:
        result={'ticker':ticker,'price':None,'previous_close':None,'date':None,'history':[],'price_change_pct':None,'volume_multiple':None,'alerts':[],'status':'unavailable','error':str(exc)[:160]}
    if result.get('status')=='live_eod' and result.get('alerts'):
        with connection() as c:
            for kind in result['alerts']:
                c.execute('''INSERT OR IGNORE INTO market_alerts
                    (ticker,market_date,alert_type,price_change_pct,volume_multiple,created)
                    VALUES (?,?,?,?,?,?)''', (ticker,result['date'],kind,result['price_change_pct'],
                         result['volume_multiple'],datetime.now(timezone.utc).isoformat()))
    with _cache_lock:_cache[ticker]=(now,result)
    return result

class Filing(BaseModel):
    ticker:str
    title:str=Field(min_length=4,max_length=500)
    published:str
    url:str=''
    description:str=''
    source:str='manual'

class Ask(BaseModel):
    ticker:str
    question:str=Field(min_length=3,max_length=1000)

class Settings(BaseModel):
    price_threshold:float=Field(ge=0.1,le=99)
    volume_threshold:float=Field(ge=1.01,le=100)
    min_priority:int=Field(ge=0,le=100)
    event_types:list[str]|None=Field(default=None,max_length=30)

    @field_validator('event_types')
    @classmethod
    def valid_events(cls,value):
        if value is None:return value
        if any(x not in {*CATEGORIES,'unclassified'} for x in value):
            raise ValueError('Unknown event type')
        return list(dict.fromkeys(value))

@app.get('/')
def index():return FileResponse(STATIC/'index.html')

@app.get('/favicon.ico',include_in_schema=False)
def favicon():return FileResponse(STATIC/'favicon.svg',media_type='image/svg+xml')

@app.get('/static/{name}')
def asset(name:str):
    if name not in {'app.js','style.css','logo.svg','favicon.svg'}:raise HTTPException(404)
    return FileResponse(STATIC/name)

@app.get('/api/health')
def health():return {'ok':True,'product':'FINN','version':'4.0.0'}

@app.get('/api/portfolio')
def portfolio():return [{'ticker':t,'name':n,'sector':s} for t,n,s in PORTFOLIO]

@app.get('/api/settings')
def settings():
    result={k:float(get_setting(k,str(v))) if k!='min_priority' else int(get_setting(k,str(v))) for k,v in [('price_threshold',5),('volume_threshold',2),('min_priority',40)]}
    try:events=json.loads(get_setting('event_types',json.dumps([*CATEGORIES,'unclassified'])))
    except (ValueError,TypeError):events=[*CATEGORIES,'unclassified']
    if not isinstance(events,list):events=[*CATEGORIES,'unclassified']
    result['event_types']=[x for x in events if x in {*CATEGORIES,'unclassified'}]
    result['revision']=get_setting('settings_revision','')
    return result

@app.put('/api/settings')
def update_settings(p:Settings):
    with connection() as db:
        for k,v in p.model_dump().items():
            if v is not None:db.execute('INSERT OR REPLACE INTO preferences VALUES (?,?)',
                (k,json.dumps(v) if k=='event_types' else str(v)))
        db.execute('INSERT OR REPLACE INTO preferences VALUES (?,?)',('settings_revision',uuid.uuid4().hex))
    with _cache_lock:_cache.clear()
    return settings()

@app.get('/api/alerts/filings')
def filing_alerts(hours:int=Query(168,ge=1,le=8760)):
    saved=settings()
    return [g for g in grouped_filings(hours=hours,min_priority=saved['min_priority'])
            if g['category'] in saved['event_types'] and all(f['source']!='synthetic_demo' for f in g['filings'])]

@app.get('/api/market/{ticker}')
def market(ticker:str):return market_data(ticker_check(ticker))

@app.get('/api/markets')
def markets(limit:int=Query(20,ge=1,le=20)):
    # Avoid exhausting free market-data rate limits: user requests explicit refresh.
    return [market_data(t) for t,_,_ in PORTFOLIO[:limit]]

@app.get('/api/alerts')
def recent_alerts(limit:int=Query(60,ge=1,le=200)):
    with connection() as db:
        return [dict(r) for r in db.execute('''SELECT * FROM market_alerts
            ORDER BY market_date DESC, created DESC LIMIT ?''',(limit,)).fetchall()]

@app.post('/api/filings')
def create_filing(f:Filing):
    t=ticker_check(f.ticker)
    try:datetime.fromisoformat(f.published.replace('Z','+00:00'))
    except ValueError:raise HTTPException(400,'published must be ISO 8601')
    if f.url and (urlparse(f.url).scheme not in ('https','http') or not urlparse(f.url).hostname):raise HTTPException(400,'Invalid filing URL')
    cat,score=classify(f.title,f.description)
    try:
        with connection() as c:
            c.execute('INSERT INTO filings (ticker,published,title,url,category,score,source,excerpt) VALUES (?,?,?,?,?,?,?,?)',(t,f.published,f.title,f.url,cat,score,f.source,excerpt(f.description)))
    except Exception as exc:raise HTTPException(409,'Filing already exists or could not be stored') from exc
    return {'ticker':t,'category':cat,'score':score}

@app.post('/api/announcements/sync/{ticker}')
def sync_announcements(ticker:str, days:int=Query(7,ge=1,le=30)):
    symbol=ticker_check(ticker)
    try:
        return sync_nse(symbol, days)
    except RuntimeError as exc:
        raise HTTPException(status_code=503,detail=str(exc)) from exc

@app.post('/api/bse/import-bundled')
def load_bundled_bse():
    """Explicit demo action: import a fixed-date REAL exchange snapshot shipped with code."""
    fixture=Path(__file__).resolve().parents[1]/'sample_data'/'BSE_announcements_2026-10-31.txt'
    if not fixture.exists():raise HTTPException(404,'Bundled exchange snapshot unavailable')
    return import_bse(fixture.read_bytes(),'portfolio')

@app.post('/api/bse/import')
async def upload_bse_feed(file:UploadFile=File(...),scope:str=Query('portfolio',pattern='^(portfolio|all)$')):
    name=(file.filename or '').lower()
    if not name.endswith(('.xml','.txt','.rss')):
        raise HTTPException(400,'Upload a BSE .xml, .rss or .txt feed')
    data=await file.read(MAX_XML_BYTES+1)
    try:return import_bse(data,scope)
    except ValueError as exc:raise HTTPException(400,str(exc)) from exc

@app.get('/api/filings')
def filings(hours:int=Query(24,ge=1,le=8760),min_priority:int=Query(0,ge=0,le=100)):
    cutoff=(datetime.now(timezone.utc)-timedelta(hours=hours)).isoformat()
    with connection() as c:
        rows=c.execute('SELECT * FROM filings WHERE julianday(published)>=julianday(?) ORDER BY julianday(published) DESC LIMIT 2000',(cutoff,)).fetchall()
    output=[]
    for r in rows:
        item=dict(r)
        assessment=assess_filing(item['title'],item['excerpt'] or '')
        item.update(category=assessment['category'],score=assessment['score'],priority_reason=assessment['reason'],assessment_confidence=assessment['confidence'])
        if item['score'] >= min_priority:output.append(item)
    with connection() as c:
        for item in output:
            if item['category']=='management_change':
                pdf_text=linked_pdf_text(c,item['ticker'],item['url'])
                item['management_change']=extract_management_change(item['title'],pdf_text)
    return sorted(output,key=lambda x:(-x['score'],x['published']))

@app.get('/api/digest')
def investor_digest(hours:int=Query(24,ge=1,le=8760), portfolio_only:bool=True,
                    include_synthetic:bool=False,min_priority:int=Query(0,ge=0,le=100)):
    source=filings(hours=hours,min_priority=min_priority)
    # Only previously requested EOD data are used, never create 20 network requests on digest.
    now=time.monotonic()
    with _cache_lock:
        markets=[v[1] for v in _cache.values() if now-v[0]<900]
    return build_digest(source,markets,hours,min_priority,portfolio_only,include_synthetic)

@app.get('/api/digest/export',response_class=PlainTextResponse)
def export_digest(hours:int=Query(24,ge=1,le=8760),portfolio_only:bool=True):
    output=investor_digest(hours=hours,portfolio_only=portfolio_only,include_synthetic=False,min_priority=0)
    return PlainTextResponse(markdown_digest(output),media_type='text/markdown',headers={
        'Content-Disposition':'attachment; filename="FINN-investor-brief.md"'})

@app.get('/api/filings/grouped')
def grouped_filings(hours:int=Query(24,ge=1,le=8760),min_priority:int=Query(0,ge=0,le=100)):
    from .grouping import group_filings
    return group_filings(filings(hours=hours,min_priority=min_priority))

class QuarterInput(BaseModel):
    ticker:str
    period:str
    source_url:str
    basis:str=Field(default='unknown',pattern='^(standalone|consolidated|unknown)$')
    evidence_page:int|None=Field(default=None,ge=1,le=350)
    revenue:float|None=None
    ebitda:float|None=None
    pbt:float|None=None
    pat:float|None=None
    verified:bool=False
    evidence_note:str=Field(default='',max_length=3000)

class TargetInput(BaseModel):
    ticker:str
    period:str
    metric:str
    target:float
    unit:str='INR crore'
    source_url:str
    statement:str=Field(min_length=5,max_length=1000)
    target_kind:str=Field(default='absolute',pattern='^(absolute|yoy_growth_pct)$')
    quote:str=Field(min_length=5,max_length=3000)
    basis:str=Field(pattern='^(standalone|consolidated)$')
    tolerance:float=Field(default=0,ge=0,le=1e12)

@app.post('/api/financials/quarter')
def quarter_upsert(body:QuarterInput):
    try:save_quarter(ticker_check(body.ticker),body.period,body.model_dump(include=set(METRICS)),body.source_url,body.basis,body.evidence_page,body.verified,body.evidence_note)
    except ValueError as exc:raise HTTPException(400,str(exc)) from exc
    return {'ok':True,'note':'Recorded user-supplied numbers; not automatically PDF-verified.'}

@app.post('/api/financials/extract-pdf')
async def extract_financial_pdf(file:UploadFile=File(...)):
    if not (file.filename or '').lower().endswith('.pdf'):
        raise HTTPException(400,'Select an original quarterly-results PDF')
    raw=await file.read(MAX_PDF_BYTES+1)
    try:return discover_pdf(raw,file.filename or 'results.pdf')
    except ValueError as exc:raise HTTPException(400,str(exc)) from exc

@app.get('/api/financials/{ticker}')
def financial_quarters(ticker:str):return quarterly_snapshot(ticker_check(ticker))

@app.post('/api/financials/target')
def create_target(body:TargetInput):
    try:add_target(ticker_check(body.ticker),body.metric,body.period,body.target,body.unit,body.source_url,body.statement,body.target_kind,body.quote,body.basis,body.tolerance)
    except ValueError as exc:raise HTTPException(400,str(exc)) from exc
    return {'ok':True,'note':'User-transcribed guidance target; source has not been automatically checked.'}

@app.get('/api/financials/targets/{ticker}')
def targets(ticker:str):return guidance_comparison(ticker_check(ticker))

@app.get('/api/documents/{ticker}')
def documents(ticker:str):return list_docs(ticker_check(ticker))

@app.post('/api/documents/upload')
async def upload(ticker:str=Form(...),kind:str=Form('annual_report'),source_url:str=Form(''),file:UploadFile=File(...)):
    t=ticker_check(ticker)
    if kind not in {'annual_report','transcript','quarterly_results','investor_presentation'}:raise HTTPException(400,'Invalid document type')
    name=Path(file.filename or 'document').name
    if source_url and (urlparse(source_url).scheme!='https' or not urlparse(source_url).hostname):
        raise HTTPException(400,'Original document URL must be HTTPS')
    data=await file.read(MAX_BYTES+1)
    try:return ingest(t,name,data,kind,source_url)
    except ValueError as exc:raise HTTPException(400,str(exc))

@app.post('/api/research/ask')
def ask(q:Ask):return answer(ticker_check(q.ticker),q.question)

@app.get('/api/research/guidance/{ticker}')
def guidance_api(ticker:str):return {'items':guidance(ticker_check(ticker)),'note':'Candidate management guidance extracted from uploaded transcripts. Not independently verified or reconciled to actuals.'}

@app.get('/api/research/links/{ticker}')
def source_links(ticker:str):
    t=ticker_check(ticker)
    return {'screener':f'https://www.screener.in/company/{t}/consolidated/','nse':f'https://www.nseindia.com/get-quotes/equity?symbol={t}','note':'Use these directories to locate primary annual reports and transcripts. Download and upload selected originals; this app does not fabricate missing sources.'}

@app.get('/api/demo/status')
def demo_status():
    with connection() as c:
        return {'filings':c.execute('SELECT COUNT(*) FROM filings').fetchone()[0],'documents':c.execute('SELECT COUNT(*) FROM documents').fetchone()[0]}

@app.post('/api/demo/seed')
def seed():
    """Explicitly synthetic demo; never mix with real filings without visible provenance."""
    now=datetime.now(timezone.utc)
    demos=[('RELIANCE','Quarterly financial results announced — synthetic demonstration','Synthetic earnings example for application testing'),('HDFCBANK','Appointment of Chief Financial Officer — synthetic demonstration','Example management transition for demonstration'),('INFY','Credit rating downgrade — synthetic demonstration','Example credit rating notification'),('TATASTEEL','Notice of annual general meeting — synthetic demonstration','Routine compliance example'),('LT','Acquisition of a subsidiary — synthetic demonstration','Example M&A filing'),('ITC','Dividend record date announced — synthetic demonstration','Example dividend filing')]
    added=0
    for i,(ticker,title,description) in enumerate(demos):
        timestamp=(now-timedelta(hours=i+1)).isoformat()
        cat,score=classify(title,description)
        with connection() as c:
            result=c.execute('INSERT OR IGNORE INTO filings(ticker,published,title,url,category,score,source,excerpt) VALUES (?,?,?,?,?,?,?,?)',(ticker,timestamp,title,'',cat,score,'synthetic_demo',description))
            added+=result.rowcount
    sample=Path(__file__).resolve().parents[1]/'sample_documents'/'FINNDEMO_transcript.txt'
    if sample.exists() and not list_docs('FINNDEMO'):
        ingest('FINNDEMO',sample.name,sample.read_bytes(),'transcript')
    sample2=Path(__file__).resolve().parents[1]/'sample_documents'/'FINNDEMO_annual_report.txt'
    if sample2.exists() and not any(x['name']==sample2.name for x in list_docs('FINNDEMO')):
        ingest('FINNDEMO',sample2.name,sample2.read_bytes(),'annual_report')
    return {'added_filings':added,'research_demo_ticker':'FINNDEMO','notice':'All seeded filing titles and FINNDEMO documents are synthetic and for UI testing only.'}

# Optional low-frequency EOD watcher, disabled by default for predictable free-tier cost.
# Set FINN_AUTO_POLL_MINUTES=60 (>=30), deploy on an always-on process, and monitor
# the /api/alerts endpoint. It is *not* a mobile OS notification service.
@app.on_event('startup')
def optional_market_watcher():
    try:minutes=int(os.environ.get('FINN_AUTO_POLL_MINUTES','0'))
    except ValueError:minutes=0
    if minutes<30:return
    stop=threading.Event()
    def work():
        while not stop.wait(minutes*60):
            for ticker,_,_ in PORTFOLIO:
                try:market_data(ticker)
                except Exception:pass
                if stop.wait(1):return
    threading.Thread(target=work,name='finn-eod-watcher',daemon=True).start()
