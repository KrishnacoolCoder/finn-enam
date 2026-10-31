# FINN — Financial Investment Agent
### ENAM Holdings | AI Engineer Build Challenge | Consolidated Release 4

**FINN** is a responsive Indian equity research and investment-intelligence prototype. It separates **Push** (relevance-ranked exchange disclosures, digest and configurable end-of-day signals) from **Pull** (source-grounded company research, PDF financial extraction and explicit management-guidance comparisons).

**Scope honesty:** This is a working, *local* prototype, not a continuously updating exchange data terminal. NSE/BSE server requests may be blocked. The supported ingestion path is user-supplied official RSS snapshots (which retain original BSE PDF links). On-demand EOD price retrieval uses Yahoo Finance; connectivity may fail. No prices, returns or financial figures are invented.

## Quick start — Windows

1. Extract the ZIP. Open the inner `FINN_ENAM_RELEASE` folder in VS Code.
2. Open **Terminal → New Terminal**.
3. Run the following (PowerShell):

```powershell
py -3 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install --no-compile --no-cache-dir -r requirements.txt
python -m uvicorn app.main:app --reload
```

Visit **http://127.0.0.1:8000**. API specification: **http://127.0.0.1:8000/docs**. Requires Python 3.11–3.13. If PowerShell refuses activation, run `.venv\Scripts\python.exe -m uvicorn app.main:app --reload` instead after installing with that interpreter.

**Already running V3?** Back up the old project. You can replace the `app/`, `static/`, `tests/` and `docs/` folders and `requirements.txt` with this release. **Never overwrite your `data/` directory.** The application adds missing SQLite columns automatically; existing filings and reports are preserved. Do not copy `.venv/` from another computer. Restart the backend and hard-refresh the browser (`Ctrl+Shift+R`).

## The 90-second real-data demo (no paid keys)

1. Open **Intelligence feed**. Click **Load verified BSE sample**. This explicitly loads the included BSE RSS snapshot taken **31 October 2026**—real source links, not a live feed. Or upload your own saved `.xml` / `.txt` file.
2. Select **Last 7 days** *if you are testing near the snapshot date*. For later demonstrations choose an appropriate historical window; `/api/digest?hours=8760` supports up to one year. Observe NTPC results grouping and L&T's business transfer classification as **M&A**. Use **View original filings & sources** to open the PDF links.
3. Choose **Build daily brief** on Overview, then **Download brief** for the source-linked Markdown report. By default, synthetic demo events are excluded.
4. Select **AI research**, type `NTPC`, and upload the official company's quarterly financial results PDF. Under *Quarterly numbers & guidance comparison* choose *Extract candidate figures*.
5. Inspect the reported page, table row, column header, standalone/consolidated basis and recognized unit. **Only after confirming the original PDF**, copy a normalized value. Set `2026-Q3` for July–September 2026, supply the exact BSE PDF URL and save it. Add comparable quarters to see correct QoQ/YoY calculations.
6. Upload an actual annual report or earnings-call transcript, optionally supply its original URL, and ask a source-grounded question. Without an LLM key FINN returns relevant excerpts and citations; with one it drafts a grounded explanation.
7. If connectivity permits, click **Refresh market data** to check 20 NSE tickers for configured EOD price/volume anomalies. Alert records survive restarts; **this is not intraday monitoring**.

**Fictional demo:** For an offline sample research conversation click *Load demo examples* and ask about ticker `FINNDEMO`. All such records are explicitly tagged **SYNTHETIC DEMO**. The real-data investor brief excludes synthetic events unless asked otherwise.

## Functionality map

