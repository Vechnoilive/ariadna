"""Package explicitly inventoried source, final media and optional audited logs."""
import argparse
import json
import sys
import zipfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from hackroi.release import build

if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', required=True, type=Path)
    p.add_argument('--media', type=Path, help='Directory containing final documents, presentation, video link and evidence')
    p.add_argument('--evidence', type=Path, help='Evidence archive from run_stage6.py')
    p.add_argument('--manifest', type=Path, help='Copy the verified archive manifest to this repository path after packaging')
    args=p.parse_args()
    result=build(ROOT,args.output,args.media,args.evidence)
    if args.manifest:
        with zipfile.ZipFile(args.output) as archive:
            payload=archive.read('MANIFEST.json')
        args.manifest.write_bytes(payload)
        result['manifest']=str(args.manifest)
    print(json.dumps(result,ensure_ascii=False,indent=2))
