"""Исполнимый базовый профиль и экспорт JSON Schema без зависимостей."""

import copy
import json
import math
from pathlib import Path

OPERATIONS = ("keep", "select", "switch", "modify", "compose", "synthesize", "safe_stop")
AGENT_KINDS = (
    "aerial", "ground", "underground", "surface_water", "underwater",
    "infrastructure", "digital", "operator",
)
ERROR_CODES = (
    "INVALID_REQUEST", "UNSUPPORTED_PROTOCOL_VERSION", "UNKNOWN_EPISODE",
    "INVALID_COMMAND", "CONSTRAINT_VIOLATION", "INVALID_SCENARIO",
    "RESOURCE_EXHAUSTED", "TIMEOUT", "INTERNAL_ERROR",
)


def obj(properties=None, required=None, **extra):
    properties = properties or {}
    return {"type": "object", "properties": properties,
            "required": list(properties) if required is None else required, **extra}


def array(items=None, **extra):
    return {"type": "array", "items": items or {}, **extra}


def ref(name):
    return {"$ref": "#/$defs/" + name}


STRING = {"type": "string", "minLength": 1}
IDENTIFIER = {"type": "string", "minLength": 1, "maxLength": 128}
NUMBER = {"type": "number"}
UNIT = {"type": "number", "minimum": 0, "maximum": 1}
TIME = {"type": "number", "minimum": 0}
POSITION = array(NUMBER, minItems=3, maxItems=3)
VERSION = {"const": "1.0"}
ROLES = obj({}, [], additionalProperties={"type": "string", "minLength": 1})

DEFINITIONS = {
    "resource": obj({"id": IDENTIFIER, "value": UNIT, "minimum": UNIT,
                     "maximum": UNIT, "unit": STRING}),
    "action": obj({"action": STRING, "parameters_schema": {"type": "object"}}, ["action"]),
    "agent": obj({
        "id": IDENTIFIER, "kind": STRING,
        "position": {"anyOf": [POSITION, {"type": "null"}]},
        "status": {"enum": ["active", "degraded", "failed", "offline", "charging",
                             "busy", "safe_mode", "unknown"]},
        "capabilities": array(STRING, uniqueItems=True),
        "resources": obj({}, [], additionalProperties=ref("resource")),
        "communication": {"type": "object"},
        "role": {"type": ["string", "null"]},
        "scenario_ids": array(IDENTIFIER, uniqueItems=True),
        "available_actions": array(ref("action")), "constraints": array({"type": "object"}),
    }),
    "infrastructure": obj({
        "id": IDENTIFIER, "kind": STRING, "position": POSITION,
        "status": STRING, "capabilities": array(STRING), "resources": {"type": "object"},
        "communication": {"type": "object"}, "constraints": array({"type": "object"}),
    }),
    "zone": obj({
        "id": IDENTIFIER, "geometry": {"type": "object"}, "type": STRING,
        "access": {"type": "object"}, "risk": UNIT, "cost": {"type": "object"},
        "communication": {"type": "object"}, "constraints": array({"type": "object"}),
    }),
    "event": obj({
        "id": IDENTIFIER, "type": STRING, "time": TIME, "source": STRING,
        "targets": array(IDENTIFIER), "parameters": {"type": "object"},
        "confidence": UNIT, "status": {"enum": ["new", "active", "resolved", "expired"]},
    }),
    "mission": obj({
        "id": STRING, "objectives": array({"type": "object"}), "priorities": array(),
        "directives": array({"type": "object"}), "constraints": array({"type": "object"}),
        "status": {"enum": ["active", "completed", "failed", "suspended", "safe_stopped"]},
        "termination": {"type": "object"},
    }),
    "network": obj({
        "connectivity_score": UNIT, "partition_count": {"type": "integer", "minimum": 0},
        "reachable_agent_ratio": UNIT, "average_link_quality": UNIT,
        "mesh_available": {"type": "boolean"}, "known_links": array({"type": "object"}),
    }),
    "observation_quality": obj({
        "global_completeness": UNIT, "maximum_delay": TIME, "stale_data_ratio": UNIT,
        "contradiction_count": {"type": "integer", "minimum": 0}, "unknown_state_ratio": UNIT,
    }),
    "configuration": obj({"scenario_ids": array(IDENTIFIER, uniqueItems=True),
                          "role_assignments": ROLES}),
    "selected_configuration": obj({
        "scenario_ids": array(IDENTIFIER, uniqueItems=True), "parameters": {"type": "object"},
        "synthesized_scenario": {"type": ["object", "null"]},
    }),
    "candidate": obj({"scenario_id": IDENTIFIER, "applicable": {"type": "boolean"},
                      "utility": NUMBER, "risk": UNIT,
                      "rejected_reason_codes": array(STRING), "selected": {"type": "boolean"}},
                     ["scenario_id", "applicable"]),
    "command": obj({"agent_id": IDENTIFIER, "action": STRING, "parameters": {"type": "object"}}),
    "constraint_check": obj({"constraint_id": IDENTIFIER,
                             "status": {"enum": ["passed", "failed", "unknown"]}}),
    "explanation": obj({"observation_refs": array(STRING), "reason_codes": array(STRING),
                        "expected_effects": array(STRING), "confidence": UNIT}),
}

