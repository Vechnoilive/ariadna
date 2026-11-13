"""Независимый HTTP клиент; изменяющие запросы автоматически не повторяются."""

from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from .contracts import ProtocolError, canonical
from .http import parse_json


class Client:
    def __init__(self, base_url, timeout=3.0, max_response_bytes=16*1024*1024):
        parsed = urlsplit(base_url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc or parsed.query or parsed.fragment:
            raise ValueError("Ожидается базовый URL HTTP или HTTPS без query и fragment")
        if type(timeout) not in (int,float) or not 0 < timeout <= 60:
            raise ValueError("timeout должен быть от 0 до 60 секунд")
        if type(max_response_bytes) is not int or not 1024 <= max_response_bytes <= 64*1024*1024:
            raise ValueError("Неверный предел ответа")
        self.max_response_bytes = max_response_bytes
        self.base_url, self.timeout = base_url.rstrip("/"), timeout

    def request(self, method, path, payload=None):
        data = canonical(payload).encode("utf-8") if payload is not None else None
        headers = {"Content-Type": "application/json; charset=utf-8"} if data is not None else {}
        request = Request(self.base_url + path, data=data, headers=headers, method=method)
        try:
            with urlopen(request, timeout=self.timeout) as response:
                data = response.read(self.max_response_bytes+1)
                if len(data)>self.max_response_bytes:
                    raise ProtocolError("INVALID_REQUEST", "Ответ превышает ограничение клиента", 502)
                if response.headers.get_content_type() != "application/json":
                    raise ProtocolError("INVALID_REQUEST", "Ответ среды не имеет типа application/json", 502)
                try:
                    return parse_json(data)
                except (ValueError, UnicodeError, RecursionError) as error:
                    raise ProtocolError("INVALID_REQUEST", "Среда вернула некорректный JSON UTF-8", 502) from error
        except HTTPError as error:
            try:
                data = error.read(self.max_response_bytes+1)
                if len(data)>self.max_response_bytes:raise ValueError("Слишком большой ответ ошибки")
                value = parse_json(data)
            except (ValueError, UnicodeError, RecursionError) as parse_error:
                raise ProtocolError("INVALID_REQUEST", "Среда вернула не JSON", 502) from parse_error
            details = value.get("error", {}) if isinstance(value, dict) else {}
            if not isinstance(details, dict) or not isinstance(details.get("details", {}), dict):
                raise ProtocolError("INVALID_REQUEST", "Некорректный объект ошибки среды", 502) from error
            raise ProtocolError(details.get("code", "INTERNAL_ERROR"),
                                details.get("message", "HTTP ошибка среды"), error.code,
                                **details.get("details", {})) from error
        except (TimeoutError, URLError) as error:
            raise ProtocolError("TIMEOUT", "Среда недоступна или не ответила вовремя", 504) from error

    def get(self, operation):
        return self.request("GET", "/v1/environment/" + operation)

    def post(self, operation, payload):
        return self.request("POST", "/v1/environment/" + operation, payload)
