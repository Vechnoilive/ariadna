"""Сравнение контрольных алгоритмов по публичному HTTP API."""
import argparse
import json
import sys
import uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from hackroi.baselines import FixedController,ReactiveController
from hackroi.audit import audit,read_records
from scripts.run_demo import Process


def run(seed=42,output=None):
    output=Path(output).resolve() if output else ROOT/'artifacts'/('stage2_'+uuid.uuid4().hex[:10])
    output.mkdir(parents=True,exist_ok=True)
    if any(output.iterdir()):raise ValueError('Нужен пустой каталог результатов')
    summaries=[]
    for kind,cls in [('fixed',FixedController),('reactive',ReactiveController)]:
        directory=output/kind;directory.mkdir()
        environment=Process(['environment','--port','0','--log-path',str(directory/'environment.jsonl')])
        try:
            url=environment.event('ready')['url']
            controller=cls(directory/'controller.jsonl')
            summary=controller.run(url,seed,100,run_id='stage2_'+str(seed))
            report=audit(read_records(directory/'environment.jsonl'),read_records(directory/'controller.jsonl'))
            summaries.append({'controller':kind,**summary,'audit':report})
            observations=[r['output']['observation'] for r in read_records(directory/'environment.jsonl') if r['kind'] in ('reset','step')]
            (directory/'replay.json').write_text(json.dumps(observations,ensure_ascii=False),encoding='utf-8')
        finally:environment.stop()
    result={'seed':seed,'results':summaries,'output_directory':str(output)}
    (output/'summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return result

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--seed',type=int,default=42);parser.add_argument('--output',type=Path)
    args=parser.parse_args();print(json.dumps(run(args.seed,args.output),ensure_ascii=False,indent=2))
