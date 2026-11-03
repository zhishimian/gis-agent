"""Independent process test worker. All model replies are fixed and offline."""
import sys
import socket
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
socket.socket.connect=lambda *_: (_ for _ in ()).throw(AssertionError('offline worker'))
from langgraph.checkpoint.sqlite import SqliteSaver
from gis_agent.persistence.sessions import SessionStore
from gis_agent.tools.base import Tool
from test_v84 import build
from test_acceptance import reply

root=Path(sys.argv[1]);root.mkdir(exist_ok=True)
phase=sys.argv[2];store=SessionStore(root/'sessions','process')
prefix=root/'prefix.json';result=root/'result.json'
def prepare():
    if prefix.exists(): raise AssertionError('Prefix was recomputed')
    prefix.write_text(json.dumps({'value':6}))
    return {'ok':True,'outputs':{'prefix':str(prefix)}}
def calculate(factor):
    result.write_text(json.dumps({'value':json.loads(prefix.read_text())['value']*factor}))
    return {'ok':True,'outputs':{'result':str(result)}}
tools=(Tool('prepare','prefix',{'type':'object'},prepare),
       Tool('calculate','suffix',{'type':'object','properties':{'factor':{'type':'number'}}},calculate))
with SqliteSaver.from_conn_string(str(root/'checkpoint.sqlite')) as saver:
    responses=([reply('prepare','prepare',{}),reply('ask','finish_task',
                    {'status':'needs_input','summary':'Base value 6 saved; multiplier is missing.',
                     'question':'What multiplier should this task use? The final value depends on it.',
                     'reason':'missing_input','artifacts':[str(prefix)],'unresolved':['Multiplier and final value']})] if phase=='wait' else
               [reply('calc','calculate',{'factor':7}),reply('done','finish_task',
                    {'status':'completed','summary':'Result 42','artifacts':[str(result)]})])
    conv,calls=build(store,responses,saver,tools)
    if phase=='wait': outcome=conv.send('Compute prefix; ask for the missing factor.')
    else:
        assert conv.waiting
        outcome=conv.reply('Use factor 7 for this task',reply_id='factor-seven')
    (root/(phase+'.json')).write_text(json.dumps({'outcome':outcome,'responses':len(calls)}))
