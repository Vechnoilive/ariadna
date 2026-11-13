import copy
import json
import random
import tempfile
import unittest
from pathlib import Path

from hackroi.audit import audit
from hackroi.client import Client
from hackroi.contracts import ProtocolError
from hackroi.controller import Controller
from hackroi.environment import Environment
from hackroi.http import EnvironmentApplication, background_server
from tests.helpers import reset_request


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.environment = Environment()
        self.environment.mutate("reset", reset_request())
        self.controller = Controller()

    def test_renaming_and_array_permutations_preserve_selected_action(self):
        observation = self.environment.observation()
        original = self.controller.decide(observation)
        replacements = {"scout_A": "unit_900", "carrier_B": "unit_010", "compute_C": "unit_300",
                        "target_1": "object_987", "world": "zone_000", "episode_id": "episode_id"}
        def rename(value):
            if isinstance(value, str):
                return replacements.get(value, value)
            if isinstance(value, list):
                return [rename(v) for v in value]
            if isinstance(value, dict):
                return {key: rename(v) for key, v in value.items()}
            return value
        normalized = rename(observation)
        for key in ("agents", "targets", "zones", "infrastructure"):
            random.Random(17).shuffle(normalized[key])
        normalized["x_future"] = {"not_required": True}
        decision = self.controller.decide(normalized)
        self.assertEqual(rename(original["commands"]), decision["commands"])

    def test_observe_uses_renamed_target_identifier(self):
        observation = self.environment.observation()
        observation["agents"][0]["position"] = list(observation["targets"][0]["position"])
        observation["targets"][0]["id"] = "foreign_target"
        command = self.controller.decide(observation)["commands"][0]
        self.assertEqual(command["parameters"], {"target_id": "foreign_target"})

    def test_missing_optional_fields_do_not_prevent_decision(self):
        observation = self.environment.observation()
        for agent in observation["agents"]:
            for action in agent["available_actions"]:
                action.pop("parameters_schema", None)
        self.assertTrue(self.controller.decide(observation)["commands"])

    def test_no_compatible_executor_produces_safe_stop(self):
        observation = self.environment.observation()
        for agent in observation["agents"]:
            agent["status"] = "failed"
        decision = self.controller.decide(observation)
        self.assertEqual(decision["operation"], "safe_stop")
        self.assertEqual(decision["commands"], [])

    def test_sub_millisecond_times_do_not_reuse_request_ids(self):
        first = self.environment.observation()
        second = copy.deepcopy(first)
        second["time"] = 0.0001
        self.assertNotEqual(self.controller.decide(first)["request_id"], self.controller.decide(second)["request_id"])

    def test_controller_completes_and_can_restart_on_same_environment(self):
        server, thread = background_server(EnvironmentApplication(self.environment))
        try:
            url = "http://127.0.0.1:" + str(server.server_address[1])
            first = self.controller.run(url, 42, run_id="first")
            second = self.controller.run(url, 42, run_id="second")
            self.assertEqual(first["status"], "success")
            self.assertEqual(first["metrics"], second["metrics"])
            self.assertNotEqual(first["episode_id"], second["episode_id"])
            self.assertEqual(audit(self.environment.journal.records, self.controller.journal.records)["status"], "passed")
        finally:
            server.shutdown(); server.server_close(); thread.join(timeout=3)

    def test_decision_limit_records_failure_and_closes_episode(self):
        server, thread = background_server(EnvironmentApplication(self.environment))
        try:
            url = "http://127.0.0.1:" + str(server.server_address[1])
            with self.assertRaises(ProtocolError) as captured:
                self.controller.run(url, max_decisions=0, run_id="limited")
            self.assertEqual(captured.exception.code, "TIMEOUT")
            self.assertEqual(self.controller.health()["execution_status"], "failed")
            self.assertTrue(self.environment.state["closed"])
        finally:
            server.shutdown(); server.server_close(); thread.join(timeout=3)

    def test_unavailable_environment_fails_without_retry_loop(self):
        server, thread = background_server(EnvironmentApplication(Environment()))
        url = "http://127.0.0.1:" + str(server.server_address[1])
        server.shutdown(); server.server_close(); thread.join(timeout=3)
        with self.assertRaises(ProtocolError) as captured:
            self.controller.run(url)
        self.assertEqual(captured.exception.code, "TIMEOUT")
        self.assertEqual(self.controller.journal.records[-1]["kind"], "error")

    def test_file_journals_are_utf8_jsonl(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "environment.jsonl"
            environment = Environment(path)
            environment.mutate("reset", reset_request())
            self.assertEqual(json.loads(path.read_text(encoding="utf-8").strip()), environment.journal.records[0])
