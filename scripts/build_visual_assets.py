"""Embed local generated JPEG materials for file:// WebGL texture loading."""
import base64
import hashlib
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def build():
    textures={}
    inventory={}
    for name in ('grass','stone','bark','sand','snow','concrete'):
        source=ROOT/'viewer'/'assets'/(name+'.jpg')
        raw=source.read_bytes()
        textures[name]='data:image/jpeg;base64,'+base64.b64encode(raw).decode()
        inventory[name]={'file':'assets/'+name+'.jpg','sha256':hashlib.sha256(raw).hexdigest()}
    (ROOT/'viewer'/'textures.js').write_text('window.ARIADNA_TEXTURES='+json.dumps(textures,separators=(',',':'))+';\n',encoding='utf-8')
    (ROOT/'viewer'/'assets'/'manifest.json').write_text(json.dumps(inventory,indent=2)+'\n',encoding='utf-8')
    return inventory

if __name__=='__main__':print(json.dumps(build(),indent=2))
