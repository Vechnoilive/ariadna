import copy
import math
import unittest

from hackroi.contracts import ERROR_CODES, ProtocolError, check, exported_schemas, validate
from hackroi.environment import Environment
from hackroi.http import parse_json
from tests.helpers import probe_decision, reset_request


class ContractsTests(unittest.TestCase):
    def setUp(self):
        self.environment = Environment()
        self.response = self.environment.mutate("reset", reset_request())

    def test_generated_responses_and_decisions_match_schema(self):
        validate("response", self.response)
        validate("observation", self.response["observation"])
        validate("decision", probe_decision(self.environment))

    def test_missing_required_fields_rejected(self):
        for field in self.response["observation"]:
            with self.subTest(field=field):
                observation = copy.deepcopy(self.response["observation"])
                del observation[field]
                with self.assertRaises(ProtocolError):
                    validate("observation", observation)

    def test_wrong_version_has_normative_error(self):
        request = reset_request()
        request["protocol_version"] = "2.0"
        with self.assertRaises(ProtocolError) as captured:
            validate("reset", request)
        self.assertEqual(captured.exception.code, "UNSUPPORTED_PROTOCOL_VERSION")

    def test_booleans_cannot_be_numbers(self):
        request = reset_request()
        request["seed"] = True
        with self.assertRaises(ProtocolError):
            validate("reset", request)

    def test_nonfinite_and_wrong_positions_rejected(self):
        for position in ([0, 1], [0, 1, 2, 3], [0, "1", 2], [0, 1, math.inf], [0, 1, math.nan]):
            with self.subTest(position=position):
                observation = copy.deepcopy(self.response["observation"])
                observation["agents"][0]["position"] = position
                with self.assertRaises(ProtocolError):
                    validate("observation", observation)

    def test_unknown_optional_fields_are_ignored(self):
        observation = copy.deepcopy(self.response["observation"])
        observation["x_future"] = {"foo": [1, 2, 3]}
        observation["agents"][0]["x_future"] = True
        validate("observation", observation)

    def test_invalid_json_numbers_duplicates_and_utf8_rejected(self):
        for data in (b'{"a":NaN}', b'{"a":Infinity}', b'{"a":1e309}', b'{"a":1,"a":2}', b'\xff', b'{'):
            with self.subTest(data=data), self.assertRaises((ValueError, UnicodeError)):
                parse_json(data)

    def test_error_schema_covers_all_normative_codes(self):
        for code in ERROR_CODES:
            validate("error", ProtocolError(code, "Ошибка проверки").payload())

    def test_export_is_independent_of_callers_mutations(self):
        first = exported_schemas()
        first["decision.schema.json"]["required"].clear()
        self.assertTrue(exported_schemas()["decision.schema.json"]["required"])

    def test_unique_items_and_additional_properties(self):
        with self.assertRaises(ProtocolError):
            check(["a", "a"], {"type": "array", "uniqueItems": True})
        with self.assertRaises(ProtocolError):
            check({"unknown": 1}, {"type": "object", "additionalProperties": False})

    def test_resource_value_must_be_between_declared_limits(self):
        observation = copy.deepcopy(self.response["observation"])
        observation["agents"][0]["resources"]["energy"]["value"] = 0.1
        with self.assertRaises(ProtocolError):
            validate("observation", observation)
