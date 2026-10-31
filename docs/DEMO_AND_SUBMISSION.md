# ENAM screening — demo & submission checklist

## 4-minute walkthrough

1. **Problem (25 seconds):** A portfolio manager receives far too many disclosures. FINN prioritizes the few decision-relevant events with source links and audit trails.
2. **Push (65 seconds):** Open Intelligence feed. Select *Load verified BSE sample* (historical 31 Oct 2026 snapshot). Show NTPC results grouped together, L&T's business transfer flagged M&A, materiality explanations and expandable original filings. Change the window and materiality filter; explain that snapshots aren't continuously live.
3. **Digest & alerts (45 seconds):** Show Overview daily brief, download a Markdown brief, change EOD alert thresholds. When connected, refresh Yahoo EOD prices; otherwise explain controlled failure and stored alert history.
4. **Pull (85 seconds):** Enter an NSE ticker, index a real annual report or earnings transcript, ask a question, expand source citations. Upload results PDF, show candidate table rows, explain unit/period/basis verification and source page. Show QoQ/YoY and guidance-vs-actual once verified figures exist. If there is no real report on the machine, use explicit synthetic FINNDEMO for the research demonstration, clearly disclosed as such.
5. **Architecture (20 seconds):** Show `/docs`, repo structure, tests, deterministic-first scoring and optional model synthesis. Explain excluded production features honestly.

## Before emailing

- [ ] Start server on a fresh machine; check home, feed, research, portfolio in 390px Chrome device emulation.
- [ ] Run `python -m pytest -q` and record the result accurately.
- [ ] Open several BSE original source PDFs; verify links work in the evaluation browser.
- [ ] Test the actual quarterly-results PDF you plan to showcase; do not claim extracted values are automatically verified.
- [ ] Set up a **deployed, mobile-accessible URL** (or supported mobile release) and verify it outside localhost; if using SQLite, attach persistent disk or seed a controlled demo.
- [ ] Create and push a public or appropriately accessible GitHub repository; do not commit your `.env`, API keys, `.venv`, or local SQLite.
- [ ] Share/export **genuine** AI build history (this ChatGPT conversation and any other coding agent conversations) with access enabled for evaluators.
- [ ] Add URLs and exact testing details to `SUBMISSION_EMAIL.md` and send before 1 November 2026 deadline.

## Limits to disclose

*Real exchange feed sync cannot be guaranteed due NSE/BSE request blocking; bundled RSS snapshot is dated and user-supplied.*
*Actual market alerts use end-of-day data, not tick-by-tick monitoring.*
*PDF financial extraction and management guidance need human review and proper basis/unit alignment.*
*The deployed application and repository are the submitter's responsibility; the ZIP is only a source artifact.*
