"""Investor-oriented digest assembled from verified-source filings and available EOD quotes."""
from datetime import datetime,timezone
from .core import PORTFOLIO
from .grouping import group_filings

def build_digest(filings, market=None, hours=24, minimum=0, portfolio_only=True, include_synthetic=False):
    portfolio={t for t,_,_ in PORTFOLIO}
    retained=[f for f in filings if f['score']>=minimum and
       (not portfolio_only or f['ticker'] in portfolio) and
       (include_synthetic or f.get('source')!='synthetic_demo')]
    groups=group_filings(retained)
    for g in groups:
        g['priority_label']='Critical / review now' if g['score']>=85 else 'Material / review' if g['score']>=60 else 'Monitor' if g['score']>=35 else 'Routine'
    relevant=[r for r in (market or []) if r.get('status')=='live_eod' and r.get('alerts')]
    return {
      'generated_at':datetime.now(timezone.utc).isoformat(), 'window_hours':hours,
      'source_policy':'Primary exchange/company filings; synthetic excluded by default.',
      'filings_total':len(retained),'events_total':len(groups),
      'high_priority_events':sum(g['score']>=75 for g in groups),
      'routine_events':sum(g['score']<35 for g in groups),
      'market_alerts':relevant,
      'events':groups,
      'coverage':{'portfolio_companies':len(portfolio),
                  'portfolio_with_filings':len({x['ticker'] for x in retained if x['ticker'] in portfolio})},
      'limitations':('Priority estimates are rules, not investment recommendations. '
          'EOD alerts are generated on refresh, not continuous push notifications. '
          'BSE snapshots are user-uploaded and do not update automatically.')
    }

def markdown_digest(d):
    lines=['# FINN | Investor intelligence brief',
       f"Generated (UTC): {d['generated_at']}",f"Window: last {d['window_hours']} hours",
       f"Material events (≥75): {d['high_priority_events']} · Total events: {d['events_total']}",
       f"Portfolio coverage: {d['coverage']['portfolio_with_filings']} of {d['coverage']['portfolio_companies']} companies",
       '', '## Priority-ranked developments']
    for g in d['events']:
        lines += [f"### {g['ticker']} — {g['title']}",f"Priority {g['score']}/100 · {g['category']} · {g['priority_label']}",
                  f"Why it matters: {g['priority_reason']}",f"Source documents: {g['count']}"]
        lines.extend(f"- [{f['title']}]({f['url']})" if f.get('url') else f"- {f['title']} (URL not supplied)" for f in g['filings'])
        lines.append('')
    lines+=['## EOD triggers (on demand)']
    for r in d['market_alerts']:
        lines.append(f"- {r['ticker']}: {r.get('price_change_pct')}% price, {r.get('volume_multiple')}× volume ({', '.join(r['alerts'])})")
    if not d['market_alerts']:lines.append('No confirmed EOD triggers for this session.')
    lines+=['','## Methodology & limitations',d['source_policy'],d['limitations'],'']
    return '\n'.join(lines)
