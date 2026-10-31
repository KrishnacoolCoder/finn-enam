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
Without a key, the app continues in extractive mode.

Gemini 2.5 Flash has a free tier subject to Google's project/model quotas. Using
this SDK does not itself choose your project's billing tier. See Google's
[key instructions](https://ai.google.dev/gemini-api/docs/api-key) and
[current pricing](https://ai.google.dev/gemini-api/docs/pricing#gemini-2.5-flash).

## Retrieval and grounding

- Page-aware chunks target 800 approximate word/punctuation tokens with 100-token
  overlap, bounded by each original PDF page. Short pages remain short.
- Legacy indexes are upgraded once per document, reconstructing each original
  page from its overlapping stored chunks. Page numbers stay unchanged.
- TF-IDF remains the retriever. Metric-specific relevance filtering excludes
  unrelated overview chunks; quantitative snapshots require numeric evidence.
- Gemini sees only the retrieved excerpts, the question and grounding rules.
  It selects concise verbatim evidence for the answer. The server checks every
  quote against the cited chunk and supplies `[file, page]` labels itself. Free
  prose that could add unsupported claims is not displayed.
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
failure fallbacks cache for 60 seconds. Adding/removing a key switches modes
without serving an old answer from the wrong mode. SQLite cache persists in the
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
