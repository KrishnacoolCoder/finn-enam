import json
from datetime import datetime,timedelta,timezone

import pytest
import requests

from app import research,storage


@pytest.fixture
def database(tmp_path,monkeypatch):
    monkeypatch.setattr(storage,'DB',tmp_path/'fallback.sqlite3');storage.init()
    monkeypatch.delenv('GEMINI_API_KEY',raising=False)
    monkeypatch.delenv('GROQ_API_KEY',raising=False)
    monkeypatch.delenv('GROQ_MODEL',raising=False)
    research.ingest('TESTCO','results.txt',b'Revenue was INR 120 crore in FY2026. EBITDA was INR 30 crore in FY2026.')


def valid(*args):
    return {'insufficient_evidence':False,'claims':[{'source_id':1,'quote':args[-1][0]['text']}]}


def rate_limited(*args):
    response=requests.Response();response.status_code=429
    raise requests.HTTPError('PRIVATE_KEY_AND_TEXT',response=response)


def test_primary_success_does_not_call_groq(database,monkeypatch):
    monkeypatch.setenv('GEMINI_API_KEY','gemini-test');monkeypatch.setenv('GROQ_API_KEY','groq-test')
    monkeypatch.setattr(research,'gemini_generate',valid)
    def forbidden(*args):raise AssertionError('Backup must not be called')
    monkeypatch.setattr(research,'groq_generate',forbidden)
    answer=research.answer('TESTCO','What was revenue?')
    assert answer['mode']=='gemini_grounded' and answer['provider_failures']==[]


def test_rate_limit_falls_back_to_groq_with_safe_reason(database,monkeypatch):
    monkeypatch.setenv('GEMINI_API_KEY','gemini-test');monkeypatch.setenv('GROQ_API_KEY','groq-test')
    monkeypatch.setattr(research,'gemini_generate',rate_limited)
    monkeypatch.setattr(research,'groq_generate',valid)
    answer=research.answer('TESTCO','What was revenue?')
    assert answer['mode']=='groq_grounded' and '[results.txt, 1]' in answer['answer']
    assert answer['provider_failures']==[{'provider':'gemini','reason':'rate_limited','http_status':429}]
    assert 'PRIVATE' not in json.dumps(answer) and 'groq-test' not in json.dumps(answer)
    assert research.answer('TESTCO','What was revenue?')['cached']


def test_invalid_primary_evidence_uses_backup(database,monkeypatch):
    monkeypatch.setenv('GEMINI_API_KEY','gemini-test');monkeypatch.setenv('GROQ_API_KEY','groq-test')
    monkeypatch.setattr(research,'gemini_generate',lambda *args:{'insufficient_evidence':False,
        'claims':[{'source_id':1,'quote':'Revenue was INR 99999 crore in FY2026.'}]})
    monkeypatch.setattr(research,'groq_generate',valid)
    answer=research.answer('TESTCO','What was revenue?')
    assert answer['mode']=='groq_grounded' and '99999' not in answer['answer']
    assert answer['provider_failures'][0]['reason']=='invalid_evidence'


def test_insufficient_evidence_is_not_a_provider_failure(database,monkeypatch):
    monkeypatch.setenv('GEMINI_API_KEY','gemini-test');monkeypatch.setenv('GROQ_API_KEY','groq-test')
    monkeypatch.setattr(research,'gemini_generate',lambda *args:{'insufficient_evidence':True,'claims':[]})
    called=[];monkeypatch.setattr(research,'groq_generate',lambda *args:called.append(1))
    answer=research.answer('TESTCO','What was revenue?')
    assert answer['answer']=='insufficient evidence.' and not called


def test_both_fail_safe_extractive_and_no_raw_error(database,monkeypatch):
    monkeypatch.setenv('GEMINI_API_KEY','gemini-test');monkeypatch.setenv('GROQ_API_KEY','groq-test')
    monkeypatch.setattr(research,'gemini_generate',rate_limited)
    monkeypatch.setattr(research,'groq_generate',rate_limited)
    answer=research.answer('TESTCO','What was revenue?')
    assert answer['mode']=='extractive' and len(answer['provider_failures'])==2
    assert '[results.txt, 1]' in answer['answer'] and 'PRIVATE' not in json.dumps(answer)


def test_groq_only_and_key_rotation_bypass_previous_cache(database,monkeypatch):
    monkeypatch.setenv('GROQ_API_KEY','groq-test')
    calls=[]
    def generate(*args):calls.append(1);return valid(*args)
    monkeypatch.setattr(research,'groq_generate',generate)
    assert research.answer('TESTCO','What was revenue?')['mode']=='groq_grounded'
    assert research.answer('TESTCO','What was revenue?')['cached']
    monkeypatch.setenv('GROQ_API_KEY','rotated-key')
    assert not research.answer('TESTCO','What was revenue?')['cached'] and len(calls)==2
    monkeypatch.delenv('GROQ_API_KEY')
    assert research.answer('TESTCO','What was revenue?')['mode']=='extractive'


def test_backup_cache_expires_and_primary_recovers(database,monkeypatch):
    monkeypatch.setenv('GEMINI_API_KEY','gemini-test');monkeypatch.setenv('GROQ_API_KEY','groq-test')
    monkeypatch.setattr(research,'gemini_generate',rate_limited);monkeypatch.setattr(research,'groq_generate',valid)
    assert research.answer('TESTCO','What was revenue?')['mode']=='groq_grounded'
    with storage.connection() as db:
        db.execute('UPDATE research_answers SET created=?',((datetime.now(timezone.utc)-timedelta(seconds=61)).isoformat(),))
    monkeypatch.setattr(research,'gemini_generate',valid)
    assert research.answer('TESTCO','What was revenue?')['mode']=='gemini_grounded'


def test_retired_default_and_blank_model_migrate(database,monkeypatch):
    for value in ('llama-3.3-70b-versatile',''):
        monkeypatch.setenv('GROQ_MODEL',value)
        assert research.groq_model()=='openai/gpt-oss-120b'
    monkeypatch.setenv('GROQ_MODEL','openai/gpt-oss-20b')
    assert research.groq_model()=='openai/gpt-oss-20b'


@pytest.mark.parametrize('code,failures,expected_calls',[(200,0,1),(429,2,3),(401,1,1),(429,4,3)])
def test_groq_transport_json_retry_and_no_redirects(database,monkeypatch,code,failures,expected_calls):
    calls=[];sleeps=[]
    def post(url,**kwargs):
        assert url=='https://api.groq.com/openai/v1/chat/completions'
        assert kwargs['allow_redirects'] is False
        assert kwargs['json']['model']=='openai/gpt-oss-120b'
        assert kwargs['json']['response_format']=={'type':'json_object'}
        assert 'ONLY' in kwargs['json']['messages'][0]['content']
        calls.append(1)
        response=requests.Response();response.status_code=code if len(calls)<=failures else 200
        response._content=json.dumps({'choices':[{'message':{'content':json.dumps({'insufficient_evidence':True,'claims':[]})}}]}).encode()
        return response
    monkeypatch.setattr(requests,'post',post);monkeypatch.setattr(research.time,'sleep',sleeps.append)
    if failures>=3 or code==401:
        with pytest.raises(requests.HTTPError):research.groq_generate('groq-test','What was revenue?',[])
    else:assert research.groq_generate('groq-test','What was revenue?',[])['insufficient_evidence']
    assert len(calls)==expected_calls
    assert len(sleeps)==(2 if code==429 else 0)
