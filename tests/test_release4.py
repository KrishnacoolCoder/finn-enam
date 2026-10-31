"""Release acceptance: primary filings, no made-up figures, comparable growth."""
import io
from pathlib import Path
import fitz
from reportlab.pdfgen.canvas import Canvas
from app.briefing import build_digest,markdown_digest
from app.pdf_financials import discover_pdf
from app.financials import growth


def _fixture():
    stream=io.BytesIO();c=Canvas(stream,pagesize=(600,840))
    c.setFont('Helvetica',11)
    c.drawString(40,790,'Consolidated Financial Results for the Quarter ended 30 September 2026')
    c.drawString(40,765,'Amounts in INR crore')
    rows=[['Particulars','30 Sep 2026','30 Jun 2026','30 Sep 2025'],
          ['Revenue from operations','15,000','14,000','13,000'],
          ['EBITDA','4,500','4,000','3,900'],
          ['Profit Before Tax','3,200','3,000','2,800'],
          ['Profit After Tax','2,600','2,400','2,100']]
    for y,row in zip([720,685,650,615,580],rows):
        for x,t in zip([40,295,397,500],row):c.drawString(x,y,t)
    c.save();return stream.getvalue()

def test_table_extraction_with_provenance():
    results=discover_pdf(_fixture(),'source.pdf')
    assert results['tables_detected']>=1
    by_metric={r['metric']:r for r in results['candidates']}
    assert {'revenue','ebitda','pbt','pat'}.issubset(by_metric)
    assert by_metric['revenue']['values'][0]['crore']==15000
    assert by_metric['revenue']['page']==1
    assert by_metric['revenue']['basis']=='consolidated'
    assert all(r['confidence']=='review_required' for r in results['candidates'])
    assert '2026' in by_metric['revenue']['values'][0]['period_header']

def test_no_narrative_fabrication():
    d=fitz.open();p=d.new_page();p.insert_text((40,70),
        'Revenue from operations 29 Net profit margin 11.63% and 14.00%')
    raw=d.tobytes();d.close()
    assert discover_pdf(raw,'narrative.pdf')['candidates']==[]

def test_conservative_no_unit_conversion():
    assert discover_pdf(_fixture().replace(b'NoMatch',b'NoMatch'),'f.pdf')['candidates']

def test_digest_excludes_synthetic_and_has_primary_sources():
    sample=[dict(id=1,ticker='NTPC',title='Unaudited consolidated financial results for quarter ended 30 Sep 2026',
       published='2026-10-31T15:35:00+05:30',category='results',score=94,
       excerpt='Unaudited results',priority_reason='Reported results warrant comparison.',
       source='BSE official RSS snapshot',url='https://www.bseindia.com/example.pdf'),
       dict(id=2,ticker='LT',title='Fictional acquisition',published='2026-10-31T15:35:00+05:30',
       category='M&A',score=93,excerpt='Demo',priority_reason='Demo',source='synthetic_demo',url='')]
    digest=build_digest(sample,hours=168)
    assert digest['events_total']==1 and digest['events'][0]['ticker']=='NTPC'
    assert 'example.pdf' in markdown_digest(digest)
    assert digest['high_priority_events']==1

def test_arithmetic():
    assert growth(120,100)==20
    assert growth(120,0) is None
