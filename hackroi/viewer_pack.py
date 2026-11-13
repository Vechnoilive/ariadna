"""Small, deterministic offline trace packet; original JSONL remains the audit source."""
import base64
import gzip
import hashlib
import json
from pathlib import Path
from .showcase import validate_showcase

PREFIX='window.ARIADNA_PACK = '
LIMIT=64*1024*1024

def save(data,path):
    validate_showcase(data)
    return save_packet(data,path)

def save_packet(data,path,prefix=PREFIX):
    raw=json.dumps(data,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode()
    if len(raw)>LIMIT:raise ValueError('Viewer packet exceeds 64 MiB')
    value={'format':'ariadna.gzip.v1','bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),'data':base64.b64encode(gzip.compress(raw,compresslevel=9,mtime=0)).decode()}
    Path(path).write_text(prefix+json.dumps(value,separators=(',',':'))+';\n',encoding='utf-8')
    return value['sha256']

def read(path):
    source=Path(path).read_text(encoding='utf-8')
    if source.startswith('window.ARIADNA_DEMO = '):return validate_showcase(json.loads(source.removeprefix('window.ARIADNA_DEMO = ')[:-2]))
    return validate_showcase(read_packet(source))

def read_packet(source,prefix=PREFIX):
    if not source.startswith(prefix) or not source.endswith(';\n'):raise ValueError('Unknown viewer wrapper')
    packet=json.loads(source[len(prefix):-2])
    if packet.get('format')!='ariadna.gzip.v1' or not 0<packet['bytes']<=LIMIT:raise ValueError('Invalid viewer packet')
    import io
    with gzip.GzipFile(fileobj=io.BytesIO(base64.b64decode(packet['data'],validate=True))) as stream:raw=stream.read(LIMIT+1)
    if len(raw)!=packet['bytes'] or hashlib.sha256(raw).hexdigest()!=packet['sha256']:raise ValueError('Viewer packet digest mismatch')
    return json.loads(raw)
