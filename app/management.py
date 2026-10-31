"""Conservative management-change extraction; no network, biographies or LLMs."""
from __future__ import annotations

import re
from datetime import datetime

# Prefer specific titles over the word 'director' in 'board of directors'.
ROLES = [
    (r'chief financial officer|\bCFO\b', 'CFO'),
    (r'chief executive officer|\bCEO\b', 'CEO'),
    (r'chief operating officer|\bCOO\b', 'COO'),
    (r'managing director', 'Managing Director'),
    (r'company secretary', 'Company Secretary'),
    (r'non[- ]executive independent director|independent director', 'Independent Director'),
    (r'non[- ]executive director', 'Non-executive Director'),
    (r'executive director', 'Executive Director'),
    (r'chair(?:man|person)', 'Chairperson'),
    (r'(?<!of )\bdirector\b(?!s)', 'Director'),
]
ACTION = r'\b(?:re-?appoint(?:ed|ment)|appoint(?:ed|ment)|resign(?:ed|ation)|retir(?:ed|ement))\b'
TOKEN = r"(?:[A-Z][a-zA-Z'’-]+|[A-Z]\.?)"
NAME = rf'(?-i:{TOKEN}(?:\s+{TOKEN}){{1,5}}?)'
HONORIFIC = r'(?:Mr|Mrs|Ms|Dr|Shri|Smt)\.?\s+'
FORBIDDEN = {'chief','officer','director','board','financial','executive','appointment',
             'resignation','retirement','company','secretary','effective','limited','ltd',
             'november','october','september','january','february','march','april','may',
             'june','july','august','december','change','management','regulation'}
MONTH = r'(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)'
DATE = rf'(?:\d{{4}}-\d{{2}}-\d{{2}}|\d{{1,2}}[./-]\d{{1,2}}[./-]\d{{4}}|\d{{1,2}}(?:st|nd|rd|th)?[\s-]+{MONTH}[\s,-]+\d{{4}}|{MONTH}\s+\d{{1,2}}(?:st|nd|rd|th)?[,]?\s+\d{{4}})'


def _date(value):
    value = re.sub(r'(?<=\d)(st|nd|rd|th)\b', '', value, flags=re.I)
    value = re.sub(r'[,./-]', ' ', value)
    value = ' '.join(value.split())
    for fmt in ('%Y %m %d', '%d %m %Y', '%d %B %Y', '%d %b %Y', '%B %d %Y', '%b %d %Y'):
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            pass
    return ''


def extract_management_change(headline: str, pdf_text: str = '') -> dict:
    """Missing or ambiguous fields are empty strings, never inferred from other filings.

    PDF text must come from the exact linked filing. Process event-bearing
    sentences only, avoiding letter dates, signatures and annexed biographies.
    """
    result = dict(person_name='', role='', action='', effective_date='')
    pdf_text = re.sub(r'(?<!\n)\n(?!\n)', ' ', (pdf_text or '')[:150000])
    text = ' '.join((headline or '').split()) + '\n' + pdf_text
    # Honorific/initial periods are not sentence boundaries.
    clauses = re.split(r'\n+|(?<=[.!?])\s+(?=[A-Z])', re.sub(
        r'\b((?i:Mr|Mrs|Ms|Dr|Shri|Smt)|[A-Z])\.(?=\s)', r'\1', text))
    clauses = [' '.join(x.split()) for x in clauses if re.search(ACTION, x, re.I)]
    actions, roles, names, dates = set(), set(), set(), set()
    for clause in clauses:
        if re.search(r'\b(?:not|no)\s+(?:been\s+)?(?:appointed|resigned|retired|appointment|resignation|retirement)|\bproposed\s+appointment', clause, re.I):
            continue
        for match in re.finditer(ACTION, clause, re.I):
            word = match.group().lower()
            actions.add('appointed' if 'appoint' in word else 'resigned' if 'resign' in word else 'retired')
        for pattern, role in ROLES:
            if re.search(pattern, clause, re.I):
                roles.add(role)
                break
        patterns = [
            rf'{HONORIFIC}(?P<name>{NAME})(?=\s*(?:,|\(|\bas\b|\bhas\b|\bis\b|\bwas\b|\bwill\b|\bresign|\bretir|\bappoint|\bw\.?e\.?f|\bwith effect|$))',
            rf'(?:appointment|resignation|retirement) of (?P<name>{NAME})(?=\s*(?:,|\bas\b|\bwith\b|\beffective\b|$))',
            rf'(?P<name>{NAME})\s+(?:(?:has been|was|is|has)\s+)?(?:appointed|resigned|retired)\b',
            rf'\b(?:appointed|resigned|retired)\s*:\s*(?P<name>{NAME})(?=\s*(?:,|\beffective\b|$))',
        ]
        for pattern in patterns:
            for match in re.finditer(pattern, clause, re.I):
                name = re.sub(r'^(?:Mr|Mrs|Ms|Dr|Shri|Smt)\.?\s+', '', match['name'], flags=re.I).strip()
                if not any(w.lower().strip('.') in FORBIDDEN for w in name.split()):
                    names.add(name)
        for match in re.finditer(rf'(?:with effect from|effective(?:\s+(?:from|on))?|w\.?\s*e\.?\s*f\.?)\s*[:,-]?\s*(?:(?:the )?(?:close of (?:business|business hours)|end of (?:the )?day)\s+(?:on\s+)?)?({DATE})', clause, re.I):
            value = _date(match[1])
            if value:
                dates.add(value)
    # Multiple changes need individual review: do not construct a mixed-person card.
    if len(actions) > 1 or len(names) > 1:
        return result
    for field, values in (('person_name', names), ('role', roles), ('action', actions), ('effective_date', dates)):
        if len(values) == 1:
            result[field] = next(iter(values))
    return result


