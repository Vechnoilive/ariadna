"""Независимый клиент базового профиля: только стандартная библиотека."""

import argparse
import json
import uuid
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def request(base, path, payload=None):
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    query = Request(base.rstrip("/") + path, data=body, method="POST" if body is not None else "GET",
                    headers={"Content-Type": "application/json; charset=utf-8"})
    try:
        response = urlopen(query, timeout=3)
    except HTTPError as error:
        response = error
    with response:
        return response.status, json.loads(response.read().decode("utf-8"))


def probe(base, controller_url=None):
    checks = []
    prefix = "probe_" + uuid.uuid4().hex[:12]
    for operation in ("health", "capabilities"):
        status, value = request(base, "/v1/environment/" + operation)
        assert status == 200 and value["protocol_version"] == "1.0", operation
        checks.append(operation)
    if controller_url:
        status, health = request(controller_url, "/v1/controller/health")
        assert status == 200 and health["status"] == "ready", "controller_health"
        checks.append("controller_health")
    reset = {"protocol_version": "1.0", "request_id": prefix + "_reset", "seed": 42,
             "mission": {"id": "search_and_rescue", "parameters": {}}}
    status, initial = request(base, "/v1/environment/reset", reset)
    assert status == 200, initial
    observation = initial["observation"]
    mandatory = {"protocol_version", "request_id", "episode_id", "time", "mission", "agents", "infrastructure",
                 "targets", "zones", "network", "events", "constraints", "metrics", "observation_quality"}
    assert mandatory <= observation.keys(), "observation_fields"
    checks.extend(["reset", "observation_fields"])
    moving = next(agent for agent in observation["agents"] if agent["position"] is not None and
                  any(action.get("action") == "move" for action in agent["available_actions"]))
    decision = {
        "protocol_version": "1.0", "episode_id": initial["episode_id"], "request_id": prefix + "_select",
        "decision_id": prefix + "_decision_select", "time": 0.0, "operation": "select",
        "previous_configuration": {"scenario_ids": [], "role_assignments": {}},
        "selected_configuration": {"scenario_ids": ["independent_scenario"], "parameters": {}, "synthesized_scenario": None},
        "candidate_evaluations": [], "role_assignments": {moving["id"]: "independent_role"},
        "commands": [{"agent_id": moving["id"], "action": "move", "parameters": {"target": moving["position"]}}],
        "constraint_checks": [], "explanation": {"observation_refs": [], "reason_codes": ["protocol_probe"],
                                                      "expected_effects": ["hold_position"], "confidence": 1.0},
        "x_independent_optional_field": True,
    }
    status, result = request(base, "/v1/environment/step", decision)
    assert status == 200 and result["time"] > 0.0, result
    status, repeated = request(base, "/v1/environment/step", decision)
    assert status == 200 and repeated == result, "idempotent_step"
    assert request(base, "/v1/environment/observation")[1]["time"] == result["time"], "duplicate_advanced_time"
    checks.extend(["select", "optional_field", "idempotent_step"])
    for operation, ids in (("keep", ["independent_scenario"]), ("switch", ["independent_reconfigured"])):
        decision["previous_configuration"] = {"scenario_ids": decision["selected_configuration"]["scenario_ids"],
                                               "role_assignments": decision["role_assignments"]}
        decision["request_id"] = prefix + "_" + operation
        decision["decision_id"] = prefix + "_decision_" + operation
        decision["time"] = result["time"]
        decision["operation"] = operation
        decision["selected_configuration"] = {"scenario_ids": ids, "parameters": {}, "synthesized_scenario": None}
        status, result = request(base, "/v1/environment/step", decision)
        assert status == 200, result
        checks.append(operation)
    decision["previous_configuration"] = {"scenario_ids": decision["selected_configuration"]["scenario_ids"],
                                           "role_assignments": decision["role_assignments"]}
    decision["operation"] = "keep"
    decision["time"] = result["time"]
    decision["request_id"] = prefix + "_invalid"
    decision["decision_id"] = prefix + "_decision_invalid"
    decision["commands"][0]["action"] = "impossible_action"
    status, error = request(base, "/v1/environment/step", decision)
    assert status == 422 and error["error"]["code"] == "INVALID_COMMAND", error
    assert request(base, "/v1/environment/observation")[1]["time"] == result["time"], "invalid_mutated_state"
    checks.append("invalid_command_atomicity")
    close = {"protocol_version": "1.0", "request_id": prefix + "_close", "episode_id": initial["episode_id"]}
    assert request(base, "/v1/environment/close", close)[0] == 200, "close"
    assert request(base, "/v1/environment/logs")[1]["records"], "logs"
    checks.extend(["close", "logs"])
    return {"status": "passed", "checks": checks}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--environment-url", required=True)
    parser.add_argument("--controller-url")
    args = parser.parse_args()
    print(json.dumps(probe(args.environment_url, args.controller_url), ensure_ascii=False, indent=2))
