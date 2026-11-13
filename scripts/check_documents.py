"""Check the current four documents, preserved video link and verification evidence."""
import hashlib
import json
from pathlib import Path
import re
import sys
import tomllib
import zipfile
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from hackroi import __version__
from scripts.build_documents import DATE, REVISION, DOCUMENTS


def check():
    media=ROOT/'submission'
    from pypdf import PdfReader
    from scripts.build_documents import PUBLIC_NAMES
    normalize=lambda value:' '.join(value.split())
    for source,stem,_,_ in DOCUMENTS:
        path=media/(PUBLIC_NAMES[stem]+'.pdf')
        assert path.read_bytes().startswith(b'%PDF-'),path.name
        reader=PdfReader(path)
        pages=[normalize(page.extract_text() or '') for page in reader.pages]
        text=' '.join(pages)
        for expected in (__version__, 'Заречкин Артём Алексеевич', 'Б24-507', DATE):
            assert expected in text,(path.name,expected)
        for heading in re.findall(r'^## (.+)$',(ROOT/'docs'/(source+'.md')).read_text(encoding='utf-8'),flags=re.M):
            assert normalize(heading) in text,(path.name,heading)
        for page in reader.pages:
            assert abs(float(page.mediabox.width)-595.28)<2 and abs(float(page.mediabox.height)-841.89)<2,path.name
        assert all(len(t)>30 for t in pages),(path.name,'empty page')
        assert '19 с' in text and ('31 с' in text or '31-й' in text),(path.name,'satellite pair')
    link=media/'Видео.txt'
    if link.exists():assert re.fullmatch(r'https://[^\s]+',link.read_text(encoding='utf-8').strip())
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
    presentation=media/'Презентация.pptx'
    return {'status':'passed','documents':4,'historical_runs':24,'cosmic_runs':2,'tests_reported':206,
            'revision':REVISION,'screencast':'included' if (media/'Скринкаст.mp4').is_file() else 'external_link' if link.is_file() else 'not_provided','presentation':'included' if presentation.is_file() else 'separate','external_teams_tested':0}
if __name__=='__main__':print(json.dumps(check(),ensure_ascii=False))
