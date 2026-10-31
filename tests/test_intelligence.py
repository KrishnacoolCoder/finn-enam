from app.core import assess_filing
from app.grouping import group_filings

def test_transfer_is_ma():
    a=assess_filing('Update on Business Transfer Agreement with Vyoma.AI Limited and Share Purchase Agreement towards sale of entire stake held in subsidiary')
    assert a['category']=='M&A' and a['score']>=85 and a['reason']

def test_results_notice_not_same_as_earnings():
    a=assess_filing('Board meeting scheduled to consider and approve unaudited financial results')
    assert a['score']<=30

def test_results_and_unclassified():
    assert assess_filing('Unaudited Consolidated Financial Results for the quarter ended September 2026')['category']=='results'
    assert assess_filing('Compliance certificate')['category']=='unclassified'

def test_related_results_group_sources_remain():
    sample=[dict(id=i,ticker='NTPC',title=t,published='2026-10-31T15:35:00+05:30',category='results',score=94,excerpt=t,priority_reason='Reported earnings',url=f'https://www.bseindia.com/{i}.pdf') for i,t in enumerate(('Unaudited financial results for quarter ended 30 Sep 2026','Unaudited consolidated financial results for quarter ended 30 Sep 2026'),1)]
    groups=group_filings(sample)
    assert len(groups)==1 and groups[0]['count']==2
    assert {f['url'] for f in groups[0]['filings']}=={f['url'] for f in sample}

def test_separate_ma_not_merged():
    sample=[dict(id=i,ticker='LT',title='Acquisition',published='2026-10-31T15:00:00+05:30',category='M&A',score=93,excerpt='Acquisition',priority_reason='Ownership',url=f'https://www.bseindia.com/{i}.pdf') for i in (1,2)]
    assert len(group_filings(sample))==2
