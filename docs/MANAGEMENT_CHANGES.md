# Management-change cards

`app/management.py` uses regex and role keywords to extract person name, role,
appointed/resigned/retired and effective date. Dates are normalized to YYYY-MM-DD.
Fields that cannot be extracted, or contain conflicting values, remain empty.
Multiple people/actions in one notice require review rather than a combined card.
No biographies are fetched or generated. This feature does not call an LLM.

`/api/filings` includes `management_change` only for management-change notices;
grouped events preserve it on each underlying filing. The UI shows the card and
original filing link in the overview and signal feed. Blank fields remain blank
in the field list; the title omits missing values.

Sources:

- Headline text, without inferring a name/date from a directory summary.
- Available indexed PDF text matched by exact ticker AND original source URL.
- The automatic collector attempts original BSE-linked PDFs for management
  notices, caching selectable text separately in `filing_pdf_text`. It follows
  no redirects or biography links. Each cycle attempts at most 10 PDFs, up to
  8 MB / 12 pages / 150,000 characters each; failures retry after a day.
- The authenticated laptop ingestion path also transports this cached text,
  including when the announcement is already stored. The seed export preserves
  the cache. Management PDFs are not automatically inserted into research.

Unavailable, blocked, oversized or scanned PDFs leave headline-only extraction.
No OCR or inference is used. This is extraction, not independent verification.

Tests cover six realistic headline formats (fictional names), PDF line wrapping,
missing/ambiguous fields, effective dates, exact source matching, source-link
restrictions, blocked downloads, caching and authenticated duplicate replays.
