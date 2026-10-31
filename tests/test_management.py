"""Fictional names in realistic exchange headline formats; no biography fixtures."""
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.core import classify
from app.management import extract_management_change


@pytest.mark.parametrize('headline,expected', [
    ('Appointment of Mr. Rahul Jain as Chief Financial Officer with effect from November 1, 2026',
     ('Rahul Jain', 'CFO', 'appointed', '2026-11-01')),
    ('Ms. Priya Nair, Chief Executive Officer, has resigned effective 31 October 2026',
     ('Priya Nair', 'CEO', 'resigned', '2026-10-31')),
    ('Retirement of Mr. Sanjay Mehta as Independent Director w.e.f. 30.09.2026',
     ('Sanjay Mehta', 'Independent Director', 'retired', '2026-09-30')),
    ('Appointment of Company Secretary and Compliance Officer',
     ('', 'Company Secretary', 'appointed', '')),
    ('CFO appointed: Anita Shah, effective 2026-11-01',
     ('Anita Shah', 'CFO', 'appointed', '2026-11-01')),
    ('APPOINTMENT OF MR. RAHUL JAIN AS CHIEF FINANCIAL OFFICER EFFECTIVE 01/11/2026',
     ('RAHUL JAIN', 'CFO', 'appointed', '2026-11-01')),
])
def test_realistic_headlines(headline, expected):
    assert classify(headline)[0] == 'management_change'
    data = extract_management_change(headline)
    assert tuple(data[k] for k in ('person_name', 'role', 'action', 'effective_date')) == expected


def test_pdf_enrichment_uses_event_sentence_not_letter_date_or_bio():
    text = '''Date: 20 October 2026
    The Board approved the appointment of Ms. Kavita Rao as Chief Financial Officer
    with effect from 1st November 2026.
    Profile: Kavita Rao previously worked at Fictional Industries.
    Yours faithfully, Company Secretary Amit Shah'''
    assert extract_management_change('Appointment of Chief Financial Officer', text) == {
        'person_name': 'Kavita Rao', 'role': 'CFO', 'action': 'appointed', 'effective_date': '2026-11-01'}


def test_invalid_or_ambiguous_values_stay_blank():
    assert extract_management_change('Mr. Rahul Jain has not resigned as CFO')['action']==''
    assert extract_management_change('CFO resigned on 31 October 2026')['effective_date'] == ''
    assert extract_management_change('CFO resigned effective 31 February 2026')['effective_date'] == ''
    assert not any(extract_management_change(
        'Mr. Ravi Shah resigned as CFO; Ms. Anita Jain appointed as CFO effective 1 November 2026').values())
    assert extract_management_change('Change in senior management') == {
        'person_name': '', 'role': '', 'action': '', 'effective_date': ''}


def test_api_matches_only_exact_filing_pdf_and_group_preserves_card(tmp_path, monkeypatch):
    from app import storage
    from app.main import app
    monkeypatch.setattr(storage, 'DB', tmp_path/'management.sqlite3')
    storage.init()
    now = datetime.now(timezone.utc).isoformat()
    source = 'https://www.bseindia.com/filing.pdf'
    with storage.connection() as db:
        db.execute('''INSERT INTO filings(ticker,published,title,url,category,score)
            VALUES (?,?,?,?,?,?)''', ('NTPC', now, 'Appointment of Chief Financial Officer', source, 'management_change', 92))
        for ticker, url, name, content in [
            ('NTPC', source, 'filing.pdf', 'Mr. Rahul Jain was appointed as Chief Financial Officer effective 1 November 2026.'),
            ('NTPC', 'https://example.com/other.pdf', 'other.pdf', 'Mr. Wrong Person was appointed as CEO effective 2 November 2026.'),
            ('ITC', source, 'wrong.pdf', 'Mr. Other Person was appointed as CEO effective 3 November 2026.'),
        ]:
            doc = db.execute('''INSERT INTO documents(ticker,name,kind,source_url,added)
                VALUES (?,?,?,?,?)''', (ticker,name,'annual_report',url,now)).lastrowid
            db.execute('INSERT INTO chunks(document_id,page,content) VALUES (?,?,?)', (doc,1,content))
    client = TestClient(app)
    row = client.get('/api/filings?hours=24').json()[0]
    assert row['management_change'] == dict(person_name='Rahul Jain',role='CFO',action='appointed',effective_date='2026-11-01')
    assert client.get('/api/filings/grouped?hours=24').json()[0]['filings'][0]['management_change'] == row['management_change']
    with storage.connection() as db:
        db.execute('DELETE FROM documents WHERE ticker=? AND source_url=?', ('NTPC', source))
    assert client.get('/api/filings?hours=24').json()[0]['management_change']['person_name'] == ''


