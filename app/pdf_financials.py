"""Table-first PDF financial extraction with explicit provenance and abstention.

Only rows within financial-statement tables are offered as candidates. Never turn
narrative percentages into a quarterly revenue number. Every candidate has the
original source page, table row, period header, basis, and unit when detectable.
"""
from __future__ import annotations
import re
from pathlib import Path
import fitz

MAX_PDF_BYTES=20*1024*1024
MAX_PAGES=350
METRIC_LABELS={
 'revenue':[r'^revenue\s+from\s+operations\b',r'^net\s+sales\b',r'^income\s+from\s+operations\b'],
 'ebitda':[r'^ebitda\b',r'^earnings\s+before\s+interest\s*,?\s*tax\b'],
 'pbt':[r'^(?:profit|loss)\s*(?:/|and)?\s*(?:\(?loss\)?)?\s*before\s+tax\b',r'^profit\s+before\s+tax\b'],
 'pat':[r'^profit\s*(?:/|and)?\s*(?:\(?loss\)?)?\s*(?:after\s+tax|for\s+the\s+(?:period|year))\b',r'^net\s+profit\s+(?:after\s+tax|for\s+the\s+period)\b'],
}
NUMERIC=re.compile(r'^\(?-?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?\)?$')
UNIT_RE=re.compile(r'\b(?:in|amounts?\s+in|figures?\s+in)\s*(?:rs\.?|inr|₹)?\s*(crores?|cr\.?|lakhs?|lacs?|millions?|billions?)\b',re.I)
FACTOR={'crore':1,'cr':1,'lakh':.01,'lac':.01,'million':.1,'billion':100}
PERIOD_RE=re.compile(r'(?:(?:quarter|three\s+months|year|half.year|six\s+months)\s+ended|(?:30|31|28|29)[-\s/](?:mar|jun|sep|dec)|(?:mar|jun|sep|dec)[a-z]*\s+20\d\d)',re.I)
FINANCIAL_CONTEXT=re.compile(r'financial\s+results|statement\s+of\s+(?:profit|standalone|consolidated)|statement\s+of\s+unaudited|particulars|quarter\s+ended|three\s+months\s+ended',re.I)
BAD_ROW=re.compile(r'\b(?:margin|percentage|%|growth|change|ratio|\byoy\b|\bqoq\b|per\s+share|earnings\s+per\s+share|\beps\b)\b',re.I)

def norm(value):return ' '.join(str(value or '').replace('\n',' ').split()).strip()

def metric_of(label):
    s=norm(label).lower().replace('–','-').replace('—','-')
    if not s or BAD_ROW.search(s):return None
    # remove statement row serial only (e.g. '1 Revenue from operations')
    s=re.sub(r'^\(?\d{1,2}\)?[.)]?\s+', '',s)
    for metric,patterns in METRIC_LABELS.items():
        if any(re.match(p,s,re.I) for p in patterns):
            # Prevent narrative descriptions masquerading as rows.
            if len(s)>105 or len(s.split())>16:return None
            return metric
    return None

def numeric(value):
    s=norm(value).replace('₹','').replace(' ','').replace('−','-')
    if s in ('-','—','–','', 'NA','N/A'):return None
    if s.endswith('%') or not NUMERIC.fullmatch(s):return None
    negative=s.startswith('(') and s.endswith(')')
    try:return -float(s[1:-1].replace(',','')) if negative else float(s.replace(',',''))
    except ValueError:return None

def read_unit(context):
    context=re.sub(r'(?:rs\.?|inr|₹)\s+in\s+', 'in ', context, flags=re.I)
    m=UNIT_RE.search(context)
    if m:
        u=m.group(1).lower().rstrip('s.')
        return 'lakh' if u in ('lak','lakh') else 'crore' if u in ('cr','crore') else u
    return None

def basis(context):
    t=context.lower()
    a='consolidated' in t;b='standalone' in t
    return 'both / verify section' if a and b else 'consolidated' if a else 'standalone' if b else 'unknown / verify'

def _quarter_headers(rows,idx,label_index):
    # Use the nearest table header; never infer period from a numeric column.
    header=[]
    for preceding in rows[max(0,idx-32):idx]:
        line=' '.join(norm(x) for x in preceding)
        if re.search(r'quarter|ended|20\d\d|particulars|standalone|consolidated|audited',line,re.I):
            header.append([norm(x) for x in preceding[label_index+1:]])
    output=[]
    ncols=max((len(a) for a in header),default=0)
    for j in range(ncols):
        labels=[row[j] for row in header if j<len(row) and row[j]]
        output.append(' / '.join(dict.fromkeys(labels))[:130] or 'Column '+str(j+1))
    return output

