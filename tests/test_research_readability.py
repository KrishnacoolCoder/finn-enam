import fitz
import pytest

from app import research,storage


@pytest.fixture
def database(tmp_path,monkeypatch):
    monkeypatch.setattr(storage,'DB',tmp_path/'readable.sqlite3');storage.init()
    monkeypatch.delenv('GEMINI_API_KEY',raising=False)
    monkeypatch.delenv('GROQ_API_KEY',raising=False)


def test_pdf_columns_keep_original_paragraph_order():
    left='Our consumer business serves customers through retail stores. Revenue increased to INR 120 crore during FY2026.'
    right='The energy business operates refining facilities. Production capacity increased during FY2026.'
    with fitz.open() as pdf:
        page=pdf.new_page(width=700,height=500)
        page.insert_textbox((30,40,310,400),left,fontsize=12)
        page.insert_textbox((370,40,650,400),right,fontsize=12)
        text=research.pdf_page_text(page)
    assert left in text and right in text
    assert text.index(left)<text.index(right)


def test_business_and_risk_cards_exclude_auditor_boilerplate(database):
    audit=b'Our audit addresses material misstatement and reasonable assurance. Those charged with governance oversee risk management and business opportunities.'
    business=b'Our business segments include consumer retail and digital services. Customers access our products through retail stores and online platforms.'
    risk=b'Strengths include a broad distribution network. Opportunities include digital expansion. Threats include volatile input costs and competitive risks.'
    for name,text in [('audit.txt',audit),('business.txt',business),('risk.txt',risk)]:research.ingest('TESTCO',name,text)
    business_results=research.retrieve('TESTCO',"Business snapshot: What are the company's main business segments, products, customers and business risks?")
    risk_results=research.retrieve('TESTCO','Bull vs bear: Identify documented business opportunities and risks, with evidence for both sides.')
    assert business_results and risk_results
    assert all(r['document']!='audit.txt' for r in business_results+risk_results)
    assert research.retrieve('TESTCO','How does the audit address material misstatement and reasonable assurance?')[0]['document']=='audit.txt'


def test_extractive_mode_returns_short_complete_sentences(database):
    text='Revenue increased to INR 120 crore during FY2026. EBITDA improved to INR 30 crore during FY2026. '+('The company operates across multiple markets. '*40)
    research.ingest('TESTCO','results.txt',text.encode())
    answer=research.answer('TESTCO','What revenue and EBITDA were reported?')
    assert 'Revenue increased to INR 120 crore during FY2026.' in answer['answer']
    assert len(answer['answer'])<800 and '[results.txt, 1]' in answer['answer']
    assert '\u2026' not in answer['answer']


def test_unreadable_fragments_are_not_dumped_as_an_answer():
    results=[{'text':'work; our users 2026 by production audit other assets and the of to new '+('mixed columns '*70),
              'document':'broken.pdf','page':53,'score':.05}]
    answer=research.extractive_answer(results,'What are the business segments?')
    assert answer['answer'].startswith('insufficient evidence') and not answer['citations']


def test_long_model_quote_rejected_even_if_verbatim():
    text='Revenue grew by 12 percent during FY2026. '*30
    with pytest.raises(ValueError):research.checked_answer({'insufficient_evidence':False,
        'claims':[{'source_id':1,'quote':text}]},[{'text':text,'document':'report.pdf','page':1}])


def test_reindex_preserves_document_identity_and_pages(database):
    with fitz.open() as pdf:
        for _ in range(2):pdf.new_page().insert_text((40,60),'Revenue increased to INR 120 crore during FY2026. EBITDA improved in the period.')
        raw=pdf.tobytes()
    first=research.ingest('TESTCO','report.pdf',raw,auto_loaded=True,url='https://example.com/report.pdf')
    with storage.connection() as db:db.execute('UPDATE documents SET extraction_version=1')
    second=research.ingest('TESTCO','report.pdf',raw,auto_loaded=True,url='https://example.com/report.pdf')
    assert second['document_id']==first['document_id'] and second['pages']==2
    with storage.connection() as db:
        assert db.execute('SELECT COUNT(*) FROM documents').fetchone()[0]==1
        assert db.execute('SELECT extraction_version FROM documents').fetchone()[0]==research.PDF_EXTRACTION_VERSION
        assert {r[0] for r in db.execute('SELECT DISTINCT page FROM chunks')}=={1,2}
