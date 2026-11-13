"""Package explicitly inventoried source, final media and optional audited logs."""
import argparse
import json
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from hackroi.release import build

if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', required=True, type=Path)
    p.add_argument('--media', type=Path, help='Directory containing all five final Office/PDF/video files')
    p.add_argument('--evidence', type=Path, help='Evidence archive from run_stage6.py')
    args=p.parse_args()
    print(json.dumps(build(ROOT,args.output,args.media,args.evidence),ensure_ascii=False,indent=2))