def _table_rows(table,page_number,context,tab_index):
    extracted=table.extract()
    if not extracted:return []
    unit=read_unit(context); base=basis(context)
    result=[]
    for ri,row in enumerate(extracted):
        if not row:continue
        cells=[norm(c) for c in row]
        for label_col in range(min(3,len(cells))):
            metric=metric_of(cells[label_col])
            if not metric:continue
            # Some PDFs split numeric values into cells. Only numbers AFTER the label count.
            cell_numbers=[(j,numeric(cells[j])) for j in range(label_col+1,len(cells))]
            values=[{'column':j+1,'raw':cells[j], 'value':v, 'crore':round(v*FACTOR[unit],4) if unit else None}
                    for j,v in cell_numbers if v is not None]
            if not values:continue
            hdr=_quarter_headers(extracted,ri,label_col)
            for v in values:v['period_header']=hdr[v['column']-label_col-2] if 0<=v['column']-label_col-2<len(hdr) else 'unresolved — check PDF'
            result.append({'metric':metric,'page':page_number,'table':tab_index,'row':ri+1,
                           'line':cells[label_col],'values':values,'unit_detected':unit,
                           'basis':base,'evidence':' | '.join(cells)[:680],
                           'confidence':'review_required', 'method':'pdf_table'})
            break
    return result

def _lines_fallback(page,page_number):
    """Only use text lines on statement pages; never scrape numbers near narrative keywords."""
    txt=page.get_text(sort=True)
    if not FINANCIAL_CONTEXT.search(txt):
        # Plain machine-readable result extracts can lack a table heading. Only allow
        # such pages when at least three distinct accounting metrics are row-anchored.
        labels=[metric_of(norm(z)) for z in txt.splitlines()]
        if len({x for x in labels if x})<3 or not read_unit(txt):return []
    lines=[norm(z) for z in txt.splitlines() if norm(z)]
    context=' '.join(lines[:90]); unit=read_unit(context)
    # Require rows with an anchored accounting label AND >=2 whitespace-delimited amounts.
    out=[]
    for line in lines:
        metric=metric_of(line)
        if not metric:continue
        pieces=line.split()
        vals=[]
        for s in pieces:
            val=numeric(s)
            if val is not None:vals.append({'column':len(vals)+1,'raw':s,'value':val,
                'crore':round(val*FACTOR[unit],4) if unit else None,'period_header':'unresolved — check PDF'})
        if len(vals)<2 or len(vals)>8:continue
        # Reject prose: numeric tokens must occupy the end of the line.
        suffix=re.search(r'(?:\s+\(?-?[\d,.]+\)?){2,}\s*$',line)
        if not suffix or len(line[:suffix.start()].split())>16:continue
        out.append({'metric':metric,'page':page_number,'table':None,'row':None,'line':line[:160],
                    'values':vals,'unit_detected':unit,'basis':basis(context),
                    'evidence':line[:450],'confidence':'review_required','method':'strict_row_fallback'})
    return out

def discover_pdf(data:bytes,filename:str):
    if len(data)>MAX_PDF_BYTES:raise ValueError('PDF exceeds 20 MB')
    if not data.startswith(b'%PDF'):raise ValueError('This is not a PDF document')
    try:pdf=fitz.open(stream=data,filetype='pdf')
    except Exception as exc:raise ValueError('Cannot open PDF') from exc
    try:
        if pdf.needs_pass:raise ValueError('Password-protected PDFs are not supported')
        if len(pdf)>MAX_PAGES:raise ValueError('PDF exceeds 350 pages')
        found=[];scanned=0;tables_count=0
        for pno,page in enumerate(pdf,1):
            text=page.get_text(sort=True)
            if not text.strip():continue
            scanned+=1
            # Table headers can be on the preceding page. Page text is still used only for metadata.
            has_tables=False
            try:
                tables=page.find_tables(strategy='lines_strict').tables
                if not tables:tables=page.find_tables(strategy='text').tables
                tables_count+=len(tables)
                for i,table in enumerate(tables,1):
                    context= (text[:2400]+' '+ ' '.join(' '.join(norm(c) for c in row) for row in table.extract()[:5]))
                    candidates=_table_rows(table,pno,context,i)
                    if candidates:has_tables=True;found.extend(candidates)
            except (AttributeError,ValueError,RuntimeError):pass
            if not has_tables:found.extend(_lines_fallback(page,pno))
            if len(found)>250:break
        # Only exact (metric,page,table,row,raw) repeats are eliminated.
        unique={}
        for c in found:
            key=(c['metric'],c['page'],c['table'],c['row'],c['evidence'])
            unique[key]=c
        found=list(unique.values())[:250]
        return {'filename':Path(filename).name,'pages_with_text':scanned,'tables_detected':tables_count,
                'candidates':found,'notice':('Review required. Table labels, headers, units and reporting basis are evidence, '
                  'not automatic verification. Never use unknown-unit candidates as INR crore. '
                  'If no valid financial statement row is found, the extractor abstains. ' 
                  'Scanned PDFs require a selectable-text version.')}
    finally:pdf.close()
