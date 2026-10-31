# Submission email template — customize before sending

**To:** assessment@enam.com

**Subject:** ENAM - IIT screening - 2027

Dear ENAM Team,

Please find my submission for the FINN AI Engineer Build Challenge.

**Mobile-accessible prototype:** [INSERT VERIFIED DEPLOYED URL]

**GitHub repository:** [INSERT REPOSITORY URL]

**AI-assisted build history:** [INSERT REAL CONVERSATION EXPORT/SHARE URL]

I built FINN, a mobile-first financial-investment intelligence prototype that filters exchange disclosures into source-linked, relevance-ranked events and supports on-demand, primary-document-grounded company research. Its Push workflow includes a BSE RSS snapshot importer, explainable event grouping, configurable EOD market alerts and an exportable portfolio brief. Its Pull workflow supports PDF/TXT-based research with page citations, review-assisted financial-table extraction, QoQ/YoY calculations and manually verified management-guidance comparisons.

**Technical decisions:** FastAPI and SQLite support a small, runnable prototype; deterministic scoring, financial arithmetic and TF-IDF document retrieval minimize cost; optional model synthesis is limited to retrieved primary-source passages. Source PDFs remain linked and synthetic demonstrations are visibly labelled.

**Scope and tradeoffs:** NSE/BSE server-side access may be blocked, so live disclosure collection is represented by user-uploaded official BSE snapshots rather than claimed as continuous automation. PDF figures require manual review for units, table columns and reporting basis, and alerts are end-of-day rather than intraday or device push notifications. A production release would add authorized exchange data access, verified structured financial extraction, user authentication and scalable storage.

Thank you for considering my work.

Regards,
[YOUR FULL NAME]
[YOUR ROLL NUMBER / CONTACT DETAILS]
