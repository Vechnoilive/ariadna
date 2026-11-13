import copy
import json
import unittest
from concurrent.futures import ThreadPoolExecutor
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from hackroi.controller import Controller
from hackroi.environment import Environment
from hackroi.http import ControllerApplication, EnvironmentApplication, background_server
from scripts.probe_protocol import probe


class HttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server, cls.thread = background_server(EnvironmentApplication(Environment()))
        cls.base = "http://127.0.0.1:" + str(cls.server.server_address[1])
        cls.controller_server, cls.controller_thread = background_server(ControllerApplication(Controller()))
        cls.controller_url = "http://127.0.0.1:" + str(cls.controller_server.server_address[1])

    @classmethod
    def tearDownClass(cls):
        for server, thread in ((cls.server, cls.thread), (cls.controller_server, cls.controller_thread)):
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)

    def request(self, operation, method="GET", payload=None, data=None, content_type="application/json", base=None):
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
        request = Request((base or self.base) + operation, method=method, data=data,
                          headers={"Content-Type": content_type})
        try:
            response = urlopen(request, timeout=3)
        except HTTPError as error:
            response = error
        with response:
            self.assertEqual(response.headers.get_content_type(), "application/json")
            body = json.loads(response.read().decode("utf-8"))
            return response.status, body

    def setUp(self):
        self.number = self._testMethodName
        self.reset = {"protocol_version": "1.0", "request_id": "reset_" + self.number,
                      "seed": 42, "mission": {"id": "search_and_rescue", "parameters": {}}}
        status, self.initial = self.request("/v1/environment/reset", "POST", self.reset)
        self.assertEqual(status, 200)

    def decision(self):
        return {
            "protocol_version": "1.0", "episode_id": self.initial["episode_id"],
            "request_id": "step_" + self.number, "decision_id": "decision_" + self.number,
            "time": 0.0, "operation": "select",
            "previous_configuration": {"scenario_ids": [], "role_assignments": {}},
            "selected_configuration": {"scenario_ids": ["foreign_search"], "parameters": {}, "synthesized_scenario": None},
            "candidate_evaluations": [], "role_assignments": {"scout_A": "foreign_role"},
            "commands": [{"agent_id": "scout_A", "action": "move", "parameters": {"target": [10, 8, 10]}}],
            "constraint_checks": [],
            "explanation": {"observation_refs": [], "reason_codes": ["independent_client"],
                            "expected_effects": ["move"], "confidence": 1.0},
        }

    def test_all_eight_normative_routes(self):
        for path in ("health", "capabilities", "observation", "logs"):
            self.assertEqual(self.request("/v1/environment/" + path)[0], 200)
        status, health = self.request("/v1/controller/health", base=self.controller_url)
        self.assertEqual(status, 200)
        self.assertEqual(health["protocol_version"], "1.0")
        decision = self.decision()
        self.assertEqual(self.request("/v1/environment/step", "POST", decision)[0], 200)
        close = {"protocol_version": "1.0", "request_id": "close_" + self.number, "episode_id": self.initial["episode_id"]}
        self.assertEqual(self.request("/v1/environment/close", "POST", close)[0], 200)

    def test_standalone_client_without_shared_contracts(self):
        self.assertEqual(probe(self.base, self.controller_url)["status"], "passed")

    def test_mandatory_observation_profile(self):
        _, observation = self.request("/v1/environment/observation")
        for key in ("protocol_version", "episode_id", "request_id", "time", "mission", "agents", "infrastructure",
                    "targets", "zones", "network", "events", "constraints", "metrics", "observation_quality"):
            self.assertIn(key, observation)
        for agent in observation["agents"]:
            self.assertIn("scenario_ids", agent)
            self.assertTrue(all(isinstance(action, dict) for action in agent["available_actions"]))

    def test_keep_and_switch_from_independent_client(self):
        decision = self.decision()
        status, result = self.request("/v1/environment/step", "POST", decision)
        self.assertEqual(status, 200)
        for operation, ids in (("keep", ["foreign_search"]), ("switch", ["other_foreign_scenario"])):
            decision["previous_configuration"] = {"scenario_ids": decision["selected_configuration"]["scenario_ids"],
                                                   "role_assignments": decision["role_assignments"]}
            decision["request_id"] += "_" + operation
            decision["decision_id"] += "_" + operation
            decision["operation"] = operation
            decision["time"] = result["time"]
            decision["selected_configuration"] = {"scenario_ids": ids, "parameters": {}, "synthesized_scenario": None}
            status, result = self.request("/v1/environment/step", "POST", decision)
            self.assertEqual(status, 200)

    def test_bad_command_returns_normative_error_and_preserves_state(self):
        decision = self.decision()
        decision["commands"][0]["action"] = "teleport"
        status, result = self.request("/v1/environment/step", "POST", decision)
        self.assertEqual(status, 422)
        self.assertEqual(result["error"]["code"], "INVALID_COMMAND")
        self.assertEqual(result["request_id"], decision["request_id"])
        self.assertEqual(self.request("/v1/environment/observation")[1]["time"], 0.0)

    def test_http_duplicate_steps_are_serialized(self):
        decision = self.decision()
        with ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(lambda _: self.request("/v1/environment/step", "POST", decision), range(6)))
        self.assertTrue(all(result == results[0] for result in results))
        self.assertEqual(self.request("/v1/environment/observation")[1]["time"], 1.0)

    def test_invalid_json_and_non_object_body(self):
        for data in (b'{', b'[]', b'null', b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":1e309}', b'\xff'):
            with self.subTest(data=data):
                status, body = self.request("/v1/environment/reset", "POST", data=data)
                self.assertEqual(status, 400)
                self.assertEqual(body["error"]["code"], "INVALID_REQUEST")

    def test_oversized_body_and_wrong_content_type(self):
        self.assertEqual(self.request("/v1/environment/reset", "POST", data=b"x" * 65537)[0], 413)
        self.assertEqual(self.request("/v1/environment/reset", "POST", data=b"{}", content_type="text/plain")[0], 415)

    def test_wrong_version_unknown_route_and_method(self):
        request = copy.deepcopy(self.reset)
        request["protocol_version"] = "2.0"
        status, body = self.request("/v1/environment/reset", "POST", request)
        self.assertEqual((status, body["error"]["code"]), (400, "UNSUPPORTED_PROTOCOL_VERSION"))
        self.assertEqual(self.request("/v1/no-such-route")[0], 404)
        self.assertEqual(self.request("/v1/environment/reset")[0], 405)
        self.assertEqual(self.request("/v1/environment/health", "OPTIONS")[0], 405)

    def test_optional_extensions_are_not_required(self):
        decision = self.decision()
        decision["x_other_team"] = {"ignored": True}
        status, body = self.request("/v1/environment/step", "POST", decision)
        self.assertEqual(status, 200)
        self.assertEqual(body["time"], 1.0)

    def test_error_is_available_in_machine_readable_log(self):
        self.request("/v1/environment/not_found")
        _, logs = self.request("/v1/environment/logs")
        self.assertEqual(logs["records"][-1]["kind"], "error")
        self.assertEqual(logs["records"][-1]["error"]["code"], "INVALID_REQUEST")
