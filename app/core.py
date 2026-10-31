"""Deterministic finance and filing logic, separated from LLM output."""
from __future__ import annotations
import re
from datetime import datetime, timezone

PORTFOLIO = [
 ('RELIANCE','Reliance Industries','Energy'),('HDFCBANK','HDFC Bank','Banking'),
 ('ICICIBANK','ICICI Bank','Banking'),('SBIN','State Bank of India','Banking'),
 ('TCS','Tata Consultancy Services','Technology'),('INFY','Infosys','Technology'),
 ('WIPRO','Wipro','Technology'),('ONGC','ONGC','Energy'),
 ('MARUTI','Maruti Suzuki','Automotive'),('M&M','Mahindra & Mahindra','Automotive'),
 ('HINDUNILVR','Hindustan Unilever','Consumer'),('ITC','ITC','Consumer'),
 ('SUNPHARMA','Sun Pharma','Pharma'),('DRREDDY','Dr Reddy’s Laboratories','Pharma'),
 ('LT','Larsen & Toubro','Industrials'),('ADANIPORTS','Adani Ports','Infrastructure'),
 ('BHARTIARTL','Bharti Airtel','Telecom'),('TATASTEEL','Tata Steel','Metals'),
 ('TITAN','Titan Company','Consumer'),('NTPC','NTPC','Power')]

CATEGORIES = {
 'results': ['financial results','quarterly results','annual results','quarter ended','statement of audited'],
 'management_change':['resignation','appointment of','appointed as','director resign','chief financial officer','chief executive officer'],
 'M&A':['acquisition','acquire','merger','demerger','joint venture','stake purchase'],
 'litigation':['litigation','penalty','regulatory order','show cause notice','fine imposed','insolvency'],
 'credit_rating':['credit rating','rating upgrade','rating downgrade','icra','crisil','care ratings'],
 'fund_raise':['qip','rights issue','preferential allotment','commercial paper','fund raising','buyback'],
 'pledging':['pledge','encumbrance'],
 'capex':['capital expenditure','new plant','capacity expansion'],
 'dividend':['dividend','record date'],
 'bonus_split':['stock split','bonus issue','sub-division'],
 'earnings_call':['earnings call','conference call','concall','transcript'],
 'insider_trading':['insider trading','insider transaction'],
 'investor_meetings':['investor meet','analyst meet','investor conference'],
 'press_release':['press release','order win','product launch','partnership'],
 'postal_ballot':['postal ballot'],
 'agm_egm':['annual general meeting','extraordinary general meeting','egm','agm'],
}
BASE_IMPORTANCE = {'results':94,'management_change':92,'M&A':93,'litigation':91,'credit_rating':82,'pledging':86,'capex':78,'fund_raise':76,'press_release':55,'dividend':52,'bonus_split':54,'earnings_call':44,'insider_trading':49,'investor_meetings':24,'agm_egm':20,'postal_ballot':19,'unclassified':10}

# Explanation-first classification. Category is based on the EVENT, not just its wording.
# A filing about upcoming results is less material than published results.
RULES = [
 ('M&A', 93, [r'business transfer agreement',r'share purchase agreement',r'sale of (?:the |entire )?stake',r'divest(?:ment|iture)',r'disposal of (?:a |the )?subsidiary',r'acquisition',r'acquir(?:e|ing)',r'merger',r'demerger',r'joint venture',r'stake sale',r'stake purchase',r'slump sale',r'sale of entire stake',r'transfer of (?:the )?business']),
 ('litigation',91,[r'insolvency',r'bankruptcy',r'penalty imposed',r'fine imposed',r'regulatory order',r'litigation',r'show cause notice',r'loan default',r'default on payment']),
 ('management_change',92,[r'chief financial officer.*resign',r'chief executive officer.*resign',r'cfo.*resign',r'ceo.*resign',r'resignation of (?:the )?(?:chief|director|managing|company secretary)',r'appointment of (?:the )?(?:chief|director|managing|company secretary)',r'change in (?:senior )?management',r'appointed as (?:ceo|cfo|director)']),
 ('pledging',86,[r'pledging',r'pledge of shares',r'promoter pledge',r'encumbrance']),
 ('credit_rating',82,[r'credit rating',r'rating downgrade',r'rating upgrade',r'crisil',r'icra',r'care ratings']),
 ('capex',78,[r'capital expenditure',r'capacity expansion',r'new plant',r'approval of capex',r'new manufacturing facility']),
 ('fund_raise',76,[r'rights issue',r'preferential allotment',r'qualified institutional placement',r'\bqip\b',r'commercial paper',r'non.convertible debenture',r'fund raising',r'buyback']),
 ('results',94,[r'operational and financial snapshot',r'financial and operational snapshot',r'unaudited.*financial results',r'audited.*financial results',r'quarterly results',r'financial results for',r'financial results of',r'result for the quarter',r'earnings presentation',r'financial results.*ended',r'quarterly financial results']),
 ('dividend',52,[r'dividend',r'record date']),
 ('bonus_split',54,[r'bonus issue',r'stock split',r'sub.division of shares']),
 ('earnings_call',44,[r'earnings call',r'conference call',r'concall',r'call transcript',r'analyst call']),
 ('insider_trading',49,[r'insider trading',r'insider transaction',r'promoter.*(?:bought|sold).*shares']),
 ('investor_meetings',24,[r'analyst meet',r'investor meet',r'investor conference']),
 ('press_release',55,[r'press release',r'order win',r'purchase orders',r'product launch',r'partnership']),
 ('postal_ballot',19,[r'postal ballot']),
 ('agm_egm',20,[r'annual general meeting',r'extraordinary general meeting',r'\begm\b',r'\bagm\b']),
]
ROUTINE = [r'newspaper publication', r'newspaper advertisement',r'board meeting.*scheduled',r'meeting of the board.*scheduled',r'notice of board meeting',r'compliance certificate',r'trading window',r'publication of.*results']

