# FINN V4 — Optional BSE RSS integration (Windows)

## What this patch does

Changes only `app/live_bse.py` and adds `tests/test_live_bse_rss.py`.
The existing `app/deploy.py` already calls `sync_bse()`, so the protected sync endpoint will use the RSS feed after updating this module.

- RSS is the default live transport; the old JSON endpoint remains available with `--source json` for diagnostics.
- Reuses existing `parse_feed`, `classify`, `excerpt`, SQLite deduplication and event grouping.
- Accepts only configured six-digit BSE codes from `data/portfolio.json`, a matching date, and original official HTTPS PDF URLs.
- On 403, malformed XML, no eligible company, or other fetch errors, returns `source: snapshot` and preserves existing SQLite filings.
- Does not promise that the BSE RSS feed covers 20 stocks or a full requested period; the observed public feed contained only one ETF announcement.

## Install

1. Back up your current FINN project (you already made a zip backup earlier).
2. Download `FINN_V4_BSE_RSS_PATCH.zip` into Windows Downloads.
3. In VS Code PowerShell, from `FINN_ENAM_RELEASE`, with `.venv` active, run:

```powershell
Expand-Archive -Path "$env:USERPROFILE\Downloads\FINN_V4_BSE_RSS_PATCH.zip" -DestinationPath (Get-Location).Path -Force
python -m pytest -q
```

The known setup has **47 passing tests** (43 previous + four RSS tests). If your project differs, review any errors before proceeding.

## Test actual feed

```powershell
python -m app.live_bse --days 3
```

Expected status:

- `source: live`: BSE RSS returned at least one date-matching PDF filing for a configured portfolio stock. `added: 0` can mean already imported.
- `source: snapshot`: feed blocked, malformed, or contains no relevant company filings. Existing DB remains unchanged.

The one observed RSS item was `SBI Sensex ETF (535276)`, which is NOT `SBIN (500112)`. It must not be imported as SBI shares.

## Publish only after local tests pass

```powershell
git add app/live_bse.py tests/test_live_bse_rss.py RSS_INTEGRATION_WINDOWS.md
git commit -m "Add BSE RSS live feed with portfolio filtering and fallback"
git push origin main
```

Confirm Render deploy of the new commit and `/health`. There is **no need to change** the runtime database, seed, main.py, storage.py, or Dockerfile.

## Optional Render manual sync (only if already configured)

If `FINN_BSE_SYNC_KEY` is already set in Render, use your existing protected POST endpoint to try a refresh. Do not expose or commit the key. The public UI does not automatically poll on its own.

## Important operational note

The free Render filesystem is ephemeral. A successful sync adds records to its current instance, not a durable external database. A restart can restore the committed seed instead. Do not claim that live BSE ingestion is operational unless a matching portfolio filing is retrieved on the deployed server.
