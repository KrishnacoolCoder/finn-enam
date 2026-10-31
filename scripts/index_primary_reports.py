"""Populate the public primary-report catalogue locally, then export a seed.

python -m scripts.index_primary_reports
--pdf-dir is optional: use already-downloaded catalogue PDFs named TICKER.pdf
(use M_M.pdf for M&M). Every local copy is checked against its pinned checksum.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path

from app import storage
from app.primary_reports import catalog, download, MAX_REPORT_BYTES, MAX_REPORT_PAGES
from app.research import ingest


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pdf-dir',type=Path)
    parser.add_argument('--export-seed',action='store_true')
    args=parser.parse_args()
    storage.init()
    failures=[]
    for ticker,reports in catalog().items():
        for report in reports:
            try:
                if args.pdf_dir:
                    data=(args.pdf_dir/(ticker.replace('&','_')+'.pdf')).read_bytes()
                else:
                    data=download(report)
                if hashlib.sha256(data).hexdigest()!=report['sha256']:
                    raise ValueError('Catalogue checksum mismatch')
                result=ingest(ticker,report['name'],data,report['kind'],report['url'],
                    auto_loaded=True,max_bytes=MAX_REPORT_BYTES,max_pages=MAX_REPORT_PAGES)
                print(ticker,json.dumps(result),flush=True)
            except Exception as exc:
                failures.append(ticker)
                print(ticker,'FAILED',type(exc).__name__,flush=True)
    if failures:
        raise SystemExit('Incomplete coverage: '+', '.join(failures))
    if args.export_seed:
        from collector import export_seed
        export_seed()
        print('Public primary-report index exported to seed/finn.sqlite3')


if __name__=='__main__':
    main()
