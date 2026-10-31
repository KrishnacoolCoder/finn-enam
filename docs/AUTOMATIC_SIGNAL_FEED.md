# Automatic signal feed

The production Docker image enables `FINN_AUTO_ANNOUNCEMENTS=1`. A daemon
scheduler checks every minute whether the 15-minute collection interval is due.
Collection runs outside request handling, with one active collection per process.
The hosted service uses one Uvicorn worker. Server startup and shutdown register
the scheduler; ordinary local/unit-test sessions do not enable it by default.

Sources are BSE's public RSS feed and the recent announcement lists on public
Screener company pages. Collection visits only the fixed 20-company portfolio.
Directory records retain their original BSE PDF links and timezone-aware source
timestamps. The directory source is labeled **BSE filing metadata via Screener**.
Directory notes are secondary metadata, not independently verified PDF contents.
News remains separate and is not used to fill the corporate filing feed.

Each source/company can fail independently. A failed BSE RSS request does not
prevent company-directory checks. Download bounds, timeouts, three concurrent
directory fetches, transactional inserts and attachment identity deduplication
protect the workflow. BSE wrapper and direct attachment URLs with the same UUID
are treated as one filing. Existing records are retained on failures.

The sources are rolling windows, so this does not guarantee exhaustive exchange
coverage. Collection accumulates available records over time. No filing dates or
events are fabricated to fill a selected window. Free-host sleep pauses the
server scheduler; it resumes when the service wakes. The laptop collector runs
the same pipeline every 15 minutes as a backup, and uploads idempotently using
the existing ingestion token.

The normal UI shows automatic status, stored filing/company counts, and a status
check button. Its default window is Last 7 days. Browser status polling refreshes
the feed when new records appear. The header reports the last successful check,
not a guarantee of real-time prices or new announcements. Time filtering uses
SQLite datetime conversion so UTC and Indian-time timestamps compare correctly.
Manual XML imports, synthetic examples and sample imports remain under Advanced.

Endpoints:

- `GET /api/feed/status`: saved source status, total coverage and scheduler state.
- `POST /api/feed/refresh`: starts a due collection and returns immediately;
  respects the 15-minute interval and cannot create parallel collection jobs.

Initial real-data acceptance: 98 stored filings across 20 companies, 93 newly
collected filings, and 61 grouped events in the last seven days at preparation
time. Counts change as source publication times enter/leave the window. 123 tests
passed, including source failure isolation, bad links/dates, duplicate transport
URLs, concurrent imports, scheduler start/stop, and timezone-window behavior.
