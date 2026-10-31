from app.core import classify,signals,extract_guidance
from app.research import ingest,retrieve,answer

def test_classification():
    assert classify('CFO resignation')[0]=='management_change'
    assert classify('quarterly financial results')[0]=='results'
    assert classify('Compliance certificate')[0]=='unclassified'

def test_signal_thresholds():
    result=signals([100]*20+[106],[100]*20+[250],5,2)
    assert result['price_change_pct']==6.0
    assert result['volume_multiple']==2.5
    assert set(result['alerts'])=={'price','volume'}

def test_no_market_series():
    assert signals([],[])['alerts']==[]

def test_guidance_candidates():
    assert extract_guidance('We expect revenue growth of 15 percent next year.')

def test_document_retrieval(tmp_path,monkeypatch):
    import app.storage as st
    # Use temporary in-memory isolation through a temp SQLite path.
    db=tmp_path/'test.sqlite3'
    monkeypatch.setattr(st,'DB',db)
    st.init()
    import app.research as research
    monkeypatch.setattr(research,'connection',st.connection)
    doc='This fictional company generated operating cash flow of INR 190 crore, compared with PAT of INR 140 crore. The company invested in new warehouse capacity.'
    ingest('TESTCO','report.txt',doc.encode())
    retrieved=retrieve('TESTCO','How much operating cash flow did the company generate?')
    assert retrieved and '190' in retrieved[0]['text']
