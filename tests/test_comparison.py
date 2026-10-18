"""Synthetic half-model composition/provenance; no CFD is solved."""
import copy
import unittest

from cfd_review.comparison import compose_half_comparison
from cfd_review.demo import make_demo_project
from cfd_review.report import project_from_cases
from cfd_review.schema import validate_case, validate_project, validate_state


class HalfComparisonTests(unittest.TestCase):
    def setUp(self):
        self.a, self.b = make_demo_project()["cases"]

    def compose(self):
        return compose_half_comparison(self.a, self.b)

    def project(self, composed=None):
        return project_from_cases([self.a, self.b, composed or self.compose()])

    def test_reflection_winding_scalars_and_originals_preserved(self):
        before = copy.deepcopy((self.a, self.b))
        result = self.compose()
        self.assertFalse(result["data"]["meta"]["halfCar"])
        self.assertFalse(result["data"]["meta"]["scalarMirror"])
        first = result["data"]["parts"][0]
        original = self.a["data"]["parts"][0]
        self.assertEqual(first["positions"][1::3], [-v for v in original["positions"][1::3]])
        self.assertEqual(first["indices"][:3], [original["indices"][0], original["indices"][2], original["indices"][1]])
        self.assertEqual(first["cp"], original["cp"])
        self.assertEqual(first["sourceCaseId"], self.a["id"])
        self.assertEqual((self.a, self.b), before)
        self.assertEqual(len(result["data"]["parts"]), len(self.a["data"]["parts"]) + len(self.b["data"]["parts"]))
        self.assertEqual(len(result["data"]["layers"]), 2)

    def test_either_original_half_side_is_supported(self):
        for kind in ("parts", "sections", "layers"):
            for mesh in self.b["data"][kind]:
                mesh["positions"][1::3] = [-v for v in mesh["positions"][1::3]]
        result = self.compose()
        self.assertEqual(result["data"]["meta"]["comparison"]["sources"][1]["sourceYSign"], -1)
        right = next(p for p in result["data"]["parts"] if p["sourceSide"] == "B")
        self.assertGreater(max(right["positions"][1::3]), 0)
        validate_project(self.project(result))

    def test_only_real_common_planes_and_fields_form_sweep(self):
        result = self.compose()
        original_xs = [[s["x"] for s in c["data"]["sections"]] for c in (self.a, self.b)]
        self.assertTrue(result["data"]["sections"])
        for section in result["data"]["sections"]:
            self.assertTrue(all(any(abs(section["x"] - x) <= 1e-9 * max(1, abs(x)) for x in row) for row in original_xs))
            self.assertEqual(len(section["comparisonRanges"]), 2)
        validate_project(self.project(result))

    def test_no_common_x_keeps_surfaces_without_invented_planes(self):
        for section in self.b["data"]["sections"]:
            section["x"] += .031
            section["positions"][0::3] = [x + .031 for x in section["positions"][0::3]]
        result = self.compose()
        self.assertEqual(result["data"]["sections"], [])
        self.assertEqual(result["data"]["meta"]["comparison"]["sectionsStatus"], "no-common-x")
        self.assertTrue(result["data"]["parts"])

    def test_no_common_scalar_does_not_fill_missing_values(self):
        for section in self.a["data"]["sections"]:
            del section["cpt"]
        for section in self.b["data"]["sections"]:
            del section["cp"]
        result = self.compose()
        self.assertEqual(result["data"]["sections"], [])
        self.assertEqual(result["data"]["meta"]["comparison"]["sectionsStatus"], "no-common-fields")

    def test_full_models_crossing_geometry_and_identical_case_rejected(self):
        with self.assertRaises(ValueError):
            compose_half_comparison(self.a, self.a)
        self.a["data"]["meta"]["halfCar"] = False
        self.a["data"]["meta"]["scalarMirror"] = False
        with self.assertRaises(ValueError):
            self.compose()
        self.a = make_demo_project()["cases"][0]
        self.a["data"]["parts"][0]["positions"][1] = -2
        with self.assertRaisesRegex(ValueError, "crosses"):
            self.compose()

    def test_originals_required_and_scalar_tampering_rejected(self):
        result = self.compose()
        with self.assertRaisesRegex(ValueError, "retain"):
            project_from_cases([result])
        result["data"]["parts"][0]["cp"][0] += 1
        with self.assertRaisesRegex(ValueError, "source scalar"):
            self.project(result)

    def test_missing_mesh_and_forged_source_identity_rejected(self):
        result = self.compose()
        result["data"]["parts"].pop()
        with self.assertRaisesRegex(ValueError, "exactly once"):
            self.project(result)
        result = self.compose()
        result["data"]["meta"]["comparison"]["sources"][0]["sourceId"] = "foreign"
        with self.assertRaisesRegex(ValueError, "identity"):
            self.project(result)

    def test_changed_topology_and_reference_metadata_rejected(self):
        result = self.compose()
        ix = result["data"]["layers"][0]["indices"]
        ix[0], ix[1] = ix[1], ix[0]
        with self.assertRaisesRegex(ValueError, "topology"):
            self.project(result)
        result = self.compose()
        result["data"]["meta"]["comparison"]["coefficientReferences"][0] = {"pressurePa": 123}
        with self.assertRaisesRegex(ValueError, "reference"):
            self.project(result)

    def test_layer_only_native_meshes_are_valid(self):
        self.a["data"]["parts"] = []
        self.a["data"]["sections"] = []
        self.a["data"]["layers"][0]["kind"] = "section"
        validate_case(self.a)
        result = self.compose()
        self.assertTrue(result["data"]["layers"])
        validate_project(self.project(result))
        self.a["data"]["layers"] = []
        with self.assertRaises(ValueError):
            validate_case(self.a)

    def test_picked_source_identity_and_inverse_coordinates_are_checked(self):
        result = self.compose()
        mesh = result["data"]["parts"][0]
        point = mesh["positions"][:3]
        source = result["data"]["meta"]["comparison"]["sources"][0]
        selection = {
            "kind": "surface", "partId": mesh["id"], "field": "Cp",
            "method": "native-triangle-barycentric-interpolation", "value": mesh["cp"][0],
            "displayPoint": point, "sourcePoint": [point[0], point[1] * mesh["sourceYSign"], point[2]],
            "sourceDataId": source["sourceId"],
            **{key: mesh[key] for key in ("sourceCaseId", "sourceSide", "sourceYSign", "sourcePartId")},
        }
        state = {"sourceId": result["data"]["meta"]["sourceKey"], "selection": selection}
        validate_state(state, result)
        selection["sourceDataId"] = "foreign-result"
        with self.assertRaisesRegex(ValueError, "data identity"):
            validate_state(state, result)
        selection["sourceDataId"] = source["sourceId"]
        selection["sourcePoint"][0] += .5
        with self.assertRaisesRegex(ValueError, "coordinates"):
            validate_state(state, result)


if __name__ == "__main__":
    unittest.main()
