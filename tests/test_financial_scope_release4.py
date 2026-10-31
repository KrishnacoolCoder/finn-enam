import sqlite3
from app import financials

def test_growth_only_when_basis_matches(tmp_path,monkeypatch):
    path=tmp_path/'finance.sqlite3'
    def conn():
        db=sqlite3.connect(path);db.row_factory=sqlite3.Row;return db
    monkeypatch.setattr(financials,'connection',conn)
    financials.setup()
    url='https://www.bseindia.com/financial-results.pdf'
    financials.save_quarter('NTPC','2025-Q3',{'revenue':100},url,'standalone',3)
    financials.save_quarter('NTPC','2026-Q2',{'revenue':110},url,'consolidated',3)
    financials.save_quarter('NTPC','2026-Q3',{'revenue':121},url,'consolidated',3)
    records=financials.quarterly_snapshot('NTPC')
    current=next(r for r in records if r['period']=='2026-Q3')
    assert current['comparison']['revenue']['qoq_pct']==10
    assert current['comparison']['revenue']['yoy_pct'] is None # mismatched scope
    financials.add_target('NTPC','revenue','2026-Q3',15,'percent',url,'We target 15 percent revenue growth','yoy_growth_pct')
    assert financials.guidance_comparison('NTPC')[0]['result']=='Insufficient comparable data'

def test_growth_target_must_use_same_units(tmp_path,monkeypatch):
    path=tmp_path/'targets.sqlite3'
    def conn():
        db=sqlite3.connect(path);db.row_factory=sqlite3.Row;return db
    monkeypatch.setattr(financials,'connection',conn)
    financials.setup()
    url='https://www.bseindia.com/report.pdf'
    financials.save_quarter('ABC','2025-Q3',{'revenue':100},url,'consolidated')
    financials.save_quarter('ABC','2026-Q3',{'revenue':120},url,'consolidated')
    financials.add_target('ABC','revenue','2026-Q3',15,'percent',url,'Expected 15% YoY growth','yoy_growth_pct')
    x=financials.guidance_comparison('ABC')[0]
    assert x['actual']==20 and x['difference']==5 and x['result']=='Met/exceeded'
