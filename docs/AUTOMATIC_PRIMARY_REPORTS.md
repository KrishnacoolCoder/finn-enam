# Automatic primary-report library

Selecting a portfolio ticker in AI research now prepares its catalogue report,
shows a loading/ready status, and lists the indexed document with its date,
original PDF page count and source link. The question waits for preparation to
finish. Other tickers keep the manual upload workflow.

The release seed includes 20 public primary documents: annual reports for
Reliance (FY2025-26), Hindustan Unilever (FY2025-26), and ITC (FY2024-25), plus
earnings-call transcripts for the other 17 companies. The catalogue is a fixed
snapshot prepared on 1 November 2026. Report dates appear in document names.
This is initial source coverage, not a promise of the latest quarter's transcript
or an answer to every possible question. Missing evidence must still produce an
abstention. Generation remains optional; without an LLM key, responses contain
retrieved primary-source excerpts and page citations.

`sample_data/primary_reports.json` pins source URLs and SHA-256 checksums.
Sources are issuer websites/CDNs or NSE's public filing archive. Screener was
used to locate some links; its descriptions, AI summaries, broker research and
news articles are not ingested. The downloaded PDFs were checked for company
identity, readable text, page count and checksum before indexing.

`POST /api/reports/{ticker}/ensure` is limited to the fixed 20-company catalogue.
It has no arbitrary URL/file input. Existing documents make it a fast local
operation. Missing catalogue PDFs are fetched with bounded size/time, approved
HTTPS redirect hosts, a checksum check, failure backoff and per-company locking.
Database insertion and URL deduplication are transactional. Failures retain other
indexed documents. `GET /api/reports/coverage` reports the library's readiness.

Automatic ingestion permits these preapproved reports up to 40 MB/1,000 pages;
manual upload limits remain 20 MB/350 pages. HUL's annual PDF is approximately
30 MB and ITC's annual PDF has 428 pages. Full PDF page numbers are preserved;
there is no invented page numbering, automatic financial verification, or OCR
claim. PDF bytes are not committed; the seed stores searchable text and source
provenance. The seed restores the library after a fresh hosted filesystem.

To rebuild locally from the pinned public sources:

```powershell
.\.venv\Scripts\python.exe -m scripts.index_primary_reports --export-seed
```

To reuse downloaded, checksum-matched PDFs:

```powershell
.\.venv\Scripts\python.exe -m scripts.index_primary_reports --pdf-dir C:\path\to\pdfs --export-seed
```

Local filenames are `TICKER.pdf` (use `M_M.pdf` for M&M). The importer exits
nonzero if any catalogue company fails. It never commits or pushes automatically.

Acceptance checks: 20/20 companies ready, one risk/business question returning
source citations for all 20, repeat selections adding no duplicate documents,
and 109 passing tests. Automated tests cover real PDF page mapping, concurrent
selection, failed downloads, changed checksums, disallowed redirects, manual
upload limits, and restoring the library from the deployment seed.