def linked_pdf_text(db, ticker: str, source_url: str) -> str:
    """Only indexed PDF pages with the exact company + filing source URL qualify."""
    if not source_url:
        return ''
    cached = db.execute('SELECT content FROM filing_pdf_text WHERE ticker=? AND url=?', (ticker, source_url)).fetchone()
    if cached and cached['content']:
        return cached['content']
    rows = db.execute('''SELECT c.content FROM chunks c JOIN documents d ON d.id=c.document_id
        WHERE d.ticker=? AND d.source_url=? AND lower(d.name) LIKE '%.pdf'
        ORDER BY d.id,c.page,c.id LIMIT 150''', (ticker, source_url)).fetchall()
    return '\n'.join(row['content'] for row in rows)[:150000]


def cache_management_pdfs(limit=10):
    """Background collector only. Read official linked BSE PDFs, never bio URLs.

    Failed/blocked/scanned PDFs leave blank fields; retry no more than daily.
    No content is added to the research index.
    """
    from contextlib import closing
    from datetime import timezone, timedelta
    from urllib.parse import urlparse, parse_qs
    import fitz
    import requests
    from .storage import connection
    from .core import classify
    now = datetime.now(timezone.utc)
    with closing(connection()) as db:
        rows = db.execute('''SELECT f.ticker,f.url,f.title,f.excerpt,p.content,p.attempted
            FROM filings f LEFT JOIN filing_pdf_text p ON p.ticker=f.ticker AND p.url=f.url
            WHERE f.source!='synthetic_demo' ORDER BY julianday(f.published) DESC LIMIT 500''').fetchall()
    attempted = 0
    seen = set()
    for row in rows:
        if attempted >= limit:
            break
        if classify(row['title'], row['excerpt'])[0] != 'management_change':
            continue
        key = (row['ticker'],row['url'])
        if key in seen:
            continue
        seen.add(key)
        if row['content']:
            continue
        if row['attempted'] and datetime.fromisoformat(row['attempted']) > now-timedelta(days=1):
            continue
        parsed = urlparse(row['url'])
        if (parsed.scheme != 'https' or parsed.hostname not in {'bseindia.com','www.bseindia.com'}
            or parsed.port not in {None,443} or parsed.username or parsed.password):
            continue
        url = row['url']
        if parsed.path.lower() == '/stockinfo/annpdfopen.aspx':
            name = parse_qs(parsed.query).get('Pname', [''])[0]
            if not re.fullmatch(r'[a-fA-F0-9-]{36}\.pdf', name):
                continue
            url = 'https://www.bseindia.com/xml-data/corpfiling/AttachLive/' + name
        elif not parsed.path.lower().endswith('.pdf'):
            continue
        attempted += 1
        text = ''
        try:
            with requests.get(url,stream=True,timeout=(4,12),allow_redirects=False) as response:
                if response.status_code != 200:
                    raise ValueError('PDF unavailable')
                raw = bytearray()
                for block in response.iter_content(65536):
                    raw.extend(block)
                    if len(raw) > 8*1024*1024:
                        raise ValueError('PDF too large')
            if not raw.startswith(b'%PDF-'):
                raise ValueError('Not a PDF')
            with fitz.open(stream=bytes(raw),filetype='pdf') as pdf:
                # Management notices are short; do not parse unrelated report appendices.
                text = '\n'.join(pdf[i].get_text(sort=True) for i in range(min(len(pdf),12)))[:150000]
        except Exception:
            pass
        with closing(connection()) as db, db:
            db.execute('''INSERT INTO filing_pdf_text(ticker,url,content,attempted) VALUES (?,?,?,?)
                ON CONFLICT(ticker,url) DO UPDATE SET content=excluded.content,attempted=excluded.attempted''',
                (row['ticker'],row['url'],text,now.isoformat()))
    return attempted
