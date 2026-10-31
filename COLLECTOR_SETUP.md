# Laptop collector setup

Built against FINN commit `482792e`. Copy the files from this upgrade ZIP into
your existing project root, replacing matching files. It does not include or
replace your runtime DB or your current seed. No dependency changes are needed.

1. On your deployed service, set a long random `INGEST_TOKEN` environment secret.
   Redeploy with these code changes. Both `app.main:app` and `app.deploy:app`
   expose the new endpoint. Keep your existing `FINN_DATA_DIR` configuration.
2. In PowerShell on your laptop, activate the project's environment and set the
   same token. The app does not automatically load `.env` files.

   ```powershell
   $env:INGEST_TOKEN = 'your-long-random-secret'
   python collector.py https://YOUR-SPACE.hf.space --loop 15
   ```

   You can use your Render URL instead. Omit `--loop 15` for one cycle.
   `--days 3` is the default collection window (1–31 days supported).
   A full `/api/ingest` endpoint URL is accepted too. Ctrl+C stops the loop.
   Keep the laptop awake for collection to continue.

3. Each cycle runs the existing BSE RSS sync locally, exports `seed/finn.sqlite3`,
   and uploads the source-linked, non-synthetic local filings in batches of 500.
   Historical replay repairs missed uploads and host restarts. There is no news
   fetcher in this repository, so no news task is invoked. RSS retention and
   portfolio filtering still apply; a successful connection can yield no matches.
   An upload failure leaves the local DB and exported seed available. Looped
   operation retries on the next cycle; one-shot operation exits nonzero.

4. Commit the refreshed seed when you want the host to restore it after a reset:

   ```powershell
   git add seed/finn.sqlite3
   git commit -m "Refresh announcement seed from laptop collector"
   git push origin main
   ```

   The collector never commits or pushes automatically. The seed is a SQLite
   backup of your local DB, including documents and other local records: use a
   dedicated collector data directory if your usual DB contains private content.
   For example set `$env:FINN_DATA_DIR = "$PWD/collector-data"` before starting;
   add `collector-data/` to your local Git exclusions. A missing runtime DB is
   restored from the current committed seed. An existing runtime DB is preserved.

## Endpoint contract

`POST /api/ingest` accepts a JSON **list** of announcements. Required fields:
`ticker`, `title`, timezone-aware ISO `published`, and HTTPS `url`. Optional:
`source`, `description`, `excerpt`. Incoming category/score values are ignored;
the server runs its existing classifier. Maximum batch: 5,000 records.

Headers: `X-Ingest-Token` (required, equals server `INGEST_TOKEN`), and
`X-Ingest-Source: live|snapshot` (defaults to `live`). Disabled configuration
returns 503; missing/wrong token returns 403. Validation errors return 422.
No source URL is fetched by this endpoint.

Response includes `received`, `added`, `duplicates`, `last_updated`,
`last_attempt`, and `source`. Rows deduplicate by ticker+URL, and the existing
ticker+published+title constraint remains enforced. The batch is transactional,
including across simultaneous uploads.

`GET /api/ingest/status` exposes only freshness metadata. The UI polls this every
minute and shows `Last updated X min ago · live/snapshot`. The timestamp means
the last nonempty live collection accepted, including already-known records;
it is not the publication time or evidence of complete exchange coverage.
Snapshot and empty uploads preserve that timestamp and display `snapshot`.
A newly exported seed is labeled snapshot on restoration. If no live timestamp
exists, the UI displays `Update time unknown · snapshot`.

## Verification

```powershell
python -m pytest -q
```

This upgrade passed 57 tests locally, including token rejection, idempotent and
concurrent uploads, invalid batch rejection, snapshot freshness, WAL-safe seed
backup/restoration, and backup retention on upload failure. External BSE and
host connectivity were not exercised by these mocked/local tests.
