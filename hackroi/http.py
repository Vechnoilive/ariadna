"""Локальный HTTP транспорт с ограничениями размера и едиными ошибками."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from .contracts import ProtocolError, canonical

MAX_BODY_BYTES = 65536


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Повторяющийся ключ JSON")
        result[key] = value
    return result


def parse_json(data):
    def invalid_constant(value):
        raise ValueError("Недопустимое число JSON: " + value)
    value = json.loads(data.decode("utf-8"), object_pairs_hook=_pairs, parse_constant=invalid_constant)
    canonical(value)
    return value


def make_server(application, host="127.0.0.1", port=0):
    class Handler(BaseHTTPRequestHandler):
        server_version = "Ariadna/0.1"

        def setup(self):
            super().setup()
            self.connection.settimeout(5.0)

        def log_message(self, *_args):
            pass

        def _reply(self, status, body):
            data = canonical(body).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Connection", "close")
            self.end_headers()
            try:
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError):
                pass
            self.close_connection = True

        def _handle(self):
            payload, request_id, episode_id = None, None, None
            try:
                path = urlsplit(self.path).path
                if self.command == "POST":
                    if self.headers.get("Transfer-Encoding"):
                        raise ProtocolError("INVALID_REQUEST", "Требуется Content-Length; chunked не поддерживается")
                    lengths = self.headers.get_all("Content-Length", [])
                    if len(lengths) != 1:
                        raise ProtocolError("INVALID_REQUEST", "Требуется единственный Content-Length", 411)
                    try:
                        length = int(lengths[0])
                    except ValueError as error:
                        raise ProtocolError("INVALID_REQUEST", "Некорректный Content-Length") from error
                    if length < 0 or length > MAX_BODY_BYTES:
                        raise ProtocolError("INVALID_REQUEST", "Превышен размер сообщения", 413)
                    if self.headers.get_content_type() != "application/json":
                        raise ProtocolError("INVALID_REQUEST", "Требуется application/json", 415)
                    data = self.rfile.read(length)
                    if len(data) != length:
                        raise ProtocolError("INVALID_REQUEST", "Неполное тело запроса")
                    try:
                        payload = parse_json(data)
                    except (ValueError, UnicodeError, RecursionError) as error:
                        raise ProtocolError("INVALID_REQUEST", "Некорректный JSON UTF-8") from error
                    if isinstance(payload, dict):
                        request_id, episode_id = payload.get("request_id"), payload.get("episode_id")
                        request_id = request_id if isinstance(request_id, str) else None
                        episode_id = episode_id if isinstance(episode_id, str) else None
                result = application.dispatch(self.command, path, payload)
                self._reply(200, result)
            except ProtocolError as error:
                application.record_error(error, request_id, episode_id)
                self._reply(error.status, error.payload(request_id, episode_id))
            except (TimeoutError, ConnectionError):
                error = ProtocolError("TIMEOUT", "Истекло время чтения запроса", 408)
                self._reply(error.status, error.payload(request_id, episode_id))
            except Exception:
                error = ProtocolError("INTERNAL_ERROR", "Внутренняя ошибка компонента", 500)
                self._reply(error.status, error.payload(request_id, episode_id))

        do_GET = _handle
        do_POST = _handle
        do_PUT = _handle
        do_DELETE = _handle
        do_PATCH = _handle
        do_HEAD = _handle
        do_OPTIONS = _handle
        do_TRACE = _handle

    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    return server


class EnvironmentApplication:
    def __init__(self, environment):
        self.environment = environment

    def dispatch(self, method, path, payload=None):
        routes = {
            "/v1/environment/health": ("GET", self.environment.health),
            "/v1/environment/capabilities": ("GET", self.environment.capabilities),
            "/v1/environment/observation": ("GET", self.environment.observation),
            "/v1/environment/logs": ("GET", self.environment.logs),
        }
        for operation in ("reset", "step", "close"):
            routes["/v1/environment/" + operation] = (
                "POST", lambda operation=operation: self.environment.mutate(operation, payload))
        if path not in routes:
            raise ProtocolError("INVALID_REQUEST", "Неизвестный маршрут", 404)
        required_method, function = routes[path]
        if method != required_method:
            raise ProtocolError("INVALID_REQUEST", "Метод не поддерживается для маршрута", 405)
        return function()

    def record_error(self, error, request_id, episode_id):
        try:
            with self.environment.lock:
                self.environment.journal.append({
                    "protocol_version": "1.0", "component": "environment", "kind": "error",
                    "record_id": f"env_{len(self.environment.journal.records):06d}",
                    "request_id": request_id, "episode_id": episode_id,
                    "error": error.payload(request_id, episode_id)["error"],
                })
        except OSError:
            pass


class ControllerApplication:
    def __init__(self, controller):
        self.controller = controller

    def dispatch(self, method, path, payload=None):
        if path != "/v1/controller/health":
            raise ProtocolError("INVALID_REQUEST", "Неизвестный маршрут", 404)
        if method != "GET":
            raise ProtocolError("INVALID_REQUEST", "Метод не поддерживается для маршрута", 405)
        return self.controller.health()

    def record_error(self, *_args):
        pass


def background_server(application):
    server = make_server(application)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread
