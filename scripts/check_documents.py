"""Check the current four documents, preserved video link and verification evidence."""
import hashlib
import json
from pathlib import Path
import re
import sys
import tomllib
import zipfile
from xml.etree import ElementTree as ET
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from hackroi import __version__
from scripts.build_documents import DATE, REVISION, DOCUMENTS
NS={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}


def check():
    media=ROOT/'submission'
    for name in ('explanatory_note','test_protocol','run_guide','essay'):
        with zipfile.ZipFile(media/(name+'.docx')) as archive:
            xml=ET.fromstring(archive.read('word/document.xml'))
            text=' '.join(xml.itertext())
            assert __version__ in text,(name,'version')
            assert 'Заречкин Артём Алексеевич' in text,(name,'author')
            assert 'Б24-507' in text,(name,'group')
            assert 'Листов' in text,(name,'sheet count')
            assert DATE in text,(name,'revision date')
            source=next(source for source,stem,_,_ in DOCUMENTS if stem==name)
            for heading in re.findall(r'^## (.+)$',(ROOT/'docs'/(source+'.md')).read_text(encoding='utf-8'),flags=re.M):
                assert heading in text,(name,'missing source section',heading)
            if name!='essay':assert 'двумер' in text.lower(),(name,'2D branches')
            assert '19 с' in text and ('31 с' in text or '31-й' in text),(name,'satellite pair')
            subject=ET.fromstring(archive.read('docProps/core.xml'))
            assert REVISION[8:]+'.'+REVISION[5:7]+'.'+REVISION[:4] in ''.join(subject.itertext()),(name,'metadata date')
            if name!='essay':assert 'Содержание' in text,(name,'contents')
            page=xml.find('.//w:pgSz',NS);assert page is not None
            assert abs(int(page.get('{'+NS['w']+'}w'))-11906)<=2
            assert abs(int(page.get('{'+NS['w']+'}h'))-16838)<=2
            margin=xml.find('.//w:pgMar',NS)
            for edge,value in [('left',1701),('right',850),('top',1134),('bottom',1134)]:
                assert abs(int(margin.get('{'+NS['w']+'}'+edge))-value)<=2,(name,edge)
        assert (media/(name+'.pdf')).read_bytes().startswith(b'%PDF-'),(name,'PDF')
    link=(media/'screencast').read_text(encoding='utf-8').strip()
    assert re.fullmatch(r'https://[^\s]+',link),'screencast must retain its external link'
    report=json.loads((ROOT/'experiments/results/verification_2026-11-12.json').read_text(encoding='utf-8'))
    assert report['program_version']==__version__
    assert report['tests']['status']=='passed' and report['tests']['run']==200
    assert len(report['results'])==24
    current=json.loads((ROOT/'experiments/results/verification_2026-11-13.json').read_text(encoding='utf-8'))
    assert current['program_version']==__version__ and current['revision']==REVISION
    assert json.loads((ROOT/'package.json').read_text())['version']==__version__
    assert tomllib.loads((ROOT/'pyproject.toml').read_text())['project']['version']==__version__
    assert current['tests']['status']=='passed' and current['tests']['run']==206
    assert current['historical_report_sha256']==hashlib.sha256((ROOT/'experiments/results/verification_2026-11-12.json').read_bytes()).hexdigest()
    for relative,digest in current['runtime_source_sha256'].items():
        assert hashlib.sha256((ROOT/relative).read_bytes()).hexdigest()==digest,('runtime changed',relative)
    evidence=media/'verification_evidence.zip'
    assert hashlib.sha256(evidence.read_bytes()).hexdigest()==report['evidence_sha256'],'verification ZIP digest'
    with zipfile.ZipFile(evidence) as archive:
        assert set(archive.namelist())==set(report['evidence_files']),'verification inventory'
        for name,digest in report['evidence_files'].items():
            assert hashlib.sha256(archive.read(name)).hexdigest()==digest,('verification source',name)
        assert archive.testzip() is None
        for row in report['results']:
            assert row['audit']=='passed'
            hashes=row.get('source_sha256',row.get('files',{}))
            for name,digest in hashes.items():
                assert hashlib.sha256(archive.read(row['evidence_prefix']+name)).hexdigest()==digest
    field=[r for r in report['results'] if r['domain']=='field']
    for mission in {r['mission'] for r in field}:
        assert len({r['map_sha256'] for r in field if r['mission']==mission})==1
    presentation=media/'defense.pptx'
    if presentation.is_file():
        with zipfile.ZipFile(presentation) as archive:
            slides=[n for n in archive.namelist() if re.fullmatch(r'ppt/slides/slide\d+\.xml',n)]
            assert len(slides)==12,'presentation slide count'
            slide_text=' '.join(' '.join(ET.fromstring(archive.read(n)).itertext()) for n in slides)
            for expected in ('206/206','24 + 2','ОРБИТАЛЬНЫЙ МОСТ','ДВУМЕРНЫЕ ВЕТВИ','110 м','75 м','31 с'):
                assert expected in slide_text,('presentation content',expected)
            assert archive.testzip() is None
    return {'status':'passed','documents':4,'historical_runs':24,'cosmic_runs':2,'tests_reported':206,
            'revision':REVISION,'screencast':'external_link','presentation':'included' if presentation.is_file() else 'separate','external_teams_tested':0}
if __name__=='__main__':print(json.dumps(check(),ensure_ascii=False))
