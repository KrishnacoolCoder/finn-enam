# Gemini research setup

FINN uses `google-genai` and `gemini-2.5-flash`, with TF-IDF retrieval over indexed
primary PDF/TXT documents. No news or Screener data enters research.

## Get an API key

1. Open [Google AI Studio](https://aistudio.google.com/), sign in and accept the
   terms if prompted.
2. Open **Get API key / Dashboard > API Keys** and create a key. Choose/create a
   project; existing Cloud projects may first need importing in the Projects view.
3. On Render, open the FINN service's **Environment** page, add `GEMINI_API_KEY`
   with the key as its value, then save and redeploy.
4. Ask a research question. The footer shows **Gemini** or **Extractive**, and
   whether an answer came from cache. Keep the key on the server; never commit it
   or place it in frontend code.

Local PowerShell, after installing requirements:

```powershell
$env:GEMINI_API_KEY='your-key'
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

The example environment file is a template; it is not loaded automatically.
Without either provider key, the app continues in extractive mode.

## Groq backup

Research uses **Gemini -> Groq -> extractive**. Each configured provider uses
the identical source-only prompt and server-side quote/citation checks. A valid
insufficient-evidence response is retained rather than shopping providers for a
different answer.

Create a key at [Groq Console](https://console.groq.com/keys). Add `GROQ_API_KEY`
under the FINN service's Render Environment settings, then save/redeploy.
Keep `GEMINI_API_KEY` to retain Gemini as primary. Groq also works alone when no
Gemini key is configured. `GROQ_MODEL` defaults to `openai/gpt-oss-120b`.
The previous `llama-3.3-70b-versatile` default is automatically migrated to this
replacement because Groq retired it for free/developer usage. Groq receives the
top four retrieved chunks to keep requests smaller for free-tier token quotas.
The Groq integration uses the existing requests dependency and JSON-object mode;
the server independently validates the response schema and evidence.

The answer footer identifies Gemini, Groq or Extractive, and cached answers.
Failures contain only allowlisted reason codes and optional HTTP status numbers:
`rate_limited`, `authentication_failed`, `permission_denied`, `model_unavailable`,
`invalid_request`, `request_timeout`, `invalid_evidence`, `provider_unavailable`.
No raw exception messages, API keys, response bodies or private passages appear
in diagnostics. Invalid evidence means quote/JSON validation failed; it does not
prove that a key is invalid.

Groq retries HTTP 429 at most twice with backoff, respecting short Retry-After
values. Long quota waits fall back promptly. See the official
[model documentation](https://console.groq.com/docs/model/openai/gpt-oss-120b)
and [rate limits](https://console.groq.com/docs/rate-limits).

Gemini 2.5 Flash has a free tier subject to Google's project/model quotas. Using
this SDK does not itself choose your project's billing tier. See Google's
[key instructions](https://ai.google.dev/gemini-api/docs/api-key) and
[current pricing](https://ai.google.dev/gemini-api/docs/pricing#gemini-2.5-flash).

## Retrieval and grounding

- Page-aware chunks target 800 approximate word/punctuation tokens with 100-token
  overlap, bounded by each original PDF page. Short pages remain short.
- PDF ingestion preserves original paragraph-block order instead of sorting
  equal-height lines across columns. The 20 pinned public reports have been
  rebuilt from their checksum-verified originals. Existing document IDs, source
  URLs and PDF page numbers are preserved. Older automatic indexes are refreshed
  on report loading; old manually uploaded PDFs need re-uploading to repair
  layout when only the flattened text remains available.
- Legacy indexes are upgraded once per document, reconstructing each original
  page from its overlapping stored chunks. Page numbers stay unchanged.
- TF-IDF remains the retriever. Metric-specific relevance filtering excludes
  unrelated overview chunks; quantitative snapshots require numeric evidence.
- Card-specific retrieval queries use topic words instead of card instructions.
  Audit boilerplate is excluded unless the question explicitly concerns audit,
  accounting, internal controls or going concern. Explicit audit questions still
  use those passages.
- Gemini sees only the retrieved excerpts, the question and grounding rules.
  Retrieved excerpts are segmented into readable numbered sentences. Both models
  return only source/passage IDs; the server inserts the selected source text and
  `[file, page]` labels. Invalid IDs are rejected. Model-supplied prose is never
  used as factual answer text. Quote checks normalize typographic quotes,
  discretionary hyphens and PDF hyphen line wraps while retaining numbers and
  minus signs.
- Answers contain at most four evidence bullets, each at most 600 characters.
  Extractive fallback selects up to three readable complete sentences and never
  displays large clipped chunks. If no readable relevant sentence is available,
  it returns `insufficient evidence`.
- Missing evidence produces `insufficient evidence`. Invalid source IDs,
  invented quotes, malformed responses and failed calls use the extractive
  fallback. Guidance is never automatically treated as delivered actuals.
- The SDK has a 20-second request timeout. HTTP 429 gets at most three attempts
  total with exponential backoff and jitter; other failures fall back immediately.

## Cache and ad-hoc companies

`research_answers` is keyed by `(ticker, normalized question, document_hash)`.
The hash covers document identities, names, source URLs, original hashes, actual
indexed text, and research/model policy versions. Added/changed documents
invalidate prior answers. No-key extractive answers persist; temporary Gemini
failure fallbacks and Groq backups after a Gemini failure cache for 60 seconds.
Groq-only success can remain cached. Adding/removing/rotating a key or changing
the Groq model bypasses the prior configuration's cache; keys are never stored
in plaintext in cache records. SQLite cache persists in the
runtime database and collector seed exports; a host reset restores the committed
seed rather than any unexported runtime changes.

Enter any syntactically valid NSE ticker in Research, upload its original PDF,
then use the five cards or a custom question. Ad-hoc ticker validation does not
claim the symbol was checked against an exchange listing. Duplicate identical
uploads reuse the existing document; the same retrieval and answer cache apply.

## Verification

`tests/test_gemini_research.py` mocks Gemini and covers evidence/citation checks,
unsupported claims, fallback, cache invalidation and mode changes, HTTP 429
backoff, ad-hoc uploads, legacy migration, page boundaries and overview filtering.
The SDK configuration is tested without any external model calls.
