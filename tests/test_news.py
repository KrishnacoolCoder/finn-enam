import ast
from contextlib import closing
import inspect
import sqlite3
from datetime import datetime, timezone

import pytest
import requests
from fastapi.testclient import TestClient

from app import news, research, storage
from app.main import app


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, 'DB', tmp_path / 'news.sqlite3')
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    monkeypatch.setenv('INGEST_TOKEN', 'news-test')
    storage.init()
    return tmp_path


def item(**changes):
    row = dict(ticker='NTPC', title='NTPC earnings rise after strong power demand',
               source='Example Publisher', published=datetime.now(timezone.utc),
               link='https://example.com/headline')
    row.update(changes)
    return news.NewsItem(**row)


def rss():
    return b'''<rss version="2.0"><channel><title>Google News</title><item>
      <title>NTPC earnings rise - Example Publisher</title>
      <source url="https://example.com">Example Publisher</source>
      <pubDate>Sun, 01 Nov 2026 01:00:00 GMT</pubDate>
      <link>https://news.google.com/rss/articles/example</link>
      <description>ARTICLE_BODY_MUST_NOT_BE_STORED</description>
      </item></channel></rss>'''


class Response:
    def __init__(self, raw): self.raw = raw
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def raise_for_status(self): pass
    def iter_content(self, size): yield self.raw


def test_rss_metadata_only_and_query(isolated):
    class Session:
        def get(self, url, **kwargs):
            assert url == news.RSS_URL
            assert kwargs['params'] == {'q': 'NTPC NSE', 'hl': 'en-IN', 'gl': 'IN', 'ceid': 'IN:en'}
            assert kwargs['timeout'] == (4, 8)
            return Response(rss())
    rows = news.fetch_company('NTPC', 'NTPC', Session())
    assert len(rows) == 1 and rows[0].title == 'NTPC earnings rise'
    news.store_news(rows)
    with closing(storage.connection()) as db:
        assert {r[1] for r in db.execute('PRAGMA table_info(news)')} == {
            'id', 'ticker', 'title', 'source', 'published', 'link'}
        saved = str(tuple(db.execute('SELECT * FROM news').fetchone()))
        assert 'ARTICLE_BODY' not in saved
        assert db.execute('SELECT COUNT(*) FROM chunks').fetchone()[0] == 0
        assert db.execute('SELECT COUNT(*) FROM filings').fetchone()[0] == 0


def test_near_duplicates_persist_across_batches_and_companies(isolated):
    assert news.store_news([item()])['added'] == 1
    near = item(title='NTPC earnings rise after stronger power demand!', link='https://another.com/repost')
    assert news.store_news([near])['duplicates'] == 1
    assert news.store_news([item(ticker='LT')])['added'] == 1
    assert news.store_news([item(title='A changed headline')])['duplicates'] == 1
    assert not news.same_headline('NTPC profit rises 10 percent', 'NTPC profit rises 20 percent')


def test_company_failure_does_not_stop_other_companies(isolated):
    class Session:
        def get(self, url, **kwargs):
            if kwargs['params']['q'].startswith('NTPC'):
                raise requests.Timeout('temporary failure')
            return Response(rss())
    result = news.sync_news(portfolio=[('NTPC','NTPC','Power'),('LT','Larsen & Toubro','Industrials')],
                            session=Session())
    assert result['added'] == 1
    assert result['errors'] == [{'ticker': 'NTPC', 'error': 'Timeout'}]


@pytest.mark.parametrize('raw', [b'<html>Access denied</html>', b'x' * (news.MAX_FEED_BYTES + 1)])
def test_invalid_or_large_feed_is_nonfatal(isolated, raw):
    class Session:
        def get(self, *args, **kwargs): return Response(raw)
    result = news.sync_news(portfolio=[('NTPC', 'NTPC', 'Power')], session=Session())
    assert result['added'] == 0 and len(result['errors']) == 1


def test_news_api_auth_dedupe_and_no_article_fields(isolated):
    row = item().model_dump(mode='json')
    with TestClient(app) as client:
        assert client.post('/api/ingest/news', json=[row]).status_code == 403
        auth = {'X-Ingest-Token': 'news-test'}
        assert client.post('/api/ingest/news', json=[row], headers=auth).json()['added'] == 1
        assert client.post('/api/ingest/news', json=[row], headers=auth).json()['duplicates'] == 1
        assert client.post('/api/ingest/news', json=[dict(row, article='forbidden')], headers=auth).status_code == 422
        assert client.post('/api/ingest/news', json=[dict(row, link='javascript:alert(1)')], headers=auth).status_code == 422
        rows = client.get('/api/news?ticker=NTPC').json()
        assert len(rows) == 1 and set(rows[0]) == {'ticker','title','source','published','link'}
        assert client.get('/api/news?ticker=LT').json() == []


def test_research_never_imports_or_queries_news(isolated, monkeypatch):
    tree = ast.parse(inspect.getsource(research))
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import): imports.extend(n.name for n in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.append(node.module or '')
            imports.extend(n.name for n in node.names)
    assert not any(name.split('.')[-1] in {'news', 'feedparser'} for name in imports)
    sentinel = 'UNTRUSTED_NEWS_SENTINEL cash flow claims 99999 crore'
    news.store_news([item(title=sentinel)])
    queries = []
    def guarded_connection():
        db = storage.connection()
        def authorize(action, table, column, database, trigger):
            if action == sqlite3.SQLITE_READ:
                queries.append(table)
                if table == 'news': return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK
        db.set_authorizer(authorize)
        return db
    monkeypatch.setattr(research, 'connection', guarded_connection)
    assert research.answer('NTPC', 'cash flow')['mode'] == 'no_sources'
    doc = b'Our annual report states operating cash flow was 190 crore. Management expects steady growth in revenue next year.'
    research.ingest('NTPC', 'primary.txt', doc, 'transcript')
    assert research.list_docs('NTPC')
    assert research.retrieve('NTPC', 'cash flow')
    assert sentinel not in str(research.answer('NTPC', 'cash flow'))
    research.guidance('NTPC')
    assert 'news' not in queries
    assert {'documents', 'chunks'} <= set(queries)


def test_news_upload_failure_does_not_break_collector(isolated, monkeypatch):
    import collector
    from app import live_bse
    news.store_news([item()])
    monkeypatch.setattr(live_bse, 'sync_bse', lambda *args: {'source': 'snapshot'})
    monkeypatch.setattr(news, 'sync_news', lambda: {'errors': []})
    class Session:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def post(self, url, **kwargs):
            if url.endswith('/news'):
                assert set(kwargs['json'][0]) == {'ticker','title','source','published','link'}
                raise requests.Timeout()
            return type('Reply', (), {'status_code': 200, 'json': lambda self: {'added':0,'duplicates':0}})()
    monkeypatch.setattr(collector.requests, 'Session', Session)
    result = collector.run_once('https://example.com/api/ingest', 'news-test', seed=isolated/'seed.sqlite3')
    assert result['news']['errors'] == [{'upload_error': 'Timeout'}]
    with closing(sqlite3.connect(isolated/'seed.sqlite3')) as db:
        assert db.execute('SELECT COUNT(*) FROM news').fetchone()[0] == 1
