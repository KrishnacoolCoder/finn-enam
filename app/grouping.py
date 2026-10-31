"""Presentation-only event grouping: underlying filings stay individually accessible."""
from __future__ import annotations
import re
from collections import defaultdict
from datetime import datetime

def event_key(f):
    category=f['category']; text=(f.get('title','')+' '+f.get('excerpt','')).lower()
    day=f['published'][:10]
    if category=='results':
        period=re.search(r'(?:quarter|half.year).*?(?:sep(?:tember)?|dec(?:ember)?|mar(?:ch)?|jun(?:e)?)\w*\s*\d{0,2}[^\d]{0,8}(20\d\d)',text)
        return (f['ticker'],category,period.group(0) if period else day)
    if category=='dividend':return (f['ticker'],category,day)
    if category=='M&A':
        # Only group repeated records of the same actual attachment, not all acquisitions of the day.
        return (f['ticker'],category,f.get('url') or f['id'])
    return (f['ticker'],category,f.get('url') or f['id'])

def group_filings(filings):
    groups=defaultdict(list)
    for item in filings:groups[event_key(item)].append(item)
    result=[]
    for items in groups.values():
        ranked=sorted(items,key=lambda x:(-x['score'],x['published']))
        top=ranked[0]
        result.append({'ticker':top['ticker'],'category':top['category'],'score':max(x['score'] for x in items),
                       'title':top['title'],'published':max(x['published'] for x in items),
                       'priority_reason':top['priority_reason'],'count':len(items),'filings':items})
    return sorted(result,key=lambda x:(-x['score'],x['published']))
