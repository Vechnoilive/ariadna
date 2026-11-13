"""Минимальная непрерывная среда для проверки публичного контракта."""

import copy
import hashlib
import math
import random
import threading

from .contracts import (
    ACTION_SCHEMAS, AGENT_KINDS, OPERATIONS, ProtocolError, canonical, check, validate,
)
from .journal import Journal

DT = 1.0
SPEED = 5.0
ENERGY_PER_METRE = 0.002
MAX_REQUESTS = 2048
BOUNDS = ([0.0, 0.0, 0.0], [100.0, 100.0, 30.0])
RESTRICTED = ([80.0, 80.0, 0.0], [90.0, 90.0, 30.0])


def intersects_box(start, end, lower, upper):
    low, high = 0.0, 1.0
    for a, b, lo, hi in zip(start, end, lower, upper):
        delta = b - a
        if abs(delta) < 1e-12:
            if not lo <= a <= hi:
                return False
        else:
            near, far = sorted(((lo - a) / delta, (hi - a) / delta))
            low, high = max(low, near), min(high, far)
            if low > high:
                return False
    return True


def closest_distance(a0, a1, b0, b1):
    relative = [a - b for a, b in zip(a0, b0)]
    velocity = [(a - old_a) - (b - old_b) for a, old_a, b, old_b in zip(a1, a0, b1, b0)]
    length = sum(v * v for v in velocity)
    t = max(0.0, min(1.0, -sum(a * v for a, v in zip(relative, velocity)) / length)) if length else 0.0
    return math.sqrt(sum((a + t * v) ** 2 for a, v in zip(relative, velocity)))


def energy(value=1.0):
    return {"energy": {"id": "energy", "value": value, "minimum": 0.15,
                       "maximum": 1.0, "unit": "normalized"}}


def agent(identifier, kind, position, actions):
    return {
        "id": identifier, "kind": kind, "position": position, "status": "active",
        "capabilities": (["move", "sense"] if actions else ["compute"]),
        "resources": energy(), "communication": {"connected": True, "quality": 1.0},
        "role": None, "scenario_ids": [],
        "available_actions": [{"action": a, "parameters_schema": copy.deepcopy(ACTION_SCHEMAS[a])}
                              for a in actions], "constraints": [],
    }


