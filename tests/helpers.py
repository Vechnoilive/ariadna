import copy

from hackroi.controller import Controller


def reset_request(seed=42, request_id="reset_test", max_steps=40):
    return {"protocol_version": "1.0", "request_id": request_id, "seed": seed,
            "mission": {"id": "search_and_rescue", "parameters": {"max_steps": max_steps}}}


def probe_decision(environment):
    return Controller().decide(environment.observation(), environment.state["configuration"], environment.state["parameters"])


def metadata_decision(environment, operation="select", selected=None, parameters=None):
    decision = probe_decision(environment)
    decision["operation"] = operation
    decision["commands"] = []
    decision["role_assignments"] = {"scout_A": "scout"}
    decision["selected_configuration"]["scenario_ids"] = selected or ["coverage_search"]
    decision["selected_configuration"]["parameters"] = copy.deepcopy(parameters or {})
    return decision
