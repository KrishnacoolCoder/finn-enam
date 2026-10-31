# Inline Screener snapshot

In AI research, selecting a company now displays public Screener valuation ratios
and the latest five reported quarterly columns. Choose standalone or consolidated
in the snapshot card. Original row labels, blanks, percentages and per-share units
are retained. Operating profit is not silently renamed EBITDA, and no values are
copied into the reviewed quarterly-financials table.

`GET /api/company-context/{ticker}?basis=consolidated` fetches the public company
page on demand and caches the parsed numeric snapshot in `company_context` for
six hours. It performs no login, challenge bypass, redirected fetch, or hidden
Screener API call. A timeout, response-size limit and strict table/header checks
protect the parser. Failed requests back off for five minutes. Previously saved
data remain available with a stale warning; missing data show an unavailable
message. Fetch time is displayed and must not be read as the quote's market time.

The old navigation-only Screener link is replaced by the inline snapshot, with a
source attribution link beneath it. NSE remains available as a primary-source
directory. Screener content is labeled unverified secondary-source context and
is excluded from document Q&A, user-reviewed financials, and guidance verdicts.
Do not compare a consolidated Screener snapshot with standalone reviewed figures
without reconciling their basis, rounding and metric definitions.

No new dependencies are required; FINN already includes requests and BeautifulSoup.
Live NTPC fetches worked in both modes during local verification. Scraping remains
dependent on Screener's public availability and HTML structure.
