import copy
import hashlib
import tempfile
import unittest
from pathlib import Path

from hackroi.audit import audit, read_records
from hackroi.contracts import canonical
from scripts.run_demo import run


class DemoTests(unittest.TestCase):
    def test_two_process_demo_and_exact_reproducibility(self):
        with tempfile.TemporaryDirectory() as temporary:
            first = run(42, Path(temporary) / "first")
            second = run(42, Path(temporary) / "second")
            self.assertEqual(first["processes"], 2)
            self.assertEqual(first["episode"]["status"], "success")
            self.assertEqual(first["episode"], second["episode"])
            self.assertEqual(first["audit"], second["audit"])
            for filename in ("environment.jsonl", "controller.jsonl"):
                self.assertEqual((Path(temporary) / "first" / filename).read_bytes(),
                                 (Path(temporary) / "second" / filename).read_bytes())

    def test_audit_rejects_missing_or_fabricated_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            run(123, temporary)
            environment = read_records(Path(temporary) / "environment.jsonl")
            controller = read_records(Path(temporary) / "controller.jsonl")
            self.assertEqual(audit(environment, controller)["status"], "passed")
            variants = []
            missing = [r for r in controller if r["kind"] != "result"]
            variants.append(missing)
            wrong_command = copy.deepcopy(controller)
            next(r for r in wrong_command if r["kind"] == "decision")["decision"]["commands"] = []
            variants.append(wrong_command)
            fake_observation = copy.deepcopy(controller)
            record = next(r for r in fake_observation if r["kind"] == "decision")
            record["observation"]["agents"][0]["resources"]["energy"]["value"] = 0.5
            record["decision"]["explanation"]["observation_refs"] = ["sha256:" + hashlib.sha256(canonical(record["observation"]).encode()).hexdigest()]
            variants.append(fake_observation)
            for variant in variants:
                with self.assertRaises(ValueError):
                    audit(environment, variant)
