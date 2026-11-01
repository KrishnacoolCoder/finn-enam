# FINN - Financial Investment Agent

A mobile-first Indian-equity intelligence and primary-source research prototype
for the ENAM AI Engineer Build Challenge.

- [Live demo](https://finn-enam.onrender.com)
- [GitHub repository](https://github.com/KrishnacoolCoder/finn-enam)
- [Deployment health](https://finn-enam.onrender.com/health)
- [API reference](https://finn-enam.onrender.com/docs)

## Verified scope

Checked on **1 November 2026**: the deployed app was healthy, with **98 filings
across 20 companies** and primary-report coverage for all 20 watchlist companies.
The public seed contains 20 indexed reports spanning 1,194 PDF pages. These are
dated observations, not guarantees of complete or continuously live coverage.

The 20-company watchlist is illustrative, not ENAM's actual holdings. Its pinned
catalogue contains annual reports **or** earnings-call transcripts; it is not a
complete or guaranteed latest-report library for every company.

| Workflow | Implemented |
|---|---|
| Push | Source-linked disclosures, deterministic classification/priority, deduplication, related-event grouping, collapsed routine notices and Markdown investor briefs |
| EOD alerts | Price-change and volume-multiple rules using yfinance, recorded triggers, saved thresholds and event preferences |
| Management changes | Regex/keyword extraction of person, role, action and effective date from headlines and available filing PDF text; unknown fields blank; no biographies |
| Pull | Primary PDF/TXT indexing, page-aware chunks, TF-IDF retrieval and file/page-cited evidence selected by a model or extractive fallback |
| Financial review | Candidate revenue/EBITDA/PBT/PAT extraction, source-linked quarterly records, QoQ/YoY arithmetic and sourced guidance comparisons |
| Context | Separately labelled Google News headlines and Screener financial snapshots; neither enters research |
| Mobile | Five bottom tabs, 24h/3d/7d digest picker, source cards, skeletons/retry states and a persistent Alerts screen |

## ASCII architecture

```text
                  DISCLOSURE COLLECTION
 BSE RSS + public company announcement directories
              |                         |
              v                         v
  LAPTOP: collector.py         DEPLOYED: automatic_feed.py
  local SQLite + loop         15-min checks while awake
              |                         |
  HTTPS POST /api/ingest                 |
  X-Ingest-Token                        |
              +------------+------------+
                           v
                   FASTAPI + SQLITE
              dedupe -> rules -> grouping
                           |
                    Feed / brief / alerts

 Pinned primary PDFs + user PDF/TXT uploads
                           |
                PDF blocks -> page chunks
                           |
              SQLite documents/chunks tables
                           |
             TF-IDF -> numbered source sentences
                           |
              Gemini -> Groq -> extractive
                           |
        validated IDs -> source text + [file, page]
                           |
                        Research UI

 Google News RSS -> laptop -> /api/ingest/news -> news table
                                                     |
                                             Market context UI
                                          (NO path to research)
 yfinance -> EOD rules -> recorded market alerts
 Screener financial snapshot -> separate context cache -> UI only

                    SNAPSHOT / RESTART PATH
 Laptop SQLite -> export seed/finn.sqlite3 -> reviewed Git commit
                                               |
                                               v
                          app.deploy restores seed ONLY if
                          the runtime database is missing
```

Classification does not call an LLM per announcement. Rules and deterministic
arithmetic handle common operations cheaply and explainably; models are reserved
for selecting relevant primary-source research evidence.

## Local setup

Docker uses Python 3.11; the laptop build was also tested on Python 3.13.9.
Run from the repository root.

### Windows PowerShell

```powershell
git clone https://github.com/KrishnacoolCoder/finn-enam.git
cd finn-enam
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn app.deploy:app --reload
```

### Linux / macOS

```bash
git clone https://github.com/KrishnacoolCoder/finn-enam.git
cd finn-enam
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m uvicorn app.deploy:app --reload
```

Open [localhost:8000](http://127.0.0.1:8000) and
[localhost:8000/docs](http://127.0.0.1:8000/docs). The direct interpreter commands
do not require activating the environment or changing PowerShell policy.

Use **`app.deploy:app`** for the seeded demo: it restores the seed before SQLite
initialization. `app.main:app` alone initializes the schema without that restore.
Existing runtime databases are preserved; do not delete one merely to update code.

`.env.example` lists variable names, but dotenv files are **not automatically
loaded**. Configure the process environment or the host's Environment page.

## Environment variables

| Variable | Purpose / default |
|---|---|
| `FINN_DATA_DIR` | Directory containing runtime `finn.sqlite3`; local default `data/`. Set before process startup. |
| `INGEST_TOKEN` | Long random shared secret for laptop filing/news uploads. Must match on collector and server. Without server configuration, ingestion is disabled. |
| `FINN_AUTO_ANNOUNCEMENTS` | `1` enables the server announcement scheduler. Docker enables it; ordinary local runs default to off. |
| `GEMINI_API_KEY` | Optional SDK key for the configured `gemini-2.5-flash` model. |
| `GROQ_API_KEY` | Optional backup, or the sole configured research provider. |
| `GROQ_MODEL` | Default `openai/gpt-oss-120b`. The previous free-tier Llama default is migrated to this replacement. |
| `FINN_AUTO_POLL_MINUTES` | Separate EOD market watcher: `0` disables it; values of at least 30 enable it. |
| `FINN_BSE_SYNC_KEY` | Optional secret for administrative `/api/bse/live-sync`; separate from the collector token. |

Create keys in [Google AI Studio](https://aistudio.google.com/) or
[Groq Console](https://console.groq.com/keys); keep them server-side. At the last
live check, the configured Gemini request returned HTTP 404 and **Groq-backed
cited answers were verified working**. Gemini is not claimed as a working live
dependency. Missing/failed providers fall back to extractive evidence or
`insufficient evidence`; account access and free-tier quotas still apply.

## Laptop collector -> deployed app

Hosting IPs can be blocked by exchanges, and RSS has limited retention. The
laptop provides another collection location, not guaranteed exchange access.
Set the same `INGEST_TOKEN` locally and on the deployed service:

```powershell
$env:INGEST_TOKEN = 'replace-with-the-same-long-random-server-secret'
# One cycle:
.\.venv\Scripts\python.exe collector.py https://finn-enam.onrender.com
# Or a 15-minute wait between completed cycles:
.\.venv\Scripts\python.exe collector.py https://finn-enam.onrender.com --loop 15 --days 30
```

Each cycle:

1. Attempts BSE RSS and recent company-announcement directories for the fixed
   portfolio. Directory records retain original BSE PDF URLs and publication
   times, but are labelled secondary metadata rather than PDF-verified content.
2. Deduplicates/stores filings locally and attempts bounded management-PDF text
   enrichment. Failures preserve prior data.
3. Collects Google News RSS title, publisher, timestamp and link in the separate
   news table; it does not download article bodies.
4. Exports the local SQLite DB to `seed/finn.sqlite3` **before** upload.
5. Replays non-demo, source-linked local filings in batches to `/api/ingest`
   using `X-Ingest-Token`. The server reclassifies/deduplicates them, including
   equivalent BSE attachment URLs. News uses protected `/api/ingest/news`.

The laptop must stay awake, connected and running the collector. The script does
not install OS autostart or commit/push automatically. Failed uploads leave local
data and the exported seed available for replay.

### Publishing a refreshed seed

Review the exported data, then:

```powershell
git add seed/finn.sqlite3
git commit -m "Refresh public FINN seed"
git push origin main
```

The collector exports the **whole local database**, not a sanitized subset. It
can contain document text, questions/answers, settings and financial records.
Review before publishing; use a dedicated public-source collector database if
also handling private documents. Original uploaded PDF binaries are not retained
as a document archive: keep the originals for re-indexing.

The older `scripts/make_seed.py` produces a reduced filing-only seed and removes
research/financial data; it is not equivalent to the collector's full export.

## Snapshot fallback and freshness

- Failed or empty retrieval does not erase stored filings or fabricate new ones.
  Original publication times remain unchanged.
- An old snapshot can correctly produce no events in a recent window. Widen the
  window for historical demonstrations instead of changing dates to fill it.
- Docker enables approximately 15-minute announcement checks while the process
  is awake. Host sleep pauses these checks; laptop collection is independent.
- **Checked X min ago** describes collection status, not intraday prices, a new
  filing's arrival, or complete exchange coverage. Successful directory access
  does not prove the exchange returned every disclosure.
- `app.deploy` copies the committed seed only when the runtime DB is missing.
  It never intentionally overwrites an existing DB. A new seed is a bootstrap,
  not an import mechanism for a running persistent database.

## Research and numerical safeguards

The primary-report catalogue pins URLs and SHA-256 hashes. Selecting a portfolio
company ensures its catalogued report is indexed. Other syntactically valid NSE
tickers need an uploaded primary PDF/TXT; syntax validation does not establish
that a symbol is currently listed.

PDF paragraph blocks reduce column interleaving. Roughly 800 word/punctuation
token chunks stay within PDF pages. TF-IDF and topic filters retrieve evidence,
reducing irrelevant overview/audit passages. Citations use one-based **PDF page
indices**, which can differ from printed page numbers.

Models return numbered source/passage IDs. The server resolves them to original
text, validates the evidence and inserts up to four short `[file, page]` bullets.
It does not display unrestricted generated prose. This sacrifices fluent
synthesis for auditability; absent evidence produces abstention. Bounded 429
retries and Gemini -> Groq -> extractive fallback preserve usability. Diagnostics
expose safe failure classes, not keys or raw provider error bodies.

SQLite caches answers by ticker, normalized question and corpus hash, with model,
policy and configuration changes invalidating stale entries. Temporary failures
and secondary-provider answers after a primary failure expire to allow recovery.

Financial extraction proposes cells, not audited figures. Real quarterly saves
require HTTPS source URLs; period, units, basis, page and user-verification status
remain explicit. QoQ/YoY avoids misleading zero/negative-base percentages and
labels loss/profit transitions. Guidance comparisons use sourced statements and
quotes against comparable stored actuals. Unverified figures stay labelled;
arithmetic is not independent verification. The NTPC seed remains unverified,
and derived EBITDA is identified as derived.

## Deployment

### Render - current demo

1. Create a Docker web service from the repository's `main` branch and root
   `Dockerfile`.
2. The image runs `uvicorn app.deploy:app --host 0.0.0.0 --port 7860 --workers 1`.
   Configure service access to port 7860 and health check `/health`. Keep one
   worker with the current in-process schedulers and SQLite.
3. Configure environment/secrets. The current ephemeral demo uses
   `FINN_DATA_DIR=/tmp/finn-data`; Docker defaults to `/home/user/app/data`.
4. Set `INGEST_TOKEN` for laptop uploads and a provider key if wanted. Docker
   enables announcement polling; EOD polling defaults to disabled.
5. After deployment, verify `/health`, `/api/feed/status`,
   `/api/reports/coverage`, source labels and an actual cited research response.
   Successful startup does not establish external provider/exchange availability.

Render's default filesystem is ephemeral. For lasting runtime data, use a
persistent disk on an eligible paid service and set `FINN_DATA_DIR` under its
writable mount, or move to managed storage. See
[Render's disk documentation](https://render.com/docs/disks).

### Docker locally

```bash
docker build -t finn .
docker volume create finn-data
docker run --rm -p 7860:7860 -v finn-data:/home/user/app/data finn
```

Open [localhost:7860](http://127.0.0.1:7860). Supply optional secrets through
environment/secret configuration, not committed files or image layers.

## Honest limitations and omissions

- **Collection:** blocking, rolling retention, directory changes and host sleep
  prevent guaranteed exhaustive/uninterrupted coverage. Snapshots preserve
  availability, not freshness.
- **Market scope:** yfinance provides optional EOD data, not a licensed intraday
  terminal. There is no order execution, holdings accounting or return tracking.
- **Research relevance:** TF-IDF can miss evidence. A valid citation alone does
  not prove that an excerpt answers the question or concerns the intended
  parent/subsidiary, period or basis. No measured retrieval-quality benchmark is
  claimed; inspect source context.
- **PDF accuracy:** block order is not a universal layout parser. Scanned PDFs
  need OCR outside this build. Financial extraction, management regex fields and
  guidance coverage can be incomplete; missing fields stay blank. Biographical
  enrichment and unattended figure verification are intentionally absent.
- **Secondary context:** news search matches are not independently verified
  company attribution. News/Screener snapshots do not enter research or verify
  financial figures; directory metadata aids discovery but is not PDF evidence.
- **Security:** no general authentication, tenant isolation or production abuse
  controls. The ingestion token protects collector endpoints only. Settings are
  shared by the workspace. Use public documents: configured providers receive
  selected excerpts. Production requires access controls and a data policy.
- **Durability:** the seed restores a baseline, not intervening server writes.
  The laptop exports its own DB, not the deployed DB; server-only uploads,
  research/financial edits and alerts are not automatically backed up to it. A
  browser can restore its saved alert preferences after a seed reset, but not
  erased documents or settings for every device. Durable storage is still needed.
- **Delivery and scale:** alerts are in-app/EOD, not mobile OS push or intraday
  streaming. There is no distributed scheduler/queue, multi-instance deployment
  design, production monitoring SLA or automatic deployment-backup policy.

## Tests and reviewer walkthrough

The latest code passed **177 pytest tests**. Provider calls are mocked in tests;
this is not a claim of exhaustive live-model accuracy. Separate live checks
verified healthy deployment, source/coverage status and Groq-backed citations.
Mobile Chromium emulation passed 360/390/430px checks for no overflow, 44px targets,
priority/routine behavior, loading/retry, stale-response guards, settings reload
and simulated reset recovery. Physical-phone Safari/Android keyboard and safe-area
checks remain manual follow-ups.

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m compileall -q app
```

1. **Brief:** switch 24h/3d/7d, inspect priority events and download a brief.
2. **Feed:** inspect a high-priority card, its original sources and routine bucket.
   Filters & tools also contains manual snapshot tools.
3. **Research:** select a catalogued company or upload a primary PDF for another
   ticker. Try the five cards; inspect citations and missing-evidence behavior.
4. **Quarterly review:** check the original PDF's units, period and basis before
   verifying figures. Do not treat a calculated result as source verification.
5. **Alerts:** save thresholds/types and reload. These preferences affect the
   alert list; the complete feed remains independently available.

Synthetic examples are explicitly tagged and excluded from the normal brief.

## Next steps

1. Authentication, per-user workspaces, rate limits and audit logging.
2. Durable runtime storage, a scheduled collector/queue independent of web-host
   sleep, and tested backup/restore.
3. Authorized exchange access and measurements of missed/duplicate disclosures.
4. A labelled evaluation set for retrieval relevance, entity/period/basis
   consistency, evidence selection and figure extraction; measured layout/OCR
   improvements with review controls.
5. Broader report coverage and explicit notification delivery after those
   foundations are reliable.

## Project map

```text
app/                  FastAPI, ingestion, rules, research, finance, SQLite
static/               Complete HTML / CSS / JavaScript mobile interface
collector.py          Laptop collection, seed export and authenticated replay
sample_data/          Source catalogue, snapshots, NTPC financial manifest
seed/finn.sqlite3     Public bootstrap database
tests/                Unit and integration tests
docs/                 Feature details, checks and submission email draft
data/                 Ignored local runtime DB and logs
Dockerfile            Single-worker production image
```

More detail: [automatic collection](docs/AUTOMATIC_SIGNAL_FEED.md),
[research providers](docs/GEMINI_RESEARCH.md),
[management extraction](docs/MANAGEMENT_CHANGES.md),
[financial review](docs/FINANCIAL_REVIEW_5_MINUTES.md),
[mobile checks](docs/MOBILE_UI_TEST_CHECKLIST.md) and
[covering email draft](docs/SUBMISSION_EMAIL.md).
