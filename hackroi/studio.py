"""Local authoring UI and bounded runner; agents and environment remain separate processes."""
import copy
import io
import json
import mimetypes
from pathlib import Path
import re
import subprocess
import threading
import time
import uuid
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit, unquote

from . import __version__
from .audit import audit, read_records
from .client import Client
from .contracts import ProtocolError, canonical
from .custom_maps import validate_map, fingerprint
from .showcase import FORMAT, episode, frame

ROOT = Path(__file__).resolve().parents[1]
MAX_REQUEST = 65536


class Studio:
    def __init__(self, output=None):
        self.output = Path(output or ROOT/'artifacts'/'studio').resolve()
        self.jobs = {}
        self.lock = threading.RLock()
        self.active = None
        self.closing = False
        self.workers = []
        self.children = set()

    def start(self, definition):
        definition = validate_map(definition)
        with self.lock:
            if self.closing or self.active is not None:
                raise ProtocolError('BUSY', 'Дождитесь завершения текущей миссии', 409)
            identifier = uuid.uuid4().hex
            job = {'id': identifier, 'state': 'running', 'phase':'simulation', 'title': definition['title'], 'map_sha256': fingerprint(definition), 'created': time.time(), 'frame': None, 'frames': [], 'environment_url': None}
            for key in list(self.jobs):
                if len(self.jobs) < 8:
                    break
                if self.jobs[key]['state'] != 'running':
                    self.jobs.pop(key)
            self.jobs[identifier] = job
            self.active = identifier
            worker = threading.Thread(target=self._execute, args=(job, definition), daemon=True)
            self.workers.append(worker)
            worker.start()
            return {'id': identifier, 'state': 'running', 'map_sha256': job['map_sha256']}

    def _execute(self, job, definition):
        from scripts.run_demo import Process
        environment = controller = None
        owned = []
        def track(component):
            owned.append(component.process)
            with self.lock:
                self.children.add(component.process)
                if self.closing:
                    component.process.terminate()
                    raise RuntimeError("Приложение закрывается")
        directory = self.output/job['id']
        try:
            directory.mkdir(parents=True)
            map_path = directory/'map.json'
            map_path.write_text(canonical(definition)+'\n', encoding='utf-8')
            environment = Process(['environment','--port','0','--map-file',str(map_path),'--log-path',str(directory/'environment.jsonl')])
            track(environment)
            url = environment.event('ready')['url']
            client = Client(url, timeout=5, max_response_bytes=64*1024*1024)
            capabilities = client.get('capabilities')
            with self.lock:
                job['environment_url'] = url
            controller = Process(['controller','--port','0','--portable','--decision-delay','0.18','--environment-url',url,'--seed',str(definition['seed']),'--max-decisions',str(definition['max_steps']+1),'--run-id','studio_'+job['map_sha256'][:20]+'_'+str(definition['seed']),'--log-path',str(directory/'controller.jsonl')])
            track(controller)
            controller.event('ready')
            summary = controller.event('episode_complete', timeout=300)
            env_records = client.get('logs')['records']
            controller.stop(); controller = None
            ctrl_records = read_records(directory/'controller.jsonl')
            with self.lock:job['phase']='checking'
            entry = episode('custom_'+job['id'],definition['title'],'Миссия на пользовательской карте',env_records,ctrl_records,capabilities,summary)
            summary['audit']=entry['audit']
            data = {'format': FORMAT, 'version': __version__, 'episodes': [entry], 'external_teams_tested': 0}
            (directory/'result.json').write_text(canonical(data)+'\n',encoding='utf-8')
            with self.lock:
                job.update(state='completed', result=data, summary=summary, frame=entry['frames'][-1], frames=entry['frames'])
        except Exception as error:
            with self.lock:
                job.update(state='failed', error=str(error)[:500])
        finally:
            if controller:
                controller.stop()
            if environment:
                environment.stop()
            with self.lock:
                job['environment_url'] = None
                self.children.difference_update(owned)
                self.active = None

    def status(self, identifier):
        with self.lock:
            job = self.jobs.get(identifier)
            if job is None:
                raise ProtocolError('NOT_FOUND','Миссия не найдена',404)
            url = job.get('environment_url') if job['state']=='running' else None
        if url:
            try:
                records = Client(url,timeout=3,max_response_bytes=64*1024*1024).get('logs')['records']
                frames = [frame(r['output']['observation']) for r in records if r.get('kind') in ('reset','step') and isinstance(r.get('output'),dict) and 'observation' in r['output']]
                with self.lock:
                    if job['state']=='running' and frames:
                        job['frame'] = frames[-1]
                        job['frames'] = frames
            except (ProtocolError, OSError):
                pass
        with self.lock:
            return copy.deepcopy({k:v for k,v in job.items() if k not in ('environment_url','created')})

    def archive(self, identifier):
        with self.lock:
            job = self.jobs.get(identifier)
            if not job or job['state']!='completed':
                raise ProtocolError('NOT_READY','Свидетельства доступны после завершения',409)
        result = io.BytesIO()
        with zipfile.ZipFile(result,'w',zipfile.ZIP_DEFLATED) as archive:
            for name in ('map.json','environment.jsonl','controller.jsonl','result.json'):
                archive.write(self.output/identifier/name,name)
        return result.getvalue()

    def close(self):
        with self.lock:
            self.closing = True
            children = list(self.children)
        for child in children:
            if child.poll() is None:
                child.terminate()
        for child in children:
            try:
                child.wait(timeout=4)
            except subprocess.TimeoutExpired:
                child.kill(); child.wait(timeout=3)
        for worker in self.workers:
            worker.join(timeout=5)


