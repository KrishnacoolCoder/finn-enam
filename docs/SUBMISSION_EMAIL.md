To: assessment@enam.com

Subject: ENAM - IIT screening - 2027

Dear ENAM Team,

Please find my submission: FINN, a mobile-first investment-intelligence and primary-source research prototype covering a 20-company NSE watchlist.

Live demo: https://finn-enam.onrender.com
Repository: https://github.com/KrishnacoolCoder/finn-enam

The Push workflow prioritises and groups exchange-linked announcements, collapses routine filings, generates time-windowed briefs, and supports configurable end-of-day price/volume alerts. The Pull workflow indexes company PDFs, retrieves evidence with TF-IDF, and returns file/page-cited passages. It also includes rule-based management-change extraction and review-assisted quarterly comparisons.

I used rule-based classification, deterministic arithmetic and TF-IDF before invoking an LLM, keeping common operations inexpensive and explainable. Models select evidence; the server inserts the original passages and citations rather than trusting unrestricted generated prose.

Because exchanges can block automated access, an authenticated laptop collector uploads idempotently to the deployed app, with retained snapshots as fallback. This keeps the demo usable without claiming uninterrupted live coverage. News is shown only as market context and excluded from research to honour the primary-source rule. Model failures also fall back safely; Groq-backed cited responses were verified live.

I left out production authentication/tenant isolation, intraday streaming, device push and unattended financial verification. Next steps are durable storage, access controls, authorised exchange access, and a labelled retrieval/evidence-quality evaluation set.

The project passes 177 pytest tests; mobile layouts were checked at 360/390/430px. External-source availability and PDF accuracy remain explicit limitations.

Thank you for considering my submission.

Regards,
[Your full name]
