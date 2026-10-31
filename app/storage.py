from __future__ import annotations
import os,sqlite3,threading
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
DATA=Path(os.environ.get('FINN_DATA_DIR',str(ROOT/'data')))
DATA.mkdir(parents=True,exist_ok=True)
DB=DATA/'finn.sqlite3'
_lock=threading.RLock()

def connection():
    c=sqlite3.connect(DB,check_same_thread=False,timeout=15)
    c.row_factory=sqlite3.Row
    return c

def init():
    with _lock,connection() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS filings (id INTEGER PRIMARY KEY AUTOINCREMENT, ticker TEXT NOT NULL, published TEXT NOT NULL, title TEXT NOT NULL, url TEXT DEFAULT '', category TEXT NOT NULL, score INTEGER NOT NULL, source TEXT NOT NULL DEFAULT 'user', excerpt TEXT DEFAULT '', UNIQUE(ticker,published,title));
        CREATE TABLE IF NOT EXISTS documents (id INTEGER PRIMARY KEY AUTOINCREMENT, ticker TEXT NOT NULL, name TEXT NOT NULL, kind TEXT NOT NULL, source_url TEXT DEFAULT '', added TEXT NOT NULL, pages INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS chunks (id INTEGER PRIMARY KEY AUTOINCREMENT, document_id INTEGER NOT NULL, page INTEGER NOT NULL, content TEXT NOT NULL, FOREIGN KEY(document_id) REFERENCES documents(id));
        CREATE INDEX IF NOT EXISTS chunks_doc_idx ON chunks(document_id);
        CREATE TABLE IF NOT EXISTS filing_pdf_text (
          ticker TEXT NOT NULL, url TEXT NOT NULL, content TEXT NOT NULL DEFAULT '',
          attempted TEXT NOT NULL, PRIMARY KEY(ticker,url)
        );
        CREATE TABLE IF NOT EXISTS preferences (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS company_context (
          ticker TEXT NOT NULL, basis TEXT NOT NULL, payload TEXT NOT NULL,
          fetched_at TEXT NOT NULL, PRIMARY KEY(ticker,basis)
        );
        CREATE TABLE IF NOT EXISTS news (
          id INTEGER PRIMARY KEY AUTOINCREMENT, ticker TEXT NOT NULL,
          title TEXT NOT NULL, source TEXT NOT NULL, published TEXT NOT NULL,
          link TEXT NOT NULL, UNIQUE(ticker,link)
        );
        CREATE INDEX IF NOT EXISTS news_company_date_idx ON news(ticker,published);
        CREATE TABLE IF NOT EXISTS market_alerts (
          id INTEGER PRIMARY KEY AUTOINCREMENT, ticker TEXT NOT NULL,
          market_date TEXT NOT NULL, alert_type TEXT NOT NULL, price_change_pct REAL,
          volume_multiple REAL, created TEXT NOT NULL,
          UNIQUE(ticker,market_date,alert_type)
        );
        CREATE INDEX IF NOT EXISTS alerts_marketdate_idx ON market_alerts(market_date);
        ''')
        cols={r[1] for r in c.execute('PRAGMA table_info(documents)')}
        if 'auto_loaded' not in cols:c.execute('ALTER TABLE documents ADD COLUMN auto_loaded INTEGER NOT NULL DEFAULT 0')
        if 'content_sha256' not in cols:c.execute("ALTER TABLE documents ADD COLUMN content_sha256 TEXT NOT NULL DEFAULT ''")
        c.execute("CREATE UNIQUE INDEX IF NOT EXISTS auto_report_identity ON documents(ticker,source_url) WHERE auto_loaded=1")

def get_setting(k,default):
    with connection() as c:
        r=c.execute('SELECT value FROM preferences WHERE key=?',(k,)).fetchone()
    return r['value'] if r else default

def set_setting(k,v):
    with _lock,connection() as c:c.execute('INSERT OR REPLACE INTO preferences VALUES (?,?)',(k,str(v)))