def make_studio_server(host='127.0.0.1', port=8080, output=None):
    studio = Studio(output)
    viewer = (ROOT/'viewer').resolve()
    class Handler(BaseHTTPRequestHandler):
        server_version = 'AriadnaStudio/'+__version__
        def log_message(self, *_args):
            pass
        def setup(self):
            super().setup();self.connection.settimeout(5)
        def reply(self, status, data, content_type='application/json; charset=utf-8'):
            payload = canonical(data).encode() if isinstance(data,dict) else data
            self.send_response(status)
            self.send_header('Content-Type',content_type)
            self.send_header('Content-Length',str(len(payload)))
            self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Cache-Control','no-store' if content_type.startswith('application/json') else 'no-cache')
            self.send_header('Connection','close')
            self.end_headers()
            try:self.wfile.write(payload)
            except (BrokenPipeError,ConnectionResetError):pass
        def do_GET(self):
            path = unquote(urlsplit(self.path).path)
            try:
                if path=='/api/studio/health':
                    return self.reply(200,{'status':'ready','version':__version__,'active':studio.active is not None,'active_job':studio.active})
                match = re.fullmatch(r'/api/studio/runs/([0-9a-f]{32})(/evidence.zip)?',path)
                if match:
                    return self.reply(200,studio.archive(match[1]) if match[2] else studio.status(match[1]),'application/zip' if match[2] else 'application/json; charset=utf-8')
                target = (viewer/(path.lstrip('/') or 'index.html')).resolve()
                if not target.is_relative_to(viewer) or not target.is_file() or any(p.startswith('.') for p in target.relative_to(viewer).parts):
                    return self.reply(404,{'error':'Файл не найден'})
                return self.reply(200,target.read_bytes(),mimetypes.guess_type(target.name)[0] or 'application/octet-stream')
            except ProtocolError as error:
                return self.reply(error.status,{'error':error.message})
        def do_POST(self):
            try:
                if urlsplit(self.path).path!='/api/studio/runs':
                    raise ProtocolError('NOT_FOUND','Маршрут не найден',404)
                origin = self.headers.get('Origin')
                if origin and origin != 'http://'+self.headers.get('Host','') and origin != 'https://'+self.headers.get('Host',''):
                    raise ProtocolError('FORBIDDEN','Требуется запрос с адреса приложения',403)
                if self.headers.get('Transfer-Encoding') or len(self.headers.get_all('Content-Length',[])) != 1:
                    raise ProtocolError('INVALID_REQUEST','Требуется Content-Length',411)
                try:length = int(self.headers['Content-Length'])
                except ValueError:raise ProtocolError('INVALID_REQUEST','Неверная длина',400)
                if not 0 < length <= MAX_REQUEST:
                    raise ProtocolError('INVALID_REQUEST','Лимит карты: 64 KiB',413)
                if self.headers.get_content_type()!='application/json':
                    raise ProtocolError('INVALID_REQUEST','Требуется application/json',415)
                from .http import parse_json
                try:value = parse_json(self.rfile.read(length))
                except (ValueError,UnicodeError):raise ProtocolError('INVALID_REQUEST','Некорректный JSON',400)
                return self.reply(202,studio.start(value))
            except ProtocolError as error:
                return self.reply(error.status,{'error':error.message})
            except (TimeoutError,ConnectionError):
                return self.reply(408,{'error':'Истекло время запроса'})
    server = ThreadingHTTPServer((host,port),Handler)
    server.daemon_threads = True
    server.studio = studio
    return server
