"""Best-effort BSE corporate announcement synchronization for FINN.

Uses the public website JSON endpoint, not an authenticated/licensed feed.
All results are checked before a database transaction begins. Access denial,
empty windows, malformed payloads and incomplete pagination leave the existing
filings unchanged. No browser automation or challenge bypass is attempted.

CLI:
    python -m app.live_bse --days 3  # BSE RSS (default)
    python -m app.live_bse --days 3 --source json  # legacy API diagnostics
"""
from __future__ import annotations

import argparse
import html
import json
import re
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .core import PORTFOLIO, assess_filing, classify, excerpt
from .bse_import import MAX_XML_BYTES, parse_feed
from .grouping import group_filings
from .storage import connection

IST = timezone(timedelta(hours=5, minutes=30))
ROOT = Path(__file__).resolve().parents[1]
PORTFOLIO_FILE = ROOT / "data" / "portfolio.json"
BSE_API = "https://api.bseindia.com/BseIndiaAPI/api/AnnGetData/w"
# Published BSE RSS addresses; reachable independently of the legacy JSON API
# in some environments. We do not circumvent HTTP 403 or access controls.
BSE_RSS_URLS = (
    "https://www.bseindia.com/data/xml/announcements.xml",
    "https://www.bseindia.com/data/xml/announcements.aspx",
)
PDF_ROOT = "https://www.bseindia.com/xml-data/corpfiling/AttachLive/"
MAX_PAGES_PER_SCRIP = 5
PAGE_SIZE = 50  # BSE's historically observed page size; use ROWCNT if supplied.
SOURCE_NAME = "BSE live website JSON"


def make_session() -> requests.Session:
    """A bounded, polite GET client; never retry access-denied 401/403 responses."""
    session = requests.Session()
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-IN,en;q=0.9",
        "Referer": "https://www.bseindia.com/",
        "Origin": "https://www.bseindia.com",
    })
    retry = Retry(
        total=2,
        connect=2,
        read=2,
        status=2,
        backoff_factor=0.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(("GET",)),
        respect_retry_after_header=True,
        raise_on_status=False,
    )
    session.mount("https://", HTTPAdapter(max_retries=retry))
    return session


def load_portfolio(path: Path = PORTFOLIO_FILE) -> dict[str, str]:
    """Return only explicitly configured equity scrip codes for FINN tickers.

    Blank codes are allowed while the user verifies them on the BSE website.
    """
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("portfolio.json must be an object: NSE ticker -> BSE scrip code")
    expected = {ticker for ticker, _, _ in PORTFOLIO}
    unknown = sorted(set(raw) - expected)
    if unknown:
        raise ValueError("Unknown NSE ticker(s) in portfolio.json: " + ", ".join(unknown))
    output: dict[str, str] = {}
    for ticker, value in raw.items():
        code = str(value).strip() if value is not None else ""
        if not code:
            continue
        if not re.fullmatch(r"\d{6}", code):
            raise ValueError(f"Invalid six-digit BSE equity scrip code for {ticker}")
        if code in output.values():
            raise ValueError(f"Duplicated BSE scrip code {code}")
        output[ticker] = code
    return output


def _date(value: date | str) -> date:
    if isinstance(value, datetime):
        return value.astimezone(IST).date() if value.tzinfo else value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _published(value: object) -> datetime | None:
    if value is None or value == "":
        return None
    text = str(value).strip()
    try:
        result = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return result.astimezone(IST) if result.tzinfo else result.replace(tzinfo=IST)
    except ValueError:
        pass
    for fmt in (
        "%d-%b-%Y %H:%M:%S", "%d-%b-%Y %H:%M",
        "%d-%m-%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S",
        "%d/%m/%Y %H:%M:%S",
    ):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=IST)
        except ValueError:
            continue
    return None


def _clean(value: object) -> str:
    """Avoid storing HTML fragments and excessively long external text."""
    value = html.unescape(str(value or ""))
    value = re.sub(r"<[^>]*>", " ", value)
    return " ".join(value.split())[:2000]


