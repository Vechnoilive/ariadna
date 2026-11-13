"""Offline own-world alternative futures; never a tournament HTTP endpoint."""
import argparse
import json
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from hackroi.research import branch

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--environment-log', required=True, type=Path)
    parser.add_argument('--controller-log', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--decision-id')
    parser.add_argument('--horizon', type=int, default=6)
    parser.add_argument('--map', dest='map_path', type=Path, help='Original map.json for an authored episode')
    args = parser.parse_args()
    definition=json.loads(args.map_path.read_text(encoding='utf-8')) if args.map_path else None
    print(json.dumps(branch(args.environment_log, args.controller_log, args.output, args.decision_id, args.horizon, map_definition=definition), ensure_ascii=False, indent=2))