OBSERVATION = obj({
    "protocol_version": VERSION, "episode_id": IDENTIFIER, "request_id": IDENTIFIER,
    "time": TIME, "mission": ref("mission"), "agents": array(ref("agent")),
    "infrastructure": array(ref("infrastructure")), "targets": array({"type": "object"}),
    "zones": array(ref("zone")), "network": ref("network"), "events": array(ref("event")),
    "constraints": array({"type": "object"}), "metrics": {"type": "object"},
    "observation_quality": ref("observation_quality"),
})
DEFINITIONS["observation"] = OBSERVATION

RESET = obj({
    "protocol_version": VERSION, "request_id": IDENTIFIER,
    "seed": {"type": "integer", "minimum": 0, "maximum": 2**63 - 1},
    "mission": obj({"id": {"const": "search_and_rescue"}, "parameters": {"type": "object"}}),
})
DECISION = obj({
    "protocol_version": VERSION, "episode_id": IDENTIFIER, "request_id": IDENTIFIER,
    "decision_id": IDENTIFIER, "time": TIME, "operation": {"enum": list(OPERATIONS)},
    "previous_configuration": ref("configuration"),
    "selected_configuration": ref("selected_configuration"),
    "candidate_evaluations": array(ref("candidate")), "role_assignments": ROLES,
    "commands": array(ref("command"), maxItems=128),
    "constraint_checks": array(ref("constraint_check")), "explanation": ref("explanation"),
})
CLOSE = obj({"protocol_version": VERSION, "request_id": IDENTIFIER, "episode_id": IDENTIFIER})
RESPONSE = obj({
    "protocol_version": VERSION, "request_id": IDENTIFIER, "episode_id": IDENTIFIER,
    "time": TIME, "status": {"enum": ["running", "success", "failed", "safe_stopped", "time_limit"]},
    "observation": ref("observation"), "command_results": array({"type": "object"}),
    "events": array(ref("event")), "metrics": {"type": "object"},
})
RESET_RESPONSE = copy.deepcopy(RESPONSE)
RESET_RESPONSE['required'] = ['protocol_version', 'request_id', 'episode_id', 'time', 'status', 'observation']
ERROR = obj({
    "protocol_version": VERSION, "request_id": {"type": ["string", "null"]},
    "episode_id": {"type": ["string", "null"]},
    "error": obj({"code": {"enum": list(ERROR_CODES)}, "message": STRING, "details": {"type": "object"}}),
})
SCHEMAS = {"reset": RESET, "decision": DECISION, "close": CLOSE,
           "observation": OBSERVATION, "response": RESPONSE, "reset_response": RESET_RESPONSE, "error": ERROR}
ACTION_SCHEMAS = {
    "move": obj({"target": POSITION}, additionalProperties=False),
    "observe": obj({"target_id": IDENTIFIER}, additionalProperties=False),
    "deliver": obj({"target_id": IDENTIFIER}, additionalProperties=False),
    "charge": obj({"station_id": IDENTIFIER}, additionalProperties=False),
    "send_message": obj({"recipient_id": IDENTIFIER, "payload": {"type": "object"}}, additionalProperties=False),
    "relay": obj({}, additionalProperties=False),
}


class ProtocolError(Exception):
    def __init__(self, code, message, status=400, **details):
        super().__init__(message)
        self.code, self.message, self.status, self.details = code, message, status, details

    def payload(self, request_id=None, episode_id=None):
        return {"protocol_version": "1.0", "request_id": request_id, "episode_id": episode_id,
                "error": {"code": self.code, "message": self.message, "details": self.details}}