def _pdf_url(row: dict) -> tuple[str, bool]:
    """Return (official URL, derived-from-attachment-name).

    Direct official PDF links are preserved unchanged. When BSE returns only
    ATTACHMENTNAME, use its documented AttachLive path (not independently checked).
    """
    for key in ("PDF_LINK", "PDFURL", "attachment_url", "ATTACHMENT_URL", "PDF_URL", "URL"):
        raw = str(row.get(key) or "").strip()
        if not raw:
            continue
        if raw.startswith("/xml-data/"):
            raw = "https://www.bseindia.com" + raw
        parsed = urlparse(raw)
        if (parsed.scheme == "https" and parsed.hostname in {"www.bseindia.com", "bseindia.com"}
                and parsed.path.lower().startswith("/xml-data/") and parsed.path.lower().endswith(".pdf")):
            return raw, False
    attachment = str(row.get("ATTACHMENTNAME") or "").strip()
    if re.fullmatch(r"[A-Za-z0-9_-]+\.pdf", attachment, re.IGNORECASE):
        return PDF_ROOT + attachment, True
    return "", False


def _convert(row: dict, ticker: str, expected_code: str, first: date, last: date) -> dict | None:
    """Map a single BSE response row to FINN's existing filings schema."""
    if not isinstance(row, dict):
        return None
    code = str(row.get("SCRIP_CD") or row.get("SCRIPCODE") or row.get("scripcode") or "").strip()
    if code != expected_code:  # Never guess company identity from a broad response.
        return None
    published = _published(row.get("DissemDT") or row.get("NEWS_DT") or
                           row.get("News_submission_dt") or row.get("DT_TM"))
    if published is None or not (first <= published.date() <= last):
        return None
    title = _clean(row.get("NEWSSUB") or row.get("HEADLINE") or row.get("SUBJECT"))[:500]
    if not title:
        return None
    body = _clean(" ".join(str(row.get(k) or "") for k in
                           ("HEADLINE", "MORE", "CATEGORYNAME", "SUBCATNAME")))
    url, derived_url = _pdf_url(row)
    if not url:  # Don't create unsupported supposedly source-linked announcements.
        return None
    category, score = classify(title, body)
    return {
        "ticker": ticker,
        "published": published.isoformat(),
        "title": title,
        "url": url,
        "category": category,
        "score": score,
        "source": SOURCE_NAME,
        "excerpt": excerpt(body),
        "derived_url": derived_url,
    }


def _count(payload: dict) -> int | None:
    table = payload.get("Table1")
    if isinstance(table, list) and table and isinstance(table[0], dict):
        try:
            n = int(table[0].get("ROWCNT"))
            if n >= 0:
                return n
        except (ValueError, TypeError):
            pass
    return None


def _fetch_for_scrip(session: requests.Session, code: str, first: date, last: date,
                     max_pages: int = MAX_PAGES_PER_SCRIP) -> list[dict]:
    records: list[dict] = []
    for page in range(1, max_pages + 1):
        response = session.get(BSE_API, params={
            "pageno": page,
            "strCat": "-1",
            "strPrevDate": first.strftime("%Y%m%d"),
            "strScrip": code,
            "strSearch": "P",
            "strToDate": last.strftime("%Y%m%d"),
            "strType": "C",
        }, timeout=(5, 15))
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict) or not isinstance(payload.get("Table"), list):
            raise ValueError("BSE returned unexpected JSON (missing Table list)")
        rows = payload["Table"]
        records.extend(rows)
        total = _count(payload)
        if not rows or (total is not None and len(records) >= total):
            return records
        if total is None and len(rows) < PAGE_SIZE:
            return records
    # Never commit a silently truncated set of announcements.
    raise ValueError(f"BSE pagination limit reached for scrip {code}; no changes saved")