class Environment:
    def __init__(self, log_path=None, map_definition=None):
        from .custom_maps import validate_map
        self.map_definition = validate_map(map_definition) if map_definition is not None else None
        self.lock = threading.RLock()
        self.journal = Journal(log_path)
        self.state = None
        self.cache = {}

    def health(self):
        return {"protocol_version": "1.0", "component": "environment", "status": "ready",
                "environment_id": "ariadna", "capabilities_url": "/v1/environment/capabilities"}

    def capabilities(self):
        from .compute import KINDS, declaration
        return {
            "protocol_version": "1.0", "environment_id": "ariadna",
            "profile": "ariadna.stage1.v1", "agent_kinds": list(AGENT_KINDS),
            "implemented_dynamics": list(AGENT_KINDS),
            "infrastructure_kinds": list(KINDS), "compute_service": declaration(),
            "profiles": ["ariadna.stage1.v1", "rescue_v2"],
            "operations": list(OPERATIONS),
            "actions": [{"action": a, "parameters_schema": copy.deepcopy(s)}
                        for a, s in ACTION_SCHEMAS.items()],
            "zone_types": ["air", "land", "water", "underground", "obstacle", "hazard", "restricted", "limited_access", "low_connectivity", "infrastructure"],
            "geometry_types": ["axis_aligned_box"], "dt_seconds": DT,
            "units": {"position": "metre", "time": "second"},
            "extensions": ["ariadna.stage1.v1", "ariadna.rescue.v2", "ariadna.cosmic.v1", "ariadna.motion.v1", "ariadna.energy.v1", "ariadna.compute.v1"]
                          + (["ariadna.home.v1"] if (self.map_definition or {}).get("format") == "ariadna.home.v1" else []),
            "extension_agent_kinds": {"ariadna.cosmic.v1": ["cosmic"]},
            "limits": {"max_body_bytes": 65536, "max_mutating_requests": MAX_REQUESTS},
            "execution_semantics": {"batch": "atomic", "configuration": "atomic"},
            "reset_parameters": ["profile", "max_steps", "events", "link_range", "message_loss", "include_cosmic", "include_compute_node", "layout", "cohorts", "targets_per_kind"],
            "layouts": ["standard", "floodplain"],
            "scenario_ownership": "controller", "mesh_available": True,
            "pending_clarifications": ["cosmic_agent_kind", "complete_organizer_json_schema"],
        }

    def _current(self, episode_id=None):
        if self.state is None or (episode_id is not None and episode_id != self.state["episode_id"]):
            raise ProtocolError("UNKNOWN_EPISODE", "Активный эпизод не найден", 404)
        return self.state

    def observation(self):
        with self.lock:
            return self._observation(self._current())

    def _observation(self, state):
        result = {k: copy.deepcopy(state[k]) for k in (
            "episode_id", "request_id", "time", "mission", "agents", "infrastructure",
            "targets", "zones", "network", "events", "constraints", "metrics", "observation_quality",
        )}
        if state.get("profile") == "rescue_v2":
            result["targets"] = [t for t in result["targets"] if t["id"] in state["discovered"]]
            result["network"]["messages"] = copy.deepcopy(state["delivered_messages"])
            result["metrics"]["current_configuration"] = copy.deepcopy(state["configuration"])
        result["protocol_version"] = "1.0"
        return result

    def _response(self, state, results=None):
        return {"protocol_version": "1.0", "request_id": state["request_id"],
                "episode_id": state["episode_id"], "time": state["time"], "status": state["status"],
                "observation": self._observation(state), "command_results": results or [],
                "events": copy.deepcopy(state["events"]), "metrics": copy.deepcopy(state["metrics"])}

    def mutate(self, route, payload):
        with self.lock:
            validate({"reset": "reset", "step": "decision", "close": "close"}[route], payload)
            request_id = payload["request_id"]
            digest = hashlib.sha256((route + canonical(payload)).encode()).hexdigest()
            if request_id in self.cache:
                old_digest, response = self.cache[request_id]
                if old_digest != digest:
                    raise ProtocolError("INVALID_REQUEST", "request_id уже использован для другого запроса", 409)
                return copy.deepcopy(response)
            if len(self.cache) >= MAX_REQUESTS:
                raise ProtocolError("RESOURCE_EXHAUSTED", "Исчерпан журнал идемпотентных запросов; перезапустите процесс", 429)
            if route == "reset":
                next_state, results = self._reset(payload), []
            elif route == "step":
                next_state, results = self._step(payload)
            else:
                next_state = copy.deepcopy(self._current(payload["episode_id"]))
                next_state["request_id"] = request_id
                next_state["closed"] = True
                if next_state["status"] == "running":
                    next_state["status"] = "safe_stopped"
                    next_state["mission"]["status"] = "safe_stopped"
                results = []
            response = self._response(next_state, results)
            validate("reset_response" if route == "reset" else "response", response)
            record = {"protocol_version": "1.0", "component": "environment",
                      "record_id": f"env_{len(self.journal.records):06d}", "kind": route,
                      "episode_id": next_state["episode_id"], "request_id": request_id,
                      "decision_id": payload.get("decision_id"), "time": next_state["time"],
                      "input": copy.deepcopy(payload), "output": copy.deepcopy(response)}
            self.journal.append(record)
            self.state = next_state
            self.cache[request_id] = (digest, copy.deepcopy(response))
            return response

    def _reset(self, request):
        if self.map_definition is not None:
            request = copy.deepcopy(request)
            request['mission']['parameters'].update(profile='rescue_v2', layout='custom', custom_map=copy.deepcopy(self.map_definition), max_steps=self.map_definition['max_steps'])
        parameters = request["mission"]["parameters"]
        max_steps = parameters.get("max_steps", 40)
        if type(max_steps) is not int or not 1 <= max_steps <= 1000:
            raise ProtocolError("INVALID_REQUEST", "max_steps должен быть целым от 1 до 1000")
        rng = random.Random(request["seed"])
        target = [float(rng.randint(25, 35)), float(rng.randint(25, 35)), 10.0]
        episode = "episode_" + hashlib.sha256(canonical(request).encode()).hexdigest()[:16]
        infrastructure = []
        for i, kind in enumerate(["relay", "charging_station", "sensor_node", "base_station"]):
            infrastructure.append({"id": "infra_" + str(i), "kind": kind,
                                   "position": [float(i * 2), 0.0, 0.0], "status": "active",
                                   "capabilities": [], "resources": {},
                                   "communication": {"connected": True, "quality": 1.0}, "constraints": []})
        def zone(identifier, kind, lower, upper, access):
            return {"id": identifier, "type": kind,
                    "geometry": {"type": "axis_aligned_box", "min": lower, "max": upper},
                    "access": access, "risk": 0.0, "cost": {"energy": 1.0, "time": 1.0},
                    "communication": {}, "constraints": []}
        state = {
            "episode_id": episode, "request_id": request["request_id"], "time": 0.0,
            "step_count": 0, "max_steps": max_steps, "closed": False, "status": "running",
            "configuration": {"scenario_ids": [], "role_assignments": {}}, "parameters": {},
            "decision_ids": set(),
            "mission": {"id": "search_and_rescue", "objectives": [{"id": "confirm_target",
                        "type": "confirm", "priority": 1.0, "status": "pending", "target_id": "target_1"}],
                        "priorities": ["confirm", "safety"], "directives": [], "constraints": [],
                        "status": "active", "termination": {"time_limit": max_steps * DT}},
            "agents": [agent("scout_A", "aerial", [5.0, 5.0, 10.0], ["move", "observe"]),
                       agent("carrier_B", "ground", [5.0, 5.0, 0.0], ["move", "observe"]),
                       agent("compute_C", "digital", None, [])],
            "infrastructure": infrastructure,
            "targets": [{"id": "target_1", "position": target, "status": "unconfirmed", "priority": 1.0}],
            "zones": [zone("world", "air", *copy.deepcopy(BOUNDS), {"aerial": True}),
                      zone("surface", "land", [0.0, 0.0, 0.0], [100.0, 100.0, 0.0], {"ground": True}),
                      zone("restricted_1", "restricted", *copy.deepcopy(RESTRICTED), {"all": False})],
            "network": {"connectivity_score": 1.0, "partition_count": 0,
                        "reachable_agent_ratio": 1.0, "average_link_quality": 1.0,
                        "mesh_available": False, "known_links": []},
            "events": [], "constraints": [{"id": "energy_reserve", "minimum": 0.15},
                                         {"id": "bounds", "min": BOUNDS[0], "max": BOUNDS[1]},
                                         {"id": "restricted_1", "type": "forbidden_zone"},
                                         {"id": "collision_distance", "minimum_metres": 0.5}],
            "metrics": {"mission_completion": 0.0, "energy_used": 0.0, "step_count": 0},
            "observation_quality": {"global_completeness": 1.0, "maximum_delay": 0.0,
                                    "stale_data_ratio": 0.0, "contradiction_count": 0,
                                    "unknown_state_ratio": 0.0},
        }

        profile = parameters.get("profile", "ariadna.stage1.v1")
        if profile == "rescue_v2":
            from .simulation import initialize
            initialize(state, request)
        elif profile != "ariadna.stage1.v1":
            raise ProtocolError("INVALID_REQUEST", "Неизвестный профиль среды")
        return state

    def _step(self, decision):
        state = self._current(decision["episode_id"])
        if state["closed"] or state["status"] != "running":
            raise ProtocolError("INVALID_REQUEST", "Эпизод завершён; выполните reset", 409)
        if decision["time"] != state["time"]:
            raise ProtocolError("INVALID_REQUEST", "Решение основано на устаревшем времени", 409,
                                expected_time=state["time"])
        if decision["decision_id"] in state["decision_ids"]:
            raise ProtocolError("INVALID_REQUEST", "decision_id уже исполнен", 409)
        if decision["previous_configuration"] != state["configuration"]:
            raise ProtocolError("INVALID_SCENARIO", "Предыдущая конфигурация не совпадает с текущей", 409)
        selected = decision["selected_configuration"]
        ids = selected["scenario_ids"]
        operation = decision["operation"]
        if not ids and operation != "safe_stop":
            raise ProtocolError("INVALID_SCENARIO", "Для операции требуется сценарий", 422)
        if operation == "select" and state["configuration"]["scenario_ids"]:
            raise ProtocolError("INVALID_SCENARIO", "select допустим при отсутствии активной конфигурации", 422)
        if operation in ("keep", "modify") and ids != state["configuration"]["scenario_ids"]:
            raise ProtocolError("INVALID_SCENARIO", "keep и modify сохраняют идентификаторы сценариев", 422)
        if operation == "keep" and (selected["parameters"] != state["parameters"] or
                                    decision["role_assignments"] != state["configuration"]["role_assignments"]):
            raise ProtocolError("INVALID_SCENARIO", "keep сохраняет параметры и роли", 422)
        if operation == "compose" and len(ids) < 2:
            raise ProtocolError("INVALID_SCENARIO", "compose требует минимум два сценария", 422)
        if operation == "switch" and (ids == state["configuration"]["scenario_ids"] and
                                      selected["parameters"] == state["parameters"] and
                                      decision["role_assignments"] == state["configuration"]["role_assignments"]):
            raise ProtocolError("INVALID_SCENARIO", "switch должен изменять конфигурацию", 422)
        if operation == "modify" and selected["parameters"] == state["parameters"]:
            raise ProtocolError("INVALID_SCENARIO", "modify должен изменять параметры", 422)
        if operation == "synthesize":
            definition = selected["synthesized_scenario"]
            if not definition or definition.get("id") not in ids or not isinstance(definition.get("graph"), dict):
                raise ProtocolError("INVALID_SCENARIO", "Для synthesize нужна декларация id и graph", 422)
        if state.get("profile") == "rescue_v2":
            from .simulation import advance
            return advance(state, decision)
        next_state = copy.deepcopy(state)
        agents = {a["id"]: a for a in next_state["agents"]}
        if any(identifier not in agents for identifier in decision["role_assignments"]):
            raise ProtocolError("INVALID_COMMAND", "Роль назначена неизвестному агенту", 422)
        for a in agents.values():
            a["role"] = decision["role_assignments"].get(a["id"])
            a["scenario_ids"] = list(ids) if a["role"] else []
        before = {a["id"]: copy.deepcopy(a["position"]) for a in state["agents"]}
        processed, results = set(), []
        for command in decision["commands"]:
            identifier, action_name = command["agent_id"], command["action"]
            if identifier in processed:
                raise ProtocolError("INVALID_COMMAND", "Не более одной команды агенту за шаг", 422)
            processed.add(identifier)
            if identifier not in agents:
                raise ProtocolError("INVALID_COMMAND", "Неизвестный агент", 422, agent_id=identifier)
            a = agents[identifier]
            if a["status"] != "active" or action_name not in {x["action"] for x in a["available_actions"]}:
                raise ProtocolError("INVALID_COMMAND", "Действие недоступно агенту", 422,
                                    agent_id=identifier, action=action_name)
            try:
                check(command["parameters"], ACTION_SCHEMAS[action_name])
            except ProtocolError as error:
                raise ProtocolError("INVALID_COMMAND", error.message, 422, **error.details) from error
            cost = 0.0
            if action_name == "move":
                target = command["parameters"]["target"]
                if any(not lo <= x <= hi for x, lo, hi in zip(target, *BOUNDS)):
                    raise ProtocolError("CONSTRAINT_VIOLATION", "Точка вне границ мира", 422, constraint_id="bounds")
                if a["kind"] == "ground" and target[2] != 0.0:
                    raise ProtocolError("CONSTRAINT_VIOLATION", "Наземный агент должен оставаться на поверхности", 422)
                start = a["position"]
                distance = math.dist(start, target)
                factor = min(1.0, SPEED * DT / distance) if distance else 0.0
                end = [round(x + factor * (y - x), 12) for x, y in zip(start, target)]
                if intersects_box(start, end, *RESTRICTED):
                    raise ProtocolError("CONSTRAINT_VIOLATION", "Пересечение запретной зоны", 422,
                                        constraint_id="restricted_1")
                cost = math.dist(start, end) * ENERGY_PER_METRE
                a["position"] = end
            else:
                target = next((t for t in next_state["targets"] if t["id"] == command["parameters"]["target_id"]), None)
                if target is None or a["position"] is None or math.dist(a["position"], target["position"]) > 1.0:
                    raise ProtocolError("INVALID_COMMAND", "Цель отсутствует или вне радиуса наблюдения", 422)
                target["status"] = "confirmed"
                cost = 0.005
            resource = a["resources"]["energy"]
            if resource["value"] - cost < resource["minimum"] - 1e-12:
                raise ProtocolError("RESOURCE_EXHAUSTED", "Команда нарушит резерв энергии", 422,
                                    agent_id=identifier, constraint_id="energy_reserve")
            resource["value"] = max(resource["minimum"], round(resource["value"] - cost, 12))
            results.append({"agent_id": identifier, "action": action_name, "status": "applied"})
        spatial = [a for a in agents.values() if a["position"] is not None]
        for i, a in enumerate(spatial):
            for b in spatial[i + 1:]:
                if closest_distance(before[a["id"]], a["position"], before[b["id"]], b["position"]) < 0.5:
                    raise ProtocolError("CONSTRAINT_VIOLATION", "Траектории агентов создают коллизию", 422,
                                        constraint_id="collision_distance")
        next_state["time"] = round(state["time"] + DT, 12)
        next_state["step_count"] += 1
        next_state["request_id"] = decision["request_id"]
        next_state["decision_ids"].add(decision["decision_id"])
        next_state["configuration"] = {"scenario_ids": list(ids), "role_assignments": copy.deepcopy(decision["role_assignments"])}
        next_state["parameters"] = copy.deepcopy(selected["parameters"])
        completed = all(t["status"] == "confirmed" for t in next_state["targets"])
        if operation == "safe_stop":
            next_state["status"], next_state["mission"]["status"] = "safe_stopped", "safe_stopped"
        elif completed:
            next_state["status"], next_state["mission"]["status"] = "success", "completed"
            next_state["mission"]["objectives"][0]["status"] = "completed"
        elif next_state["step_count"] >= state["max_steps"]:
            next_state["status"], next_state["mission"]["status"] = "time_limit", "failed"
        next_state["metrics"] = {"mission_completion": float(completed), "step_count": next_state["step_count"],
                                 "energy_used": round(sum(1.0 - a["resources"]["energy"]["value"] for a in agents.values()), 12)}
        return next_state, results

    def logs(self):
        with self.lock:
            return {"protocol_version": "1.0", "episode_id": self.state["episode_id"] if self.state else None,
                    "records": self.journal.snapshot()}
