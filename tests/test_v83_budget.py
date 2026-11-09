import httpx
import pytest
from openai import OpenAI
from dataclasses import replace

from gis_agent.core.model import ModelConfig
from v83_budget import Budget, BudgetStop


@pytest.fixture(autouse=True)
def verified_price_date(monkeypatch):
    # Future offline runs must not depend on the live campaign's calendar date.
    import v83_budget
    from datetime import datetime
    class CampaignDate(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026,11,2,23,0,tzinfo=tz)
    monkeypatch.setattr(v83_budget,'datetime',CampaignDate)


def test_budget_reserves_before_sending_and_disables_retries(tmp_path):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(200,json={'id':'m','object':'chat.completion','model':'deepseek-flash',
          'choices':[{'index':0,'finish_reason':'stop','message':{'role':'assistant','content':'done'}}],
          'usage':{'prompt_tokens':10,'completion_tokens':5,'total_tokens':15,
                   'prompt_cache_hit_tokens':2,'prompt_cache_miss_tokens':8}})
    model = replace(ModelConfig(),supports_images=False,image_tokens=0,max_tokens=512)
    with OpenAI(api_key='offline',base_url='https://api.deepseek.com',max_retries=0,
                http_client=httpx.Client(transport=httpx.MockTransport(respond))) as client:
        blocked = Budget(client,model,tmp_path/'blocked.json',threshold=.00001)
        with pytest.raises(BudgetStop): blocked([{'role':'user','content':'x'}],[])
        assert len(requests)==0
        budget=Budget(client,model,tmp_path/'ok.json')
        budget([{'role':'user','content':'x'}],[])
        assert len(requests)==1 and budget.spent==pytest.approx((2*.04+8*2+5*8)/1e6)
        budget.spent=1.69
        with pytest.raises(BudgetStop): budget([{'role':'user','content':'x'}],[])
        assert len(requests)==1


def test_api_error_keeps_reservation_and_stops(tmp_path):
    requests=[]
    def respond(request):
        requests.append(request)
        return httpx.Response(500,json={'error':{'message':'offline failure'}})
    model=replace(ModelConfig(),supports_images=False,image_tokens=0,max_tokens=512)
    with OpenAI(api_key='offline',base_url='https://api.deepseek.com',max_retries=0,
                http_client=httpx.Client(transport=httpx.MockTransport(respond))) as client:
        budget=Budget(client,model,tmp_path/'error.json')
        with pytest.raises(Exception): budget([{'role':'user','content':'x'}],[])
        assert budget.stopped and budget.spent>0 and len(requests)==1
