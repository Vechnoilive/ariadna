"""Reject divergence between executable scenarios and their delivered declarations."""
import json
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from hackroi.scenarios import declarations

if __name__ == '__main__':
    actual = json.loads((ROOT/'scenarios/library.json').read_text(encoding='utf-8'))
    if actual != declarations():
        raise SystemExit('Scenario declarations differ from executable library')
    print('5 scenario declarations match executable library')
