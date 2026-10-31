"""Mocked BSE RSS tests. Never reach the network or mutate FINN's real database."""
from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from xml.sax.saxutils import escape

import pytest

from app import live_bse


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    path = tmp_path / "runtime.sqlite3"
    def connect():
        db = sqlite3.connect(path)
        db.row_factory = sqlite3.Row
        return db
    with closing(connect()) as db:
        db.execute("""CREATE TABLE filings (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          ticker TEXT NOT NULL, published TEXT NOT NULL,
          title TEXT NOT NULL, url TEXT DEFAULT '', category TEXT NOT NULL,
          score INTEGER NOT NULL, source TEXT NOT NULL DEFAULT 'user',
          excerpt TEXT DEFAULT '', UNIQUE(ticker,published,title))""")
        db.commit()
    monkeypatch.setattr(live_bse, "connection", connect)
    portfolio = tmp_path / "portfolio.json"
    portfolio.write_text(json.dumps({"NTPC": "532555"}), encoding="utf-8")
    return connect, portfolio


def feed_xml(items):
    chunks = []
    for code, title, description, url, published in items:
        chunks.append(
            "<item>"
            f"<title>{escape(title)}</title>"
            f"<scripcode>{escape(code)}</scripcode>"
            f"<description>{escape(description)}</description>"
            f"<link>{escape(url)}</link>"
            f"<pubDate>{escape(published)}</pubDate>"
            "</item>"
        )
    return ("<?xml version='1.0' encoding='UTF-8'?>"
            "<rss version='2.0'><channel><title>BSE - Latest Corporate Announcements</title>"
            + "".join(chunks) + "</channel></rss>").encode('utf-8')


class FakeSession:
    def close(self):
        self.closed = True


def inject_feed(monkeypatch, data):
    monkeypatch.setattr(live_bse, 'make_session', lambda: FakeSession())
    monkeypatch.setattr(live_bse, '_fetch_rss', lambda session: (
        data, 'https://www.bseindia.com/data/xml/announcements.xml'))


def test_rss_match_uses_existing_scoring_and_preserves_pdf(isolated, monkeypatch):
    connect, portfolio = isolated
    pdf = 'https://www.bseindia.com/xml-data/corpfiling/AttachLive/example.pdf'
    data = feed_xml([('532555', 'NTPC Ltd (532555)',
                      'Unaudited financial results for quarter ended September 2026',
                      pdf, '01-Nov-2026 01:05:56')])
    inject_feed(monkeypatch, data)
    outcome = live_bse.sync_bse('2026-11-01', '2026-11-01', portfolio_file=portfolio)
    assert outcome['source'] == 'live'
    assert outcome['transport'] == 'rss'
    assert outcome['received'] == 1 and outcome['eligible'] == 1
    assert outcome['added'] == 1 and outcome['grouped_events'] == 1
    assert outcome['derived_pdf_urls'] == 0
    with closing(connect()) as db:
        row = dict(db.execute('SELECT * FROM filings').fetchone())
    assert row['ticker'] == 'NTPC' and row['url'] == pdf
    assert row['category'] == 'results' and row['score'] == 94
    again = live_bse.sync_bse('2026-11-01', '2026-11-01', portfolio_file=portfolio)
    assert again['source'] == 'live' and again['added'] == 0 and again['duplicates'] == 1


def test_rss_nonportfolio_etf_preserves_existing_database(isolated, monkeypatch):
    connect, portfolio = isolated
    with closing(connect()) as db:
        db.execute('INSERT INTO filings(ticker,published,title,url,category,score,source,excerpt)'
                   ' VALUES (?,?,?,?,?,?,?,?)',
                   ('NTPC', '2026-10-31T12:00:00+05:30', 'Older filing',
                    'https://www.bseindia.com/xml-data/corpfiling/AttachLive/old.pdf',
                    'unclassified', 10, 'BSE official RSS snapshot', ''))
        db.commit()
    data = feed_xml([('535276', 'SBI Mutual Fund - SBI Sensex ETF (535276)', '',
                      'https://www.bseindia.com/xml-data/corpfiling/AttachLive/88744a48-59c5-4036-8b34-ff987f05a019.pdf',
                      '01-Nov-2026 01:05:56')])
    inject_feed(monkeypatch, data)
    outcome = live_bse.sync_bse('2026-10-30', '2026-11-01', portfolio_file=portfolio)
    assert outcome['source'] == 'snapshot' and outcome['received'] == 1
    assert outcome['added'] == 0 and outcome['error']
    with closing(connect()) as db:
        assert db.execute('SELECT COUNT(*) FROM filings').fetchone()[0] == 1


def test_rss_bad_url_or_out_of_range_not_imported(isolated, monkeypatch):
    connect, portfolio = isolated
    data = feed_xml([
        ('532555', 'NTPC Ltd (532555)', 'Financial results', 'https://evil.example/a.pdf', '01-Nov-2026 01:05:56'),
        ('532555', 'NTPC Ltd (532555)', 'Financial results',
         'https://www.bseindia.com/xml-data/corpfiling/AttachLive/old.pdf', '01-Oct-2026 01:05:56'),
    ])
    inject_feed(monkeypatch, data)
    outcome = live_bse.sync_bse('2026-11-01', '2026-11-01', portfolio_file=portfolio)
    assert outcome['source'] == 'snapshot' and outcome['added'] == 0
    with closing(connect()) as db:
        assert db.execute('SELECT COUNT(*) FROM filings').fetchone()[0] == 0


def test_rss_request_failure_returns_snapshot_and_keeps_data(isolated, monkeypatch):
    connect, portfolio = isolated
    monkeypatch.setattr(live_bse, 'make_session', lambda: FakeSession())
    def blocked(session):
        raise ValueError('HTTP 403')
    monkeypatch.setattr(live_bse, '_fetch_rss', blocked)
    outcome = live_bse.sync_bse('2026-11-01', '2026-11-01', portfolio_file=portfolio)
    assert outcome['source'] == 'snapshot'
    assert '403' in outcome['error'] and outcome['added'] == 0
    with closing(connect()) as db:
        assert db.execute('SELECT COUNT(*) FROM filings').fetchone()[0] == 0
