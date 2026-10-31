# NTPC financial review: five-minute browser smoke test

Run from the FINN project folder. These seed observations are real source
transcriptions, not fictional test data. They remain UNVERIFIED until you check
the PDF. This checklist tests the workflow; a complete accounting review can take
longer. No management guidance is invented or seeded.

## Before starting the timer

```powershell
.\.venv\Scripts\python.exe -m scripts.seed_ntpc_financials
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8001
```

Open `http://127.0.0.1:8001`. The seed defaults to your local runtime DB and
preserves every existing quarterly row. Optional `--replace-unverified` replaces
only unverified rows; verified rows are always protected. An explicit
`--database seed/finn.sqlite3` updates a deployment seed instead. It does not push
to GitHub, upload financials through the collector API, or replace a live host DB.

## 0:00–1:00: load and inspect

- Open **AI research**, set ticker **NTPC**, expand **Quarterly numbers & guidance
  comparison**, then click **Show quarterly trends & guidance**.
- Expect three standalone rows: `2026-Q3` (Jul–Sep 2026 / NTPC Q2 FY27), `2026-Q2`
  (Apr–Jun 2026), and `2025-Q3` (Jul–Sep 2025). These are the latest completed
  reported quarters as of 1 November 2026, not the unfinished Oct–Dec quarter.
- All rows should show **Unverified**, **Rs crore**, PDF page **2**, and a BSE
  source link. The chart waits for at least two user-verified revenue quarters.

## 1:00–2:00: compare against the primary document

Open the [BSE source](https://www.bseindia.com/xml-data/corpfiling/AttachLive/763a3c28-d8b4-4cfb-83b1-854c78ab5c26.pdf).
If BSE denies access, use the
[official NTPC copy](https://ntpc.co.in/sites/default/files/financial_results/2026/QFRQ2FY27%20Final.pdf).
The NTPC copy was inspected during preparation; BSE returned HTTP 403. Independent
byte-for-byte equivalence of those two downloads was not established.

Check PDF page 2, **standalone**, first three **quarterly** columns:

| Metric (Rs crore) | Jul–Sep 2026 | Apr–Jun 2026 | Jul–Sep 2025 |
|---|---:|---:|---:|
| Revenue from operations | 45,752.00 | 43,831.86 | 39,164.82 |
| Derived operating EBITDA | 10,890.65 | 12,628.87 | 10,017.71 |
| PBT before regulatory deferrals | 5,009.55 | 6,878.80 | 4,887.07 |
| PAT including net-of-tax regulatory deferrals | 5,319.94 | 5,342.36 | 4,653.33 |

EBITDA is **derived**, not a reported row: revenue from operations minus fuel,
purchased electricity, employee benefits and other expenses. It excludes other
income and regulatory deferrals. The JSON manifest retains the component figures.
Use the same EBITDA definition when recording a management target.

## 2:00–3:00: review badge and validation

- Click **Load for source review** on `2026-Q3`. Confirm the form retains the
  values, basis, source URL, PDF page and evidence note. It starts unchecked.
- Try saving with the source URL empty, then with `http://` instead of `https://`.
  The form/API must reject both. Restore the original source URL.
- Only after checking every entered figure, select the review checkbox, save,
  and refresh comparisons. Expect **Verified by user**. The badge is your review
  assertion; it does not mean an audit or automatic source validation.
- QoQ/YoY comparison badges stay unverified until their base rows are also
  reviewed. Edit a figure with the review box unchecked and save: the row must
  return to **Unverified**.

## 3:00–4:00: arithmetic and labels

For `2026-Q3`, expect Revenue QoQ **+4.38%**, YoY **+16.82%**; PAT QoQ **−0.42%**,
YoY **+14.33%**. Check the comparator periods and the absolute changes in Rs crore.
Changing reporting basis to consolidated must suppress comparisons with the
standalone base rows. Restore the correct basis after testing.

Zero/negative bases are covered in pytest: no percentage for zero or negative
denominators; loss-to-profit and changes in losses have explicit labels and
absolute deltas. Do not insert fictional NTPC losses just to test these cases.

## 4:00–5:00: guidance provenance and verdict

- Use an actual management target from an original transcript or company
  presentation: paste its exact quote, source HTTPS URL, interpretation, metric,
  applicable calendar quarter, matching basis, target type and numerical target.
- Set an explicit **in-line tolerance**: Rs crore for absolute amounts or
  percentage points for YoY growth. Zero means exact equality. Higher actuals
  mean **delivered**, lower mean **missed**, and values within tolerance mean
  **in line**. A target for the full financial year is not a quarterly target.
- Save and refresh comparisons. Confirm the quote and source links appear.
  Actuals retain their own review badge. Missing comparable data or unmatched
  reporting basis must produce **Insufficient comparable data**.
- If no genuine numerical quarterly guidance is available, verify that missing
  quote/source fields are rejected and stop there. Do not make up a quote.

## Migration and automated checks

Existing data are preserved. Legacy quarterly rows default to unverified; legacy
guidance without a quote or reporting basis needs to be completed before a
verdict is possible. HTTPS validation applies equally to manual and seed data.

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

The suite covers zero/negative bases, loss-to-profit, quarter rollovers, matching
basis, quote requirements, unit validation, all three guidance verdicts, seed
idempotency, migrations, and preserving/resetting review status.