def _fetch_rss(session: requests.Session) -> tuple[bytes, str]:
    """Try publicly advertised BSE RSS feeds; never bypass access restrictions.

    A successful response must be parseable by FINN's existing BSE RSS parser.
    Network errors, 403, HTML login pages and invalid XML are all treated as
    failures. No DB changes are made during fetching.
    """
    failures: list[str] = []
    for url in BSE_RSS_URLS:
        try:
            with session.get(
                url,
                timeout=(5, 15),
                stream=True,
                headers={
                    # Match the simple successful RSS probe. The JSON API
                    # uses separate request defaults on the same session.
                    "Accept": "application/rss+xml, application/xml, text/xml, */*",
                    "Origin": None,
                    "Referer": None,
                },
            ) as response:
                response.raise_for_status()
                size = 0
                pieces: list[bytes] = []
                for piece in response.iter_content(chunk_size=65536):
                    if not piece:
                        continue
                    size += len(piece)
                    if size > MAX_XML_BYTES:
                        raise ValueError("BSE RSS feed exceeds safety limit")
                    pieces.append(piece)
                raw = b"".join(pieces)
                parse_feed(raw)  # Reuse the vetted RSS/XML parser, including DTD checks.
                return raw, url
        except (requests.RequestException, ValueError, OSError) as exc:
            failures.append(f"{url.rsplit('/', 1)[-1]}: {type(exc).__name__}: {str(exc)[:100]}")
    raise ValueError("BSE RSS unavailable (" + "; ".join(failures) + ")")


def _rss_candidates(feed: bytes, codes: dict[str, str],
                    first: date, last: date) -> tuple[int, list[dict]]:
    """Convert official RSS rows to the existing FINN filings schema.

    Only retain verified ticker/code pairs, correct dates and HTTPS BSE PDF
    addresses. Never invent source documents or announcements.
    """
    rows = parse_feed(feed)
    reverse_codes = {code: ticker for ticker, code in codes.items()}
    candidates = []
    for row in rows:
        ticker = reverse_codes.get(row["code"])
        if ticker is None:
            continue
        try:
            published = datetime.fromisoformat(row["published"])
        except (ValueError, TypeError):
            continue
        if not first <= published.date() <= last:
            continue
        raw_url = row["url"]
        parsed = urlparse(raw_url)
        if not (parsed.scheme == "https"
                and parsed.hostname in ("www.bseindia.com", "bseindia.com")
                and parsed.path.lower().startswith("/xml-data/")
                and parsed.path.lower().endswith(".pdf")):
            continue
        desc = _clean(row["description"])
        title = (desc[:170] or _clean(row["name"]))[:500]
        if not title:
            continue
        category, score = classify(title, desc)
        candidates.append({
            "ticker": ticker, "published": published.isoformat(),
            "title": title, "url": raw_url, "category": category,
            "score": score, "source": "BSE official live RSS",
            "excerpt": excerpt(desc), "derived_url": False,
        })
    return len(rows), candidates


