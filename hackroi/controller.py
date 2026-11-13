"""Протокольный контроллер первого этапа, без полноценного метапланирования."""

import copy
import hashlib
import math
import threading
import time
import uuid

from .client import Client
from .contracts import OPERATIONS, ProtocolError, canonical, validate
from .journal import Journal


class Controller:
    def __init__(self, log_path=None):
        self.journal = Journal(log_path)
        self.lock = threading.RLock()
        self.status = "idle"

    def health(self):
        with self.lock:
            return {"protocol_version": "1.0", "component": "controller", "status": "ready",
                    "controller_id": "ariadna_stage1_probe", "supported_operations": list(OPERATIONS),
                    "execution_status": self.status, "profile": "ariadna.stage1.v1"}

    def decide(self, observation, previous=None, parameters=None):
        validate("observation", observation)
        previous = previous or {"scenario_ids": [], "role_assignments": {}}
        parameters = parameters or {}
        candidates = []
        for a in observation["agents"]:
            actions = {x.get("action", x.get("name")) for x in a["available_actions"]}
            if a["status"] != "active" or a["position"] is None or not {"move", "observe"} <= actions:
                continue
            if a["resources"].get("energy", {}).get("value", 0) <= a["resources"].get("energy", {}).get("minimum", 1):
                continue
            for target in observation["targets"]:
                if target.get("status") == "confirmed" or not isinstance(target.get("position"), list):
                    continue
                if a["kind"] == "ground" and target["position"][2] != 0:
                    continue
                distance = math.dist(a["position"], target["position"])
                key = (distance, tuple(a["position"]), tuple(target["position"]), a["kind"])
                candidates.append((key, a, target))
        observation_ref = "sha256:" + hashlib.sha256(canonical(observation).encode()).hexdigest()
        sequence = hashlib.sha256(canonical(observation).encode()).hexdigest()[:24]
        decision = {
            "protocol_version": "1.0", "episode_id": observation["episode_id"],
            "request_id": "step_" + sequence, "decision_id": "decision_" + sequence,
            "time": observation["time"], "operation": "safe_stop",
            "previous_configuration": copy.deepcopy(previous),
            "selected_configuration": {"scenario_ids": copy.deepcopy(previous["scenario_ids"]),
                                       "parameters": copy.deepcopy(parameters), "synthesized_scenario": None},
            "candidate_evaluations": [], "role_assignments": copy.deepcopy(previous["role_assignments"]),
            "commands": [], "constraint_checks": [],
            "explanation": {"observation_refs": [observation_ref], "reason_codes": ["no_supported_task"],
                            "expected_effects": ["safe_stop"], "confidence": 1.0},
        }
        if candidates:
            _, chosen, target = min(candidates, key=lambda x: x[0])
            roles = {chosen["id"]: "scout"}
            scenario_ids = ["coverage_search"]
            if not previous["scenario_ids"]:
                operation = "select"
            elif previous["scenario_ids"] == scenario_ids and previous["role_assignments"] == roles:
                operation = "keep"
            else:
                operation = "switch"
            action = "observe" if math.dist(chosen["position"], target["position"]) <= 1.0 else "move"
            command_parameters = {"target_id": target["id"]} if action == "observe" else {"target": target["position"]}
            decision.update({"operation": operation, "role_assignments": roles,
                             "candidate_evaluations": [{"scenario_id": "coverage_search", "applicable": True,
                                                        "selected": True, "risk": 0.0}],
                             "commands": [{"agent_id": chosen["id"], "action": action, "parameters": command_parameters}],
                             "selected_configuration": {"scenario_ids": scenario_ids,
                                                        "parameters": {}, "synthesized_scenario": None}})
            decision["explanation"].update({"reason_codes": ["stage1_protocol_probe"],
                                            "expected_effects": ["confirm_target"], "confidence": 1.0})
            decision["constraint_checks"] = [{"constraint_id": "agent_available_actions", "status": "passed"}]
        validate("decision", decision)
        return decision

    def run(self, environment_url, seed=42, max_decisions=100, run_id=None):
        with self.lock:
            self.status = "running"
        client = Client(environment_url, timeout=getattr(self, "client_timeout", 3.0),
                        max_response_bytes=getattr(self, "max_response_bytes", 16*1024*1024))
        run_id = run_id or uuid.uuid4().hex
        request = {"protocol_version": "1.0", "request_id": "reset_" + run_id,
                   "seed": seed, "mission": {"id": "search_and_rescue", "parameters": getattr(self, "mission_parameters", {})}}
        response = None
        trusted_episode = None
        try:
            capabilities = client.get("capabilities")
            if capabilities.get("protocol_version") != "1.0":
                raise ProtocolError("UNSUPPORTED_PROTOCOL_VERSION", "Среда не поддерживает 1.0")
            if hasattr(self, "configure_capabilities"):
                self.configure_capabilities(capabilities)
            if hasattr(self, "reset_parameters"):
                request["mission"]["parameters"] = self.reset_parameters(capabilities)
            response = client.post("reset", request)
            validate("reset_response", response)
            if hasattr(self, "validate_reply"):
                self.validate_reply(response, request)
            trusted_episode = response["episode_id"]
            self.journal.append({"protocol_version": "1.0", "component": "controller", "kind": "reset",
                                 "episode_id": response["episode_id"], "input": request, "output": response,
                                 **({"audit_profile": self.audit_profile} if getattr(self, "audit_profile", None) else {}),
                                 **(self.reset_evidence() if hasattr(self, "reset_evidence") else {})})
            previous, parameters = None, None
            for _ in range(max_decisions):
                if response["status"] != "running":
                    break
                # UI pacing changes wall time only; protocol time and decisions stay identical.
                if getattr(self,'decision_delay',0):
                    time.sleep(self.decision_delay)
                observation = response["observation"]
                decision = self.decide(observation, previous, parameters)
                self.journal.append({"protocol_version": "1.0", "component": "controller", "kind": "decision",
                                     "episode_id": response["episode_id"], "decision_id": decision["decision_id"],
                                     "request_id": decision["request_id"], "time": observation["time"],
                                     "observation": observation, "decision": decision})
                response = client.post("step", decision)
                validate("response", response)
                if hasattr(self, "validate_reply"):
                    self.validate_reply(response, decision)
                feedback = self.observe_result(response) if hasattr(self, "observe_result") else None
                self.journal.append({"protocol_version": "1.0", "component": "controller", "kind": "result",
                                     "episode_id": response["episode_id"], "decision_id": decision["decision_id"],
                                     "request_id": decision["request_id"], "output": response,
                                     **({"forecast_feedback": feedback} if feedback is not None else {})})
                previous = {"scenario_ids": copy.deepcopy(decision["selected_configuration"]["scenario_ids"]),
                            "role_assignments": copy.deepcopy(decision["role_assignments"])}
                parameters = copy.deepcopy(decision["selected_configuration"]["parameters"])
            if response["status"] == "running":
                raise ProtocolError("TIMEOUT", "Превышен лимит решений контроллера", 504)
            summary = {"episode_id": response["episode_id"], "status": response["status"],
                       "time": response["time"], "metrics": response.get("metrics", response["observation"]["metrics"])}
            client.post("close", {"protocol_version": "1.0", "request_id": "close_" + run_id,
                                  "episode_id": response["episode_id"]})
            with self.lock:
                self.status = "completed"
            return summary
        except Exception as error:
            with self.lock:
                self.status = "failed"
            self.journal.append({"protocol_version": "1.0", "component": "controller", "kind": "error",
                                 "code": error.code if isinstance(error, ProtocolError) else "INTERNAL_ERROR",
                                 "message": str(error)})
            if trusted_episode is not None:
                try:
                    client.post("close", {"protocol_version": "1.0", "request_id": "abort_" + run_id,
                                          "episode_id": trusted_episode})
                except Exception:
                    pass
            raise
