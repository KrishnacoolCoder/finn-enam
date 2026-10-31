import fitz
import pytest
from app.pdf_financials import discover_pdf

def pdf_with(text):
    d=fitz.open();p=d.new_page();p.insert_text((40,60),text);result=d.tobytes();d.close();return result

def test_extract_candidates_no_auto_verification():
    out=discover_pdf(pdf_with('Amounts in INR crore\nRevenue from operations 1,250 1,100\nEBITDA 300 250\nProfit Before Tax 210 190\nProfit After Tax 160 140'), 'quarter.pdf')
    assert out['candidates']
    assert any(c['metric']=='revenue' and c['values'][0]['value']==1250 for c in out['candidates'])
    assert all(c['confidence']=='review_required' for c in out['candidates'])

def test_invalid_file_is_rejected():
    with pytest.raises(ValueError): discover_pdf(b'not-a-pdf','invalid.pdf')