def canonical(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"))


def check(value, schema, path="$", definitions=None):
    """Проверка используемого подмножества JSON Schema 2020-12."""
    definitions = DEFINITIONS if definitions is None else definitions
    if "$ref" in schema:
        return check(value, definitions[schema["$ref"].removeprefix("#/$defs/")], path, definitions)
    if "anyOf" in schema:
        for option in schema["anyOf"]:
            try:
                check(value, option, path, definitions)
                return
            except ProtocolError:
                pass
        raise ProtocolError("INVALID_REQUEST", "Значение не соответствует схеме", path=path)
    if "const" in schema and (value != schema["const"] or type(value) is not type(schema["const"])):
        raise ProtocolError("INVALID_REQUEST", "Неверное постоянное значение", path=path)
    if "enum" in schema and value not in schema["enum"]:
        raise ProtocolError("INVALID_REQUEST", "Недопустимое значение", path=path)
    types = schema.get("type", [])
    types = [types] if isinstance(types, str) else types
    matches = {"object": isinstance(value, dict), "array": isinstance(value, list),
               "string": isinstance(value, str), "number": type(value) in (int, float),
               "integer": type(value) is int, "boolean": type(value) is bool, "null": value is None}
    if types and not any(matches[t] for t in types):
        raise ProtocolError("INVALID_REQUEST", "Неверный тип данных", path=path)
    if type(value) in (float, int):
        if isinstance(value, float) and not math.isfinite(value):
            raise ProtocolError("INVALID_REQUEST", "Ожидается конечное число", path=path)
        if "minimum" in schema and value < schema["minimum"]:
            raise ProtocolError("INVALID_REQUEST", "Значение меньше минимума", path=path)
        if "maximum" in schema and value > schema["maximum"]:
            raise ProtocolError("INVALID_REQUEST", "Значение больше максимума", path=path)
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0) or len(value) > schema.get("maxLength", math.inf):
            raise ProtocolError("INVALID_REQUEST", "Неверная длина строки", path=path)
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0) or len(value) > schema.get("maxItems", math.inf):
            raise ProtocolError("INVALID_REQUEST", "Неверная длина массива", path=path)
        if schema.get("uniqueItems") and len({canonical(x) for x in value}) != len(value):
            raise ProtocolError("INVALID_REQUEST", "Повторяющиеся элементы массива", path=path)
        for i, item in enumerate(value):
            check(item, schema.get("items", {}), f"{path}[{i}]", definitions)
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                raise ProtocolError("INVALID_REQUEST", "Отсутствует обязательное поле", path=f"{path}.{key}")
        properties = schema.get("properties", {})
        for key, item in value.items():
            if not isinstance(key, str):
                raise ProtocolError("INVALID_REQUEST", "Ключ объекта должен быть строкой", path=path)
            if key in properties:
                check(item, properties[key], f"{path}.{key}", definitions)
            else:
                additional = schema.get("additionalProperties", True)
                if additional is False:
                    raise ProtocolError("INVALID_REQUEST", "Неизвестный параметр действия", path=f"{path}.{key}")
                if isinstance(additional, dict):
                    check(item, additional, f"{path}.{key}", definitions)


def validate(name, value):
    if isinstance(value, dict) and "protocol_version" in value and value["protocol_version"] != "1.0":
        raise ProtocolError("UNSUPPORTED_PROTOCOL_VERSION", "Поддерживается версия протокола 1.0")
    check(value, SCHEMAS[name])
    if name in ("response", "reset_response"):
        validate("observation", value["observation"])
    if name == "observation":
        for agent in value["agents"]:
            for key, resource in agent["resources"].items():
                if not resource["minimum"] <= resource["value"] <= resource["maximum"]:
                    raise ProtocolError("INVALID_REQUEST", "Нарушены границы нормированного ресурса",
                                        agent_id=agent["id"], resource=key)


def exported_schemas():
    return {name + ".schema.json": {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "urn:ariadna:protocol:1.0:" + name,
        "title": "Ариадна базовый профиль " + name,
        **copy.deepcopy(schema), "$defs": copy.deepcopy(DEFINITIONS),
    } for name, schema in SCHEMAS.items()}


def export(directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    for filename, schema in exported_schemas().items():
        (directory / filename).write_text(json.dumps(schema, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
