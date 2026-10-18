"""A manual physical-symmetry declaration is explicit, auditable metadata."""
import copy
import unittest

from cfd_review.demo import make_demo_case
from cfd_review.schema import validate_case


class UserSymmetryChecks(unittest.TestCase):
    def test_declaration_requires_valid_timestamp_original_flags_and_active_y_half(self):
        case = make_demo_case()
        case["data"]["meta"]["symmetryDeclaration"] = {
            "kind": "user-confirmed-y0-half", "version": 1,
            "statement": "User confirmed a symmetric Y=0 half model",
            "confirmedAt": "2026-10-18T09:10:11.123Z",
            "original": {"halfCar": False, "mirrorAxisPresent": False, "mirrorAxis": None}}
        before = copy.deepcopy(case)
        self.assertIs(validate_case(case), case)
        self.assertEqual(case, before)
        for axis in ("x", "y", "z"):
            candidate = copy.deepcopy(case)
            candidate["data"]["meta"]["symmetryDeclaration"]["original"].update(
                mirrorAxisPresent=True, mirrorAxis=axis)
            validate_case(candidate)
        invalid = [
            ("kind", "inferred-from-geometry"), ("version", True), ("version", 2),
            ("statement", ""), ("statement", "x" * 301),
            ("confirmedAt", "today"), ("confirmedAt", "2026-02-30T01:00:00Z"),
            ("confirmedAt", "2026-10-18T09:10:11"), ("confirmedAt", None),
            ("original", {}), ("original", {"halfCar": True, "mirrorAxisPresent": False, "mirrorAxis": None}),
            ("original", {"halfCar": False, "mirrorAxisPresent": False, "mirrorAxis": "y"}),
            ("original", {"halfCar": False, "mirrorAxisPresent": True, "mirrorAxis": None}),
            ("original", {"halfCar": False, "mirrorAxisPresent": 1, "mirrorAxis": "y"}),
        ]
        for key, value in invalid:
            with self.subTest(key=key, value=value):
                candidate = copy.deepcopy(case)
                candidate["data"]["meta"]["symmetryDeclaration"][key] = value
                with self.assertRaisesRegex(ValueError, "symmetryDeclaration"):
                    validate_case(candidate)
        for changes in ({"halfCar": False, "scalarMirror": False}, {"mirrorAxis": "x", "scalarMirror": False}):
            candidate = copy.deepcopy(case)
            candidate["data"]["meta"].update(changes)
            with self.assertRaisesRegex(ValueError, "symmetryDeclaration"):
                validate_case(candidate)


if __name__ == "__main__":
    unittest.main()