def sync_bse(from_date: date | str, to_date: date | str, *,
             portfolio_file: Path = PORTFOLIO_FILE,
             session: requests.Session | None = None,
             max_pages: int = MAX_PAGES_PER_SCRIP,
             transport: str = "rss") -> dict:
    """Atomically import valid BSE rows; preserve the DB on any fetch failure.

    Returns metadata with source='live' only when at least one valid current
    filing was retrieved. source='snapshot' means existing DB should be used.
    """
    fetched_at = datetime.now(timezone.utc).isoformat()
    status = {
        "source": "snapshot", "fetched_at": fetched_at, "error": None,
        "from_date": str(from_date), "to_date": str(to_date),
        "received": 0, "eligible": 0, "added": 0,
        "duplicates": 0, "grouped_events": 0, "derived_pdf_urls": 0,
        "note": "Existing database rows are preserved if live retrieval fails.",
        "transport": transport, "endpoint": None,
    }
    own_session = session is None
    try:
        first, last = _date(from_date), _date(to_date)
        if first > last:
            raise ValueError("from_date must not be after to_date")
        status["from_date"], status["to_date"] = first.isoformat(), last.isoformat()
        if transport not in ("rss", "json"):
            raise ValueError("transport must be rss or json")
        codes = load_portfolio(portfolio_file)
        if not codes:
            raise ValueError("No BSE scrip codes configured in data/portfolio.json")
        active = session if session is not None else make_session()
        candidates: list[dict] = []
        # Keep injected fake sessions on the original JSON path so existing
        # mocked tests remain unchanged; default real usage is RSS-first.
        if transport == "rss" and session is None:
            feed, url = _fetch_rss(active)
            status["endpoint"] = url
            status["received"], candidates = _rss_candidates(feed, codes, first, last)
            if not candidates:
                raise ValueError(
                    "BSE RSS responded, but contained no source-linked portfolio "
                    "filings in the selected date range (not proof of zero "
                    "announcements; RSS has a rolling retention window)"
                )
        else:
            status["transport"] = "json"
            status["endpoint"] = BSE_API
            for ticker, code in codes.items():
                rows = _fetch_for_scrip(active, code, first, last, max_pages)
                status["received"] += len(rows)
                candidates.extend(item for row in rows
                                  if (item := _convert(row, ticker, code, first, last)) is not None)
            if not candidates:
                raise ValueError("No valid portfolio filings returned by BSE in this date window")

        status["eligible"] = len(candidates)
        status["derived_pdf_urls"] = sum(item["derived_url"] for item in candidates)
        grouped_rows: list[dict] = []
        with closing(connection()) as db:
            with db:  # one transaction; idempotence across snapshot and live sources
                for filing in candidates:
                    old = db.execute(
                        "SELECT * FROM filings WHERE ticker=? AND url=? LIMIT 1",
                        (filing["ticker"], filing["url"]),
                    ).fetchone()
                    if old is not None:
                        status["duplicates"] += 1
                        item = dict(old)
                    else:
                        cursor = db.execute(
                            "INSERT OR IGNORE INTO filings "
                            "(ticker,published,title,url,category,score,source,excerpt) "
                            "VALUES (?,?,?,?,?,?,?,?)",
                            tuple(filing[k] for k in
                                  ("ticker", "published", "title", "url", "category", "score", "source", "excerpt")),
                        )
                        if cursor.rowcount:
                            status["added"] += 1
                        else:
                            status["duplicates"] += 1
                        found = db.execute(
                            "SELECT * FROM filings WHERE ticker=? AND url=? LIMIT 1",
                            (filing["ticker"], filing["url"]),
                        ).fetchone()
                        if found is None:
                            found = db.execute(
                                "SELECT * FROM filings WHERE ticker=? AND published=? AND title=? LIMIT 1",
                                (filing["ticker"], filing["published"], filing["title"]),
                            ).fetchone()
                        item = dict(found) if found is not None else None
                    if item is not None:
                        assessed = assess_filing(item["title"], item.get("excerpt") or "")
                        item["priority_reason"] = assessed["reason"]
                        grouped_rows.append(item)
        # Use FINN's existing presentation-only grouping function.
        status["grouped_events"] = len(group_filings(grouped_rows))
        status["source"] = "live"
        if status["transport"] == "rss":
            status["note"] = (
                "Live BSE RSS successfully fetched and matched; this is a rolling "
                "feed and may not contain the entire requested date range. "
                "Linked PDFs were not independently downloaded or inspected."
            )
        else:
            status["note"] = (
                "BSE website JSON response processed; PDFs not independently "
                "fetched or verified. Derived attachment URLs may require review."
            )
        return status
    except (requests.RequestException, ValueError, OSError, json.JSONDecodeError) as exc:
        status["error"] = f"{type(exc).__name__}: {str(exc)[:240]}"
        return status
    finally:
        if own_session and 'active' in locals():
            active.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sync source-linked BSE announcements into FINN")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--days", type=int, default=None, help="Calendar days including today (default 3)")
    group.add_argument("--from", dest="from_date", help="Start date YYYY-MM-DD (requires --to)")
    parser.add_argument("--to", dest="to_date", help="End date YYYY-MM-DD")
    parser.add_argument("--source", choices=("rss", "json"), default="rss",
                        help="rss (default) or legacy JSON for diagnosis")
    parser.add_argument("--portfolio", type=Path, default=PORTFOLIO_FILE)
    args = parser.parse_args(argv)
    if args.from_date is not None:
        if args.to_date is None:
            parser.error("--from requires --to")
        first, last = args.from_date, args.to_date
    else:
        if args.to_date is not None:
            parser.error("--to requires --from")
        days = 3 if args.days is None else args.days
        if not 1 <= days <= 31:
            parser.error("--days must be between 1 and 31")
        today = datetime.now(IST).date()
        first, last = today - timedelta(days=days - 1), today
    result = sync_bse(first, last, portfolio_file=args.portfolio,
                      transport=args.source)
    print(json.dumps(result, indent=2))
    # A network failure is a graceful application fallback, not a Python crash.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
