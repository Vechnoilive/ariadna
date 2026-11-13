"""Deterministic closed handoff archive with a strict inventory and SHA-256 checks."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import tomllib
import zipfile

FORMAT = 'ariadna.release.v1'
SOURCE_DIRS = ('hackroi', 'scripts', 'tests', 'interop', 'contracts', 'examples', 'scenarios', 'docs', 'experiments', 'viewer', '.github/workflows')
SOURCE_FILES = ('README.md', 'pyproject.toml', '.gitattributes', '.gitignore')
OPTIONAL_SOURCE_FILES = ('package.json', 'start.bat')
SUFFIXES = {'.py', '.json', '.jsonl', '.md', '.html', '.css', '.js', '.mjs', '.toml', '.yml', '.jpg', '.png', '.webp', '.gltf', '.glb'}
MEDIA_FILES = ('explanatory_note.docx', 'explanatory_note.pdf', 'test_protocol.docx', 'test_protocol.pdf', 'run_guide.docx', 'run_guide.pdf', 'essay.docx', 'essay.pdf', 'screencast')
ASSET_FILES = ('scene.png', 'flood.png', 'pressure.png', 'peer.png')
EXTRA_MEDIA = ('cosmic_evidence.zip', 'missions_evidence.zip', 'campaign_evidence.zip', 'verification_evidence.zip', 'defense.pptx', 'screencast.mp4', 'screencast.vtt')
MAX_FILES = 2000
MAX_BYTES = 256*1024*1024


def safe_name(name):
    path = PurePosixPath(name)
    if not name or '\\' in name or ':' in name or name.startswith('/') or any(part in ('', '.', '..') for part in name.split('/')) or path.is_absolute():
        raise ValueError('Unsafe archive path: '+name)
    return name


def source_files(root):
    root = Path(root).resolve()
    output = {}
    for name in SOURCE_FILES:
        path = root/name
        if not path.is_file() or path.is_symlink():
            raise ValueError('Missing or linked source: '+name)
        output[name] = path
    for name in OPTIONAL_SOURCE_FILES:
        path = root/name
        if path.exists():
            if not path.is_file() or path.is_symlink():
                raise ValueError('Invalid optional source: '+name)
            output[name] = path
    for directory in SOURCE_DIRS:
        for path in sorted((root/directory).rglob('*')):
            if '__pycache__' in path.parts or path.name == '__qa.html' or path.suffix not in SUFFIXES:
                continue
            if path.is_symlink():
                raise ValueError('Symlinks are not deliverables')
            if path.is_file():
                name = path.relative_to(root).as_posix()
                safe_name(name)
                output[name] = path
    return output


def build(root, output, media=None, evidence=None):
    root, output = Path(root).resolve(), Path(output).resolve()
    if output.exists():
        raise ValueError('Refusing to overwrite release')
    inputs = source_files(root)
    if media:
        media = Path(media).resolve()
        for name in MEDIA_FILES:
            path = media/name
            if not path.is_file() or path.is_symlink():
                raise ValueError('Missing final material: '+name)
            inputs['submission/'+name] = path
        for name in EXTRA_MEDIA:
            path=media/name
            if path.exists():
                if not path.is_file() or path.is_symlink():raise ValueError('Invalid extra document: '+name)
                inputs['submission/'+name]=path
        if (media/'assets').is_dir():
            for name in ASSET_FILES:
                path = media/'assets'/name
                if not path.is_file() or path.is_symlink():
                    raise ValueError('Missing or linked screenshot: '+name)
                inputs['submission/assets/'+name] = path
            for path in sorted((media/'assets').glob('*.png')):
                if path.is_symlink():raise ValueError('Linked screenshot')
                inputs['submission/assets/'+path.name]=path
    if evidence:
        path = Path(evidence).resolve()
        if path.is_symlink() or not path.is_file():
            raise ValueError('Missing evidence archive')
        inputs['submission/evidence.zip'] = path
    if len(inputs) > MAX_FILES or sum(p.stat().st_size for p in inputs.values()) > MAX_BYTES:
        raise ValueError('Release exceeds documented limits')
    files = {name: {'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'bytes': path.stat().st_size}
             for name, path in sorted(inputs.items())}
    version = tomllib.loads((root/'pyproject.toml').read_text(encoding='utf-8'))['project']['version']
    manifest = {'format': FORMAT, 'version': version, 'files': files,
                'material_status': {'documents': bool(media), 'screencast': bool(media), 'screencast_kind': ('file' if media and (media/'screencast.mp4').is_file() else 'external_link' if media else None), 'presentation': 'included' if media and (media/'defense.pptx').is_file() else 'separate', 'raw_evidence': bool(evidence)},
                'entrypoint': 'python scripts/start_local.py --open', 'reproduce': 'python scripts/run_stage6.py', 'offline_viewer': 'viewer/index.html',
                'external_teams_tested': 0, 'submission_channel': 'unconfirmed'}
    payload = (json.dumps(manifest, ensure_ascii=False, indent=2)+'\n').encode('utf-8')
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix+'.tmp')
    try:
        with zipfile.ZipFile(temporary, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for name, path in sorted(inputs.items()):
                data = path.read_bytes()
                if hashlib.sha256(data).hexdigest() != files[name]['sha256'] or len(data) != files[name]['bytes']:
                    raise ValueError('Source changed during packaging: '+name)
                info = zipfile.ZipInfo(name, (2026, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = (stat.S_IFREG | 0o644) << 16
                archive.writestr(info, data)
            info = zipfile.ZipInfo('MANIFEST.json', (2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, payload)
        with temporary.open('r+b') as stream:
            stream.flush(); os.fsync(stream.fileno())
        verify(temporary)
        temporary.replace(output)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return {'archive': str(output), 'sha256': hashlib.sha256(output.read_bytes()).hexdigest(), 'files': len(files), **manifest['material_status']}


def verify(path):
    with zipfile.ZipFile(path) as archive:
        members = archive.infolist()
        names = [i.filename for i in members]
        if len(names) > MAX_FILES+1 or len(names) != len(set(names)):
            raise ValueError('Too many or duplicate archive members')
        if sum(i.file_size for i in members) > MAX_BYTES:
            raise ValueError('Uncompressed archive exceeds limit')
        for item in members:
            safe_name(item.filename)
            if stat.S_ISLNK(item.external_attr >> 16):
                raise ValueError('Archive symlink rejected')
        manifest = json.loads(archive.read('MANIFEST.json'))
        if manifest.get('format') != FORMAT or not isinstance(manifest.get('files'), dict):
            raise ValueError('Unknown release manifest')
        if set(names) != set(manifest['files']) | {'MANIFEST.json'}:
            raise ValueError('Manifest inventory mismatch')
        for name, expected in manifest['files'].items():
            data = archive.read(name)
            if len(data) != expected['bytes'] or hashlib.sha256(data).hexdigest() != expected['sha256']:
                raise ValueError('Digest mismatch: '+name)
        if archive.testzip() is not None:
            raise ValueError('ZIP CRC mismatch')
    return {'status': 'passed', 'files': len(manifest['files']), 'version': manifest['version'], 'material_status': manifest['material_status']}