def assess_filing(title: str, body: str='') -> dict:
    text=' '.join((title+' '+body[:1200]).lower().split())
    # Avoid overclaiming based on a generic filing title or vague wording.
    for category,base,patterns in RULES:
        matched=next((pattern for pattern in patterns if re.search(pattern,text)),None)
        if matched:
            routine=next((x for x in ROUTINE if re.search(x,text)),None)
            if routine and category in ('results','press_release','agm_egm'):
                return {'category':category,'score':min(base,30),'reason':'Routine notice or secondary publication; not the underlying material event.','confidence':'rule-based'}
            return {'category':category,'score':base,'reason':{
                'M&A':'Business acquisition, stake disposal, merger or transfer may materially change company operations or ownership.',
                'results':'Reported financial performance warrants review against previous periods.',
                'management_change':'Senior leadership change may affect execution and governance.',
                'litigation':'Legal, regulatory or credit distress can create material risk.',
                'dividend':'Cash distribution or relevant record date affects shareholders.',
                'capex':'Investment in capacity or assets could affect future cash flows.'
            }.get(category,'Announcement matches the '+category.replace('_',' ')+' event category.'),'confidence':'rule-based'}
    if re.search(r'\btransfer agreement\b|\bstake held\b',text):
        return {'category':'M&A','score':88,'reason':'Possible change in ownership or business assets; review the original filing for materiality.','confidence':'review-needed'}
    return {'category':'unclassified','score':10,'reason':'Insufficient detail to establish materiality from feed text; inspect linked filing.','confidence':'review-needed'}

def classify(title: str, body: str='') -> tuple[str,int]:
    result=assess_filing(title,body)
    return result['category'],result['score']

def signals(closes: list[float], volumes: list[int], price_threshold: float=5.0, volume_threshold: float=2.0) -> dict:
    if len(closes)<2 or len(volumes)<2: return {'price_change_pct':None,'volume_multiple':None,'alerts':[]}
    previous=closes[-2]
    change = round(100*(closes[-1]/previous-1),2) if previous else None
    past=volumes[-21:-1]
    mean=sum(past)/len(past) if past else 0
    multiple=round(volumes[-1]/mean,2) if mean else None
    alerts=[]
    if change is not None and abs(change)>=price_threshold:alerts.append('price')
    if multiple is not None and multiple>=volume_threshold:alerts.append('volume')
    return {'price_change_pct':change,'volume_multiple':multiple,'alerts':alerts}

def parse_number(s: str) -> float | None:
    try:return float(re.sub(r'[,₹\s]','',s).replace('(','-').replace(')',''))
    except (ValueError,TypeError):return None

def extract_guidance(text: str) -> list[dict]:
    """Find candidate sentences only; never claim guidance as verified facts."""
    result=[]
    for sentence in re.split(r'(?<=[.!?])\s+|\n',text):
        if 18<len(sentence)<450 and re.search(r'\b(expect|guidance|target|forecast|outlook|anticipat|aim to)\b',sentence,re.I):
            result.append({'statement':sentence.strip(),'review_status':'unverified — compare against reported results'})
    return result[:20]

def excerpt(text: str, limit:int=200)->str:
    clean=' '.join(text.split())
    return clean[:limit]+('…' if len(clean)>limit else '')
