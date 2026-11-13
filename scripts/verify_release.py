"""Read-only validation of ZIP paths, inventory, CRC and SHA-256."""
import argparse
import json
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from hackroi.release import verify

if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive',type=Path)
    print(json.dumps(verify(parser.parse_args().archive),ensure_ascii=False,indent=2))
