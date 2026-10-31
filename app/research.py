"""Document-grounded retrieval, with extractive fallback and optional OpenAI."""
from __future__ import annotations
import io, os,re
from datetime import datetime,timezone
import fitz
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from .storage import connection
from .core import excerpt,extract_guidance

MAX_BYTES=20*1024*1024

def ingest(ticker:str,name:str,data:bytes,kind:str='annual_report',url:str=''):
    if len(data)>MAX_BYTES:raise ValueError('File exceeds the 20 MB limit.')
    pages=[]
    if name.lower().endswith('.pdf'):
        try:
            pdf=fitz.open(stream=data,filetype='pdf')
            if len(pdf)>350:raise ValueError('PDF exceeds the 350-page limit.')
            for i,p in enumerate(pdf):pages.append((i+1,p.get_text(sort=True)))
            pdf.close()
        except ValueError:raise
        except Exception as exc:raise ValueError('Could not read this PDF.') from exc
    elif name.lower().endswith('.txt'):
        try:pages=[(1,data.decode('utf-8-sig'))]
        except UnicodeDecodeError as exc:raise ValueError('Text must be UTF-8.') from exc
    else:raise ValueError('Only PDF and UTF-8 TXT documents are supported.')
    chunks=[]
    for page,text in pages:
        words=text.split()
        for start in range(0,len(words),170):
            block=' '.join(words[start:start+220])
            if len(block)>50:chunks.append((page,block))
    if not chunks:raise ValueError('No selectable text was found. Scanned PDFs need OCR before upload.')
    with connection() as c:
        cur=c.execute('INSERT INTO documents (ticker,name,kind,source_url,added,pages) VALUES (?,?,?,?,?,?)',
            (ticker,name,kind,url,datetime.now(timezone.utc).isoformat(),len(pages)))
        doc_id=cur.lastrowid
        c.executemany('INSERT INTO chunks (document_id,page,content) VALUES (?,?,?)',[(doc_id,p,t) for p,t in chunks])
    return {'document_id':doc_id,'pages':len(pages),'chunks':len(chunks)}

def list_docs(ticker):
    with connection() as c:
        rows=c.execute('SELECT id,ticker,name,kind,source_url,added,pages FROM documents WHERE ticker=? ORDER BY id DESC',(ticker,)).fetchall()
    return [dict(x) for x in rows]

def retrieve(ticker,question,top_k=5):
    with connection() as c:
        rows=c.execute('''SELECT c.id,c.page,c.content,d.id AS doc_id,d.name,d.source_url FROM chunks c JOIN documents d ON d.id=c.document_id WHERE d.ticker=?''',(ticker,)).fetchall()
    if not rows:return []
    texts=[r['content'] for r in rows]
    vectorizer=TfidfVectorizer(stop_words='english',ngram_range=(1,2),max_features=30000)
    try:
        mat=vectorizer.fit_transform(texts+[question]); scores=cosine_similarity(mat[-1],mat[:-1]).ravel()
    except ValueError:return []
    indices=scores.argsort()[::-1][:top_k]
    return [{'chunk_id':rows[int(i)]['id'],'document_id':rows[int(i)]['doc_id'],'document':rows[int(i)]['name'],'page':rows[int(i)]['page'],'source_url':rows[int(i)]['source_url'],'score':round(float(scores[i]),3),'text':rows[int(i)]['content']} for i in indices if scores[i]>0]

def answer(ticker,question):
    results=retrieve(ticker,question)
    if not results:return {'answer':'No relevant source passage found. Upload an annual report or earnings-call transcript for this ticker, or ask a more specific question.','citations':[],'mode':'no_sources'}
    key=os.environ.get('OPENAI_API_KEY','').strip()
    if key:
        try:
            import requests
            context='\n\n'.join(f'[{i+1}] {r["document"]} page {r["page"]}: {r["text"]}' for i,r in enumerate(results))
            prompt='You are FINN, a cautious financial research assistant. ONLY use the provided primary-document excerpts. Cite claims as [1], [2], etc. Do not make up numbers or extrapolate. If the evidence is missing, say so. Distinguish guidance from actual reported results. No investment advice.\n\n'+context+'\n\nQuestion: '+question
            resp=requests.post('https://api.openai.com/v1/chat/completions',headers={'Authorization':'Bearer '+key},json={'model':os.environ.get('OPENAI_MODEL','gpt-4o-mini'),'temperature':0,'messages':[{'role':'user','content':prompt}]},timeout=35)
            resp.raise_for_status()
            content=resp.json()['choices'][0]['message']['content']
            return {'answer':content,'citations':results,'mode':'llm_grounded'}
        except Exception:
            pass
    lines=['Relevant excerpts from primary documents (extractive mode; no generative AI configured):']
    for i,r in enumerate(results[:4],1):lines.append(f'[{i}] {r["document"]}, p. {r["page"]}: {excerpt(r["text"],500)}')
    return {'answer':'\n\n'.join(lines),'citations':results,'mode':'extractive'}

def guidance(ticker):
    with connection() as c:
        rows=c.execute('''SELECT c.page,c.content,d.name FROM chunks c JOIN documents d ON d.id=c.document_id WHERE d.ticker=? AND d.kind='transcript' LIMIT 150''',(ticker,)).fetchall()
    out=[]
    for r in rows:
        for s in extract_guidance(r['content']):
            out.append({**s,'document':r['name'],'page':r['page']})
    return out[:15]