| Capability | Implementation | Limitations |
|---|---|---|
| Watchlist | 20 NSE companies, sector mix, ticker-independent Q&A | Mock portfolio, no holdings/weights |
| Filings | BSE RSS XML/TXT importer, provenance, deduplication, event grouping | User-uploaded snapshot, **not automatic live** NSE/BSE |
| Materiality | Deterministic rules, categories, scores, explanations, routine-notice downranking | Heuristic; source filing should be reviewed |
| Digest | Configurable time window, portfolio scope, high-priority ranked events, Markdown export | Reflects indexed disclosures only |
| Market signals | EOD daily return, volume vs prior 20-session average, editable thresholds | Yahoo Finance connection required; no intraday data |
| Alerts | Persistent ticker/date/type triggered events, optional periodic polling | No device push notifications; server must stay running |
| Document Q&A | Primary PDF/TXT uploads, chunk retrieval, source pages, optional Gemini evidence selection | Unsupported/scanned PDFs may lack text; no broker research |
| Finance PDFs | Table-first revenue, EBITDA, PBT, PAT candidate rows with source evidence | **Review-assisted**; never auto-verifies/saves numbers |
| Quarterly comparisons | Arithmetic QoQ/YoY; matching reporting basis required | Need user-confirmed quarterly observations |
| Guidance reconciliation | User-entered absolute or YoY-growth guidance vs recorded actual, source links | Manual target capture and human verification |
| Frontend | Responsive dark UI, desktop sidebar, mobile bottom navigation | No phone app binary |

## Sources and accuracy

- Corporate disclosure feed: original BSE RSS `.xml`/`.txt` supplied by the user, **not** scraped via blocked server requests. The ZIP contains the supplied historical snapshot under `sample_data/`.
- Source documents: company-published annual reports, earnings calls and quarterly results. PDFs must be uploaded by the user; citations identify document/page. No broker notes or news are used for company research.
- `yfinance` provides optional EOD price/volume. The application labels connection failures rather than supplying fake values.
- PDF extractor only proposes cells from apparent accounting statement rows. It abstains on narrative-only pages or unknown units, and may still misread some multi-column PDFs. Values must be checked in the original filing before saving.
- Rule priority is **not** a probability, price forecast, or personalized investment recommendation.

## Optional settings

Copy `.env.example` locally and configure environment variables using your shell or hosting provider (this starter doesn't automatically read `.env`):

- `GEMINI_API_KEY`: enables Gemini 2.5 Flash over retrieved primary excerpts; absent or failed calls use extractive mode. See `docs/GEMINI_RESEARCH.md` for setup.
- Research model: `gemini-2.5-flash`, using the `google-genai` SDK.
- `FINN_DATA_DIR`: path to persistent SQLite and indexed files (default `./data`).
- `FINN_AUTO_POLL_MINUTES`: `0` by default, or `60` (must be >=30). Enables an optional in-process EOD watcher, which needs an **always-on backend**; it is not a real-time mobile notification service.

Deployment uses `Dockerfile` or `Procfile` to start on `$PORT`. Use persistent disk if you want your SQLite records to survive redeployments. **There is no authentication or tenant isolation; do not expose writable endpoints as a public multi-user service** without adding protection first. For a hiring review, private/local or controlled-demo usage is safest.

## Verify

```powershell
python -m pytest -q
python -m compileall -q app
```

Development checks include parser tests, real-snapshot deduplication, event grouping, document extraction rejection, source-cited calculations and API smoke tests. A browser screenshot/environment cannot substitute for validating your deployed URL: test it yourself before emailing ENAM.

## Repository / structure

```
FINN_ENAM_RELEASE/
  app/                  # FastAPI routes, financial engine, BSE parser, retrieval, SQLite
  static/               # HTML / CSS / JavaScript mobile-first interface
  sample_data/          # historical original BSE RSS snapshot (user-provided)
  sample_documents/     # explicitly synthetic FINNDEMO source samples
  tests/                # unit and integration acceptance tests
  docs/                 # architecture, demo, submission checklist/email
  data/                 # locally generated SQLite — NOT committed to GitHub
  requirements.txt
  Dockerfile, Procfile
```

More information: `docs/ARCHITECTURE.md`, `docs/DEMO_AND_SUBMISSION.md`, `docs/SUBMISSION_EMAIL.md`.

## Non-goals and tradeoffs

This release focuses on a **thin-but-working investor workflow**: distinguish important filings from routine noise, preserve the chain to primary sources, retrieve actual filings, and perform only properly reviewed financial analysis. Exchange blocking prevents automatic official live sync. Automated results reconciliation at scale, management biography enrichment, mobile OS push alerts, voice, team collaboration, brokerage integrations and production authentication remain out of scope. The honest limitation is part of the engineering judgment ENAM asks candidates to demonstrate.
