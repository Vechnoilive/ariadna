"""Read-only validation of ZIP paths, inventory, CRC and SHA-256."""
import argparse
import hashlib
import json
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from hackroi.release import verify
from hackroi.release import FORMAT, safe_name


def verify_manifest(path):
    manifest=json.loads(path.read_text(encoding='utf-8'))
    if manifest.get('format')!=FORMAT or not manifest.get('files'):
        raise ValueError('Unknown or empty release manifest')
    for name,expected in manifest['files'].items():
        safe_name(name)
        target=path.parent/name
        if target.is_symlink() or not target.is_file():
            raise ValueError('Missing or linked material: '+name)
        data=target.read_bytes()
        if len(data)!=expected['bytes'] or hashlib.sha256(data).hexdigest()!=expected['sha256']:
            raise ValueError('Digest mismatch: '+name)
    return {'status':'passed','files':len(manifest['files']),'version':manifest['version'],
            'material_status':manifest['material_status']}

if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive',type=Path,nargs='?')
    parser.add_argument('--manifest',type=Path,help='Verify byte counts and SHA-256 of a repository manifest')
    args=parser.parse_args()
    if bool(args.archive)==bool(args.manifest):parser.error('Provide either an archive or --manifest')
    print(json.dumps(verify(args.archive) if args.archive else verify_manifest(args.manifest),ensure_ascii=False,indent=2))
