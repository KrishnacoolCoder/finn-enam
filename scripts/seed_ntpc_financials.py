"""Seed real source-linked NTPC quarterly observations, unverified by default.

Run: python -m scripts.seed_ntpc_financials
Use --database seed/finn.sqlite3 to explicitly update a deployment seed.
No network fetch, fictional figures, or guidance targets are inserted.
"""
from __future__ import annotations
import argparse
import json
import sqlite3
from contextlib import closing
from decimal import Decimal
from pathlib import Path

from app import financials, storage

MANIFEST = Path(__file__).resolve().parents[1] / 'sample_data' / 'ntpc_quarters_2026_q3.json'


def seed(database, replace_unverified=False):
    data = json.loads(MANIFEST.read_text(encoding='utf-8'))
    financials.primary_url(data['source_url'])
    for row in data['quarters']:
        derived = Decimal(str(row['revenue'])) - sum(Decimal(str(v)) for v in row['components'].values())
        if derived != Decimal(str(row['ebitda'])):
            raise ValueError('Derived EBITDA components do not reconcile')
    database = Path(database)
    database.parent.mkdir(parents=True, exist_ok=True)
    added = skipped = 0
    with closing(sqlite3.connect(database)) as db:
        db.row_factory = sqlite3.Row
        financials.setup(db)
        db.execute('BEGIN IMMEDIATE')
        with db:
            for row in data['quarters']:
                old = db.execute('SELECT verified FROM quarterly_financials WHERE ticker=? AND period=?',
                                 (data['ticker'], row['period'])).fetchone()
                if old and (old['verified'] or not replace_unverified):
                    skipped += 1
                    continue
                financials.save_quarter(data['ticker'], row['period'], row, data['source_url'],
                    data['basis'], data['evidence_page'], False,
                    data['evidence_note'] + ' Official copy: ' + data['official_copy'], db=db)
                added += 1
    return {'saved': added, 'skipped_existing': skipped, 'verified': False,
            'current_period': data['current_period'], 'as_of': data['as_of'],
            'note': 'Fixed historical release as of 1 November 2026; not automatically rolling current-quarter data.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, default=storage.DB)
    parser.add_argument('--replace-unverified', action='store_true',
                        help='Replace existing unverified rows; verified rows are always preserved')
    args = parser.parse_args()
    print(json.dumps(seed(args.database, args.replace_unverified), indent=2))


if __name__ == '__main__':
    main()