def test_pdf_collection_is_cached_bounded_and_never_fetches_bio(tmp_path, monkeypatch):
    import fitz
    import requests
    from app import storage
    from app.management import cache_management_pdfs, linked_pdf_text
    monkeypatch.setattr(storage,'DB',tmp_path/'pdf.sqlite3');storage.init()
    now = datetime.now(timezone.utc).isoformat()
    source = 'https://www.bseindia.com/xml-data/corpfiling/AttachLive/notice.pdf'
    with storage.connection() as db:
        for i,url in enumerate((source, 'https://biography.example/person.pdf')):
            db.execute('''INSERT INTO filings(ticker,published,title,url,category,score)
                VALUES (?,?,?,?,?,?)''', ('NTPC',now,f'CFO appointed: Anita Shah - notice {i}',url,'management_change',92))
    with fitz.open() as pdf:
        pdf.new_page().insert_text((30,30),'Anita Shah was appointed as CFO effective 1 November 2026.')
        raw = pdf.tobytes()
    calls=[]
    class Response:
        status_code=200
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def iter_content(self,size):yield raw
    def get(url,**kwargs):
        calls.append(url)
        assert kwargs['allow_redirects'] is False and kwargs['stream'] is True
        return Response()
    monkeypatch.setattr(requests,'get',get)
    assert cache_management_pdfs()==1
    assert cache_management_pdfs()==0
    assert calls==[source]
    with storage.connection() as db:
        text=linked_pdf_text(db,'NTPC',source)
        assert extract_management_change('Appointment of CFO',text)['person_name']=='Anita Shah'
        assert db.execute('SELECT COUNT(*) FROM documents').fetchone()[0]==0
        assert db.execute('SELECT COUNT(*) FROM chunks').fetchone()[0]==0


def test_blocked_pdf_preserves_headline_fields_and_does_not_retry_immediately(tmp_path, monkeypatch):
    import requests
    from app import storage
    from app.management import cache_management_pdfs, linked_pdf_text
    monkeypatch.setattr(storage,'DB',tmp_path/'blocked.sqlite3');storage.init()
    source='https://www.bseindia.com/notice.pdf'
    with storage.connection() as db:
        db.execute('''INSERT INTO filings(ticker,published,title,url,category,score)
            VALUES (?,?,?,?,?,?)''',('NTPC',datetime.now(timezone.utc).isoformat(),'CFO resigned',source,'management_change',92))
    def blocked(*args,**kwargs):raise requests.Timeout()
    monkeypatch.setattr(requests,'get',blocked)
    assert cache_management_pdfs()==1
    assert cache_management_pdfs()==0
    with storage.connection() as db:
        assert linked_pdf_text(db,'NTPC',source)==''
    assert extract_management_change('CFO resigned')['person_name']==''


def test_authenticated_pdf_enrichment_replays_without_duplicate_filing(tmp_path,monkeypatch):
    from app import storage
    from app.main import app
    monkeypatch.setattr(storage,'DB',tmp_path/'upload.sqlite3');storage.init()
    monkeypatch.setenv('INGEST_TOKEN','test-pdf-token')
    data=[dict(ticker='NTPC',published=datetime.now(timezone.utc).isoformat(),
        title='Appointment of Chief Financial Officer',url='https://www.bseindia.com/notice.pdf',
        pdf_text='Ms. Priya Nair was appointed as CFO effective 1 November 2026.')]
    client=TestClient(app)
    assert client.post('/api/ingest',json=data).status_code==403
    for _ in range(2):
        assert client.post('/api/ingest',json=data,headers={'X-Ingest-Token':'test-pdf-token'}).status_code==200
    rows=client.get('/api/filings').json()
    assert len(rows)==1 and rows[0]['management_change']['person_name']=='Priya Nair'
