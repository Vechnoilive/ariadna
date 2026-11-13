"""Publish the five authorable mission definitions as an offline, checked catalog."""
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from hackroi.custom_maps import campaign_map
from hackroi.physics import BODIES
from hackroi.landscapes import PROFILES,zones

def build():
    catalog=json.loads((ROOT/'scenarios/missions/catalog.json').read_text(encoding='utf-8'))
    deployments=json.loads((ROOT/'scenarios/campaign/deployments.json').read_text(encoding='utf-8'))
    assert len(catalog)==5 and len({x['id'] for x in catalog})==5
    for entry in catalog:
        entry['map']=campaign_map(json.loads((ROOT/'scenarios/missions'/entry.pop('file')).read_text(encoding='utf-8')), deployments)
    landscapes={name:zones(name,name) for name in PROFILES}
    (ROOT/'viewer/missions.js').write_text('window.ARIADNA_FIELD_BODIES='+json.dumps({k:{'min':[-r,-r,lo],'max':[r,r,hi],'clearance':.12} for k,(r,lo,hi) in BODIES.items()},separators=(',',':'))+';\nwindow.ARIADNA_LANDSCAPES='+json.dumps(landscapes,ensure_ascii=False,separators=(',',':'))+';\nwindow.ARIADNA_MISSIONS='+json.dumps(catalog,ensure_ascii=False,separators=(',',':'))+';\n',encoding='utf-8')
    return catalog
if __name__=='__main__':print('Published',len(build()),'missions')
