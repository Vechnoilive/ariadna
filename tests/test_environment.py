import copy
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from hackroi.contracts import ProtocolError, canonical
from hackroi.environment import Environment, closest_distance, intersects_box
from tests.helpers import metadata_decision, probe_decision, reset_request


class EnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.environment = Environment()
        self.environment.mutate("reset", reset_request())

    def test_reset_observation_requires_existing_episode(self):
        with self.assertRaises(ProtocolError) as captured:
            Environment().observation()
        self.assertEqual(captured.exception.code, "UNKNOWN_EPISODE")

    def test_same_seed_and_commands_reproduce_full_response(self):
        other = Environment()
        other.mutate("reset", reset_request())
        for _ in range(5):
            decision = probe_decision(self.environment)
            self.assertEqual(self.environment.mutate("step", decision), other.mutate("step", decision))

    def test_different_seeds_change_conditions(self):
        other = Environment()
        other.mutate("reset", reset_request(seed=43))
        self.assertNotEqual(self.environment.observation()["targets"], other.observation()["targets"])

    def test_continuous_motion_is_bounded_by_speed(self):
        before = self.environment.observation()["agents"][0]["position"]
        response = self.environment.mutate("step", probe_decision(self.environment))
        after = response["observation"]["agents"][0]["position"]
        import math
        self.assertAlmostEqual(math.dist(before, after), 5.0)
        self.assertTrue(any(value != int(value) for value in after))
        self.assertIsInstance(response["time"], float)

    def test_vertical_motion_changes_the_third_coordinate(self):
        decision = probe_decision(self.environment)
        decision["commands"] = [{"agent_id": "scout_A", "action": "move", "parameters": {"target": [5, 5, 15]}}]
        response = self.environment.mutate("step", decision)
        self.assertEqual(response["observation"]["agents"][0]["position"], [5.0, 5.0, 15.0])

    def test_reset_is_idempotent_without_destroying_progress(self):
        initial = copy.deepcopy(self.environment.cache["reset_test"][1])
        self.environment.mutate("step", probe_decision(self.environment))
        response = self.environment.mutate("reset", reset_request())
        self.assertEqual(initial, response)
        self.assertEqual(self.environment.observation()["time"], 1.0)

    def test_step_is_idempotent_and_does_not_duplicate_journal(self):
        decision = probe_decision(self.environment)
        first = self.environment.mutate("step", decision)
        count = len(self.environment.journal.records)
        self.assertEqual(first, self.environment.mutate("step", decision))
        self.assertEqual(self.environment.observation()["time"], 1.0)
        self.assertEqual(len(self.environment.journal.records), count)

    def test_duplicate_request_with_different_payload_rejected(self):
        decision = probe_decision(self.environment)
        self.environment.mutate("step", decision)
        decision["commands"][0]["parameters"]["target"][0] += 1
        with self.assertRaises(ProtocolError) as captured:
            self.environment.mutate("step", decision)
        self.assertEqual(captured.exception.status, 409)
        self.assertEqual(self.environment.observation()["time"], 1.0)

    def test_concurrent_duplicate_steps_execute_exactly_once(self):
        decision = probe_decision(self.environment)
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: self.environment.mutate("step", decision), range(8)))
        self.assertTrue(all(result == results[0] for result in results))
        self.assertEqual(self.environment.observation()["time"], 1.0)

    def test_competing_decisions_cannot_both_execute(self):
        first = probe_decision(self.environment)
        second = copy.deepcopy(first)
        second["request_id"], second["decision_id"] = "other_request", "other_decision"
        def invoke(decision):
            try:
                self.environment.mutate("step", decision)
                return "applied"
            except ProtocolError:
                return "rejected"
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertCountEqual(list(pool.map(invoke, [first, second])), ["applied", "rejected"])

    def test_rejected_batch_is_atomic(self):
        before = self.environment.observation()
        decision = probe_decision(self.environment)
        decision["commands"].append({"agent_id": "missing", "action": "move", "parameters": {"target": [1, 1, 0]}})
        with self.assertRaises(ProtocolError):
            self.environment.mutate("step", decision)
        self.assertEqual(before, self.environment.observation())
        self.assertEqual(len(self.environment.journal.records), 1)

    def test_fail_to_persist_journal_cannot_commit_state(self):
        before = self.environment.observation()
        with patch.object(self.environment.journal, "append", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.environment.mutate("step", probe_decision(self.environment))
        self.assertEqual(before, self.environment.observation())

    def test_bad_action_and_parameters_rejected(self):
        for command in (
            {"agent_id": "scout_A", "action": "teleport", "parameters": {}},
            {"agent_id": "compute_C", "action": "move", "parameters": {"target": [1, 1, 1]}},
            {"agent_id": "scout_A", "action": "move", "parameters": {"target": [1, 2]}},
            {"agent_id": "scout_A", "action": "observe", "parameters": {"target_id": "missing"}},
        ):
            with self.subTest(command=command):
                decision = probe_decision(self.environment)
                decision["commands"] = [command]
                with self.assertRaises(ProtocolError) as captured:
                    self.environment.mutate("step", decision)
                self.assertEqual(captured.exception.code, "INVALID_COMMAND")

    def test_unknown_episode_stale_time_and_decision_reuse(self):
        for field, value in (("episode_id", "unknown"), ("time", 7.0)):
            decision = probe_decision(self.environment)
            decision[field] = value
            with self.subTest(field=field), self.assertRaises(ProtocolError):
                self.environment.mutate("step", decision)
        first = probe_decision(self.environment)
        self.environment.mutate("step", first)
        second = probe_decision(self.environment)
        second["decision_id"] = first["decision_id"]
        with self.assertRaises(ProtocolError):
            self.environment.mutate("step", second)

    def test_energy_reserve_is_enforced(self):
        self.environment.state["agents"][0]["resources"]["energy"]["value"] = 0.151
        with self.assertRaises(ProtocolError) as captured:
            self.environment.mutate("step", probe_decision(self.environment))
        self.assertEqual(captured.exception.code, "RESOURCE_EXHAUSTED")

    def test_world_bounds_surface_and_forbidden_volume(self):
        cases = [("scout_A", [101, 5, 10]), ("carrier_B", [5, 5, 1]), ("scout_A", [85, 85, 10])]
        for identifier, target in cases:
            if target[0] == 85:
                self.environment.state["agents"][0]["position"] = [79.0, 85.0, 10.0]
            decision = probe_decision(self.environment)
            decision["commands"] = [{"agent_id": identifier, "action": "move", "parameters": {"target": target}}]
            with self.subTest(target=target), self.assertRaises(ProtocolError) as captured:
                self.environment.mutate("step", decision)
            self.assertEqual(captured.exception.code, "CONSTRAINT_VIOLATION")

    def test_swept_collisions_catch_crossing_paths(self):
        self.assertAlmostEqual(closest_distance([0, 0, 0], [2, 0, 0], [2, 0, 0], [0, 0, 0]), 0.0)
        self.environment.state["agents"][0]["position"] = [0.0, 0.0, 0.0]
        self.environment.state["agents"][1]["position"] = [5.0, 0.0, 0.0]
        decision = metadata_decision(self.environment)
        decision["commands"] = [
            {"agent_id": "scout_A", "action": "move", "parameters": {"target": [5, 0, 0]}},
            {"agent_id": "carrier_B", "action": "move", "parameters": {"target": [0, 0, 0]}},
        ]
        with self.assertRaises(ProtocolError) as captured:
            self.environment.mutate("step", decision)
        self.assertEqual(captured.exception.details["constraint_id"], "collision_distance")

    def test_segment_volume_intersection(self):
        self.assertTrue(intersects_box([0, 0, 0], [10, 0, 0], [4, -1, -1], [6, 1, 1]))
        self.assertFalse(intersects_box([0, 2, 0], [10, 2, 0], [4, -1, -1], [6, 1, 1]))

    def test_all_seven_operations_are_distinct_and_logged(self):
        specifications = [
            ("select", ["coverage_search"], {}), ("keep", ["coverage_search"], {}),
            ("modify", ["coverage_search"], {"radius": 5}),
            ("switch", ["priority_delivery"], {}),
            ("compose", ["priority_delivery", "relay_coalition"], {}),
            ("synthesize", ["new_configuration"], {}), ("safe_stop", ["new_configuration"], {}),
        ]
        for operation, ids, parameters in specifications:
            decision = metadata_decision(self.environment, operation, ids, parameters)
            if operation == "synthesize":
                decision["selected_configuration"]["synthesized_scenario"] = {"id": "new_configuration", "graph": {"nodes": [], "edges": []}}
            self.environment.mutate("step", decision)
        operations = [record["input"]["operation"] for record in self.environment.journal.records if record["kind"] == "step"]
        self.assertEqual(operations, [item[0] for item in specifications])
        self.assertEqual(self.environment.state["status"], "safe_stopped")

    def test_bad_scenario_transition_rejected(self):
        for operation in ("keep", "modify", "compose", "synthesize"):
            decision = metadata_decision(self.environment, operation)
            with self.subTest(operation=operation), self.assertRaises(ProtocolError) as captured:
                self.environment.mutate("step", decision)
            self.assertEqual(captured.exception.code, "INVALID_SCENARIO")

    def test_close_is_idempotent_and_prevents_stepping(self):
        request = {"protocol_version": "1.0", "request_id": "close_test", "episode_id": self.environment.state["episode_id"]}
        response = self.environment.mutate("close", request)
        self.assertEqual(response, self.environment.mutate("close", request))
        with self.assertRaises(ProtocolError):
            self.environment.mutate("step", probe_decision(self.environment))
        self.assertEqual(self.environment.observation()["mission"]["status"], "safe_stopped")

    def test_time_limit_and_reset_after_close(self):
        self.environment.mutate("reset", reset_request(request_id="short_run", max_steps=1))
        response = self.environment.mutate("step", probe_decision(self.environment))
        self.assertEqual(response["status"], "time_limit")
        new = self.environment.mutate("reset", reset_request(request_id="new_run"))
        self.assertEqual(new["time"], 0.0)
        self.assertEqual(new["status"], "running")

    def test_unknown_optional_request_fields_do_not_change_dynamics(self):
        other = Environment()
        other.mutate("reset", reset_request())
        first = probe_decision(self.environment)
        second = copy.deepcopy(first)
        second["x_future"] = {"ignored": 5}
        self.assertEqual(self.environment.mutate("step", first), other.mutate("step", second))

    def test_request_and_response_mutation_cannot_corrupt_cache(self):
        decision = probe_decision(self.environment)
        first = self.environment.mutate("step", decision)
        expected = canonical(first)
        first["observation"]["agents"].clear()
        self.assertEqual(expected, canonical(self.environment.mutate("step", decision)))

    def test_cache_limit_never_silently_evicts_old_mutations(self):
        with patch("hackroi.environment.MAX_REQUESTS", 1):
            with self.assertRaises(ProtocolError) as captured:
                self.environment.mutate("step", probe_decision(self.environment))
            self.assertEqual(captured.exception.code, "RESOURCE_EXHAUSTED")
            self.assertEqual(self.environment.mutate("reset", reset_request())["time"], 0.0)
