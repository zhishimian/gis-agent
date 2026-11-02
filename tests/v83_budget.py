"""Explicit bounded live-test accounting; never used by the product Agent."""
import json
from datetime import datetime, timezone, timedelta
from time import perf_counter

from gis_agent.integrations.llm import chat, request_view
from gis_agent.persistence.json import write_json


class BudgetStop(RuntimeError):
    pass


def peak_time(now):
    return now.weekday() < 5 and (9 <= now.hour < 12 or 14 <= now.hour < 18)


class Budget:
    def __init__(self, client, model, path, *, threshold=1.7, max_calls=60, max_seconds=1200):
        if client.max_retries != 0:
            raise ValueError('Live tests require SDK retries=0')
        if model.provider != 'deepseek' or model.model != 'deepseek-flash' or str(client.base_url).rstrip('/') != 'https://api.deepseek.com':
            raise ValueError('Only the price-verified configured model is permitted')
        if model.supports_images or not 1 <= model.max_tokens <= 8192:
            raise ValueError('This guard requires text-only requests and bounded output')
        self.client, self.model, self.path = client, model, path
        old = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
        self.rows = old.get('rows', [])
        self.spent = old.get('peak_reserved_cny', 0.)
        self.estimated = old.get('usage_estimated_cny', 0.)
        self.stopped = old.get('stopped', False)
        self.phase_stops = old.get('phase_stops', [])
        self.threshold, self.max_calls, self.max_seconds = threshold, max_calls, max_seconds
        self.phase, self.phase_calls = '', 0
        self.started = perf_counter()

    def save(self):
        write_json(self.path, {'rows': self.rows, 'peak_reserved_cny': self.spent,
            'usage_estimated_cny': self.estimated, 'stopped': self.stopped,
            'phase_stops': self.phase_stops,
            'threshold_cny': self.threshold, 'authorized_cny': 2., 'sdk_retries': 0,
            'price_per_million_peak': {'hit': .04, 'miss': 2., 'output_including_reasoning': 8.},
            'pricing_source': 'https://api-docs.deepseek.com/zh-cn/quick_start/pricing/',
            'pricing_verified_date': '2026-11-02', 'max_output': self.model.max_tokens})

    def __call__(self, messages, schemas):
        now = datetime.now(timezone(timedelta(hours=8)))
        if (self.stopped or now.date().isoformat() != '2026-11-02' or len(self.rows) >= self.max_calls
            or self.phase_calls >= 30 or perf_counter()-self.started > self.max_seconds):
            self.stopped = True
            self.save()
            raise BudgetStop('Budget, date, call count or wall-clock stop')
        view, images = request_view(messages, self.model)
        if images:
            raise BudgetStop('Unpriced images prohibited')
        # UTF-8 bytes exceed text tokens; allow additional protocol overhead.
        upper_input = len(json.dumps({'messages':view,'tools':schemas},ensure_ascii=False).encode('utf-8')) + 16384 + 64*len(messages)
        upper = (upper_input * 2 + self.model.max_tokens * 8) / 1e6
        if upper_input > 160000 or self.spent + upper > self.threshold:
            self.stopped = True
            self.save()
            raise BudgetStop('Next request upper bound exceeds remaining conservative budget')
        row = {'phase':self.phase,'request':len(self.rows)+1,'input_upper':upper_input,
               'reserved_cny':upper,'state':'sending','time':now.isoformat()}
        self.rows.append(row)
        self.phase_calls += 1
        self.spent += upper
        self.save()  # unknown failures retain the entire reservation
        write_json(self.path.parent/'requests'/f'{len(self.rows):03d}.json',
                   {'messages':view,'tools':schemas,'max_output':self.model.max_tokens})
        started = perf_counter()
        try:
            reply = chat(self.client,self.model,messages,schemas)
            usage = reply.usage or {}
            hit = usage.get('prompt_cache_hit_tokens')
            miss = usage.get('prompt_cache_miss_tokens')
            n_input, n_output = usage.get('prompt_tokens'),usage.get('completion_tokens')
            if (any(type(v) is not int or v < 0 for v in (hit,miss,n_input,n_output)) or
                hit+miss != n_input or n_input > upper_input or n_output > self.model.max_tokens):
                raise BudgetStop('Usage cannot be reconciled with reserved bound')
            peak = (hit*.04 + miss*2 + n_output*8)/1e6
            end = datetime.now(timezone(timedelta(hours=8)))
            estimated = peak if peak_time(now) or peak_time(end) else peak/2
            self.spent += peak-upper
            self.estimated += estimated
            row.update(state='received',usage=usage,peak_cny=peak,estimated_cny=estimated,
                       model=reply.model,finish_reason=reply.finish_reason,
                       tools=[c['function']['name'] for c in (reply.message.get('tool_calls') or [])],
                       elapsed_seconds=perf_counter()-started)
            write_json(self.path.parent/'replies'/f'{len(self.rows):03d}.json',reply.message)
        except Exception as error:
            self.stopped = True
            row.update(state='error',error_type=type(error).__name__,elapsed_seconds=perf_counter()-started)
            self.save()
            raise
        self.save()
        return reply
