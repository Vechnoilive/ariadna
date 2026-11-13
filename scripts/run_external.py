"""Run the portable controller against an explicitly supplied environment URL."""
import argparse
import json
import sys
import uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from hackroi.client import Client
from hackroi.contracts import ProtocolError
from hackroi.portable import PortableController


def run(url,output=None,seed=42,parameters=None,timeout=3.,max_decisions=200):
    if type(max_decisions) is not int or not 1<=max_decisions<=1000:raise ValueError('max_decisions: 1..1000')
    output=Path(output).resolve() if output else ROOT/'artifacts'/('external_'+uuid.uuid4().hex[:10])
    output.mkdir(parents=True,exist_ok=True)
    if any(output.iterdir()):raise ValueError('Нужен пустой каталог результатов')
    if parameters is not None and not isinstance(parameters,dict):raise ValueError('Параметры миссии должны быть JSON-объектом')
    controller=PortableController(output/'controller.jsonl');controller.client_timeout=timeout
    if parameters is not None:controller.mission_parameters={**controller.mission_parameters,**parameters}
    health=None
    try:
        health=Client(url,timeout).get('health')
        if health.get('status')!='ready' or health.get('protocol_version')!='1.0':raise ProtocolError('UNSUPPORTED_PROTOCOL_VERSION','Среда не готова или версия не 1.0')
        result=controller.run(url,seed,max_decisions)
        report={'status':'completed','environment_health':health,'episode':result,
                'scope':'Actual supplied endpoint; mission outcome is reported separately from transport compatibility.',
                'compatibility':{'transport':'passed','protocol':'passed','mission':result['status'],'requires_attention':result['status']!='success'}}
    except ProtocolError as error:
        report={'status':'error','environment_health':health,'error':{'code':error.code,'message':error.message},
                'scope':'No automatic POST retry; inspect logs before starting a new episode.'}
    (output/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--url',required=True);p.add_argument('--output',type=Path);p.add_argument('--seed',type=int,default=42)
    p.add_argument('--parameters',type=Path);p.add_argument('--timeout',type=float,default=3.);p.add_argument('--max-decisions',type=int,default=200)
    a=p.parse_args();parameters=json.loads(a.parameters.read_text(encoding='utf-8')) if a.parameters else None
    print(json.dumps(run(a.url,a.output,a.seed,parameters,a.timeout,a.max_decisions),ensure_ascii=False,indent=2))
