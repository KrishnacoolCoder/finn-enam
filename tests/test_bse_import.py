import pytest
from app.bse_import import parse_feed,import_bse,EQUITY_CODES
from app.storage import connection

SAMPLE=b'''<?xml version="1.0"?><rss version="2.0"><channel><item><title>NTPC Ltd (532555)</title><link>https://www.bseindia.com/abc.pdf</link><scripcode>532555</scripcode><description>Unaudited Financial Results for the quarter ended September 2026</description><pubDate>31-Oct-2026 15:35:47</pubDate></item><item><title>NTPC Ltd (976684)</title><link>https://www.bseindia.com/abc.pdf</link><scripcode>976684</scripcode><description>Unaudited Financial Results for the quarter ended September 2026</description><pubDate>31-Oct-2026 15:35:47</pubDate></item></channel></rss>'''

def test_parse():
    rows=parse_feed(SAMPLE)
    assert len(rows)==2 and rows[0]['code']=='532555'
    assert rows[0]['published'].endswith('+05:30')

def test_reject_entities():
    with pytest.raises(ValueError):parse_feed(b'<!DOCTYPE rss [<!ENTITY x SYSTEM "file:///etc/passwd">]><rss/>')

def test_portfolio_mapping():
    assert len(EQUITY_CODES)==20 and EQUITY_CODES['NTPC']=='532555'

def test_dedup_is_idempotent(tmp_path,monkeypatch):
    import app.bse_import as importer
    import sqlite3
    db=tmp_path/'test.db'
    def conn():
        c=sqlite3.connect(db);c.row_factory=sqlite3.Row;return c
    with conn() as c:c.executescript('CREATE TABLE filings (id INTEGER PRIMARY KEY, ticker TEXT,published TEXT,title TEXT,url TEXT,category TEXT,score INTEGER,source TEXT,excerpt TEXT,UNIQUE(ticker,published,title));')
    monkeypatch.setattr(importer,'connection',conn)
    a=import_bse(SAMPLE);b=import_bse(SAMPLE)
    assert a['received']==2 and a['added']==1 and b['added']==0
    with conn() as c:assert c.execute('SELECT COUNT(*) FROM filings').fetchone()[0]==1
