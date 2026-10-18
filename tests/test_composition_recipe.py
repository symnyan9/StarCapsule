"""Compact HTML recipes retain synthetic originals and checked provenance."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

from cfd_review.comparison import compose_half_comparison
from cfd_review.report import build_report, load_report_document, project_from_cases, upgrade_report


def original(case_id):
    """A tiny, explicitly synthetic half-model with real stored plane arrays."""
    tri = {"positions": [0, 0, .2, 1, .2, .2, 0, .3, .4], "indices": [0, 1, 2]}
    sections = [{"x": x, "positions": [x, 0, .1, x, .2, .1, x, .2, .4],
                 "indices": [0, 1, 2], "cp": [.1, -.2, -.3], "cpt": [1.05, .9, .8]}
                for x in (0, .5)]
    return {"schema": "cfd-review-case", "version": 1, "id": case_id, "name": case_id,
            "data": {"meta": {"title": case_id, "source": "Synthetic recipe fixture",
                     "sourceKey": "synthetic:" + case_id, "units": "m", "axis": {"up": "z"},
                     "isDemo": True, "halfCar": True, "mirrorAxis": "y", "scalarMirror": True,
                     "ranges": {"Cp": [-3, 1], "CpT": [-.5, 1]}, "surfaceRange": [-3, 1]},
                     "parts": [{"id": "wall", "name": "Synthetic wall", **copy.deepcopy(tri), "cp": [.1, .2, .3]}],
                     "sections": sections,
                     "layers": [{"id": "q", "name": "Synthetic Q", "kind": "isosurface",
                                 **copy.deepcopy(tri), "criterion": "Q", "threshold": 1500}]}}


class CompositionRecipeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "recipe.html"
        self.a, self.b = original("original-a"), original("original-b")
        self.composed = compose_half_comparison(self.a, self.b, case_id="display-pair", name="Synthetic comparison")
        self.composed["data"]["meta"]["cptTransparentAbove"] = 1.03
        self.composed["data"]["meta"]["ranges"]["Cp"] = [-4, 2]
        self.project = project_from_cases([self.a, self.b, self.composed])
        self.project["ui"] = {"sidebarCollapsed": True}
        state = {"sourceId": self.composed["data"]["meta"]["sourceKey"], "variable": "CpT", "sectionIndex": 1,
                 "cptTransparentAbove": 1.03, "hideNearOne": True}
        self.project["views"] = [{"caseId": self.composed["id"], "state": copy.deepcopy(state)}]
        self.project["notes"] = [{"id": "recipe-note", "caseId": self.composed["id"], "view": 0,
                                  "text": "Synthetic retained comment", "state": state}]

    def recipe(self):
        return {"schema": "cfd-review-composition", "version": 1, "id": self.composed["id"],
                "name": self.composed["name"], "meta": copy.deepcopy(self.composed["data"]["meta"])}

    def write_bundle(self, slots=None, project=None):
        slots = slots if slots is not None else [self.a, self.b, self.recipe()]
        project = project if project is not None else self.project
        manifest = {"schema": "cfd-review-html-bundle", "version": 1,
                    "project": {k: v for k, v in project.items() if k != "cases"},
                    "cases": [{"id": case["id"], "elementId": f"cfd-case-data-{i}"} for i, case in enumerate(slots)]}
        html = '<script id="cfd-project-data" type="application/json">' + json.dumps(manifest) + '</script>'
        for i, case in enumerate(slots):
            html += f'<script id="cfd-case-data-{i}" type="application/json">' + json.dumps(case) + '</script>'
        self.path.write_text(html, encoding="utf-8")

    def test_writer_stores_only_original_arrays_and_recipe_roundtrips_entire_project(self):
        before = copy.deepcopy(self.project)
        build_report(self.project, self.path)
        html = self.path.read_text(encoding="utf-8")
        slot = re.search(r'<script id="cfd-case-data-2" type="application/json">(.*?)</script>', html, re.S)
        self.assertIsNotNone(slot)
        stored = json.loads(slot[1])
        self.assertEqual(stored, self.recipe())
        self.assertNotIn('"positions"', slot[1])
        self.assertEqual(load_report_document(self.path), before)
        self.assertEqual(self.project, before)
        # The source A reflection changes winding while keeping original fields.
        result = load_report_document(self.path)["cases"][2]
        self.assertEqual(result["data"]["parts"][0]["indices"], [0, 2, 1])
        self.assertEqual(result["data"]["parts"][0]["cp"], self.a["data"]["parts"][0]["cp"])

    def test_recipe_can_precede_its_originals_in_bundle_manifest(self):
        self.write_bundle([self.recipe(), self.a, self.b])
        result = load_report_document(self.path)
        self.assertEqual(result["cases"], [self.composed, self.a, self.b])

    def test_existing_full_case_bundle_and_legacy_report_remain_readable(self):
        self.write_bundle([self.a, self.b, self.composed])
        self.assertEqual(load_report_document(self.path), self.project)
        self.path.write_text('<script id="cfd-project-data" type="application/json">' +
                             json.dumps(self.project) + '</script>', encoding="utf-8")
        self.assertEqual(load_report_document(self.path), self.project)

    def test_upgrade_full_case_legacy_report_replaces_duplicate_arrays_with_recipe(self):
        self.path.write_text('<script id="cfd-project-data" type="application/json">' +
                             json.dumps(self.project) + '</script>', encoding="utf-8")
        output = self.path.with_name("upgraded.html")
        upgrade_report(self.path, output)
        self.assertEqual(load_report_document(output), self.project)
        self.assertIn('"schema":"cfd-review-composition"', output.read_text(encoding="utf-8"))

    def test_extra_fields_wrong_schema_version_and_invalid_names_are_rejected(self):
        variants = []
        for key, value in (("unexpected", {}), ("data", {}), ("schema", "other"), ("version", True),
                           ("version", 2), ("id", ""), ("id", "constructor"), ("name", ""), ("meta", [])):
            recipe = self.recipe()
            recipe[key] = value
            variants.append(recipe)
        for recipe in variants:
            with self.subTest(recipe=recipe):
                self.write_bundle([self.a, self.b, recipe])
                with self.assertRaises(ValueError):
                    load_report_document(self.path)

    def test_recipe_id_must_match_manifest(self):
        self.write_bundle()
        html = self.path.read_text(encoding="utf-8")
        html = html.replace('"id": "display-pair", "elementId"', '"id": "foreign-id", "elementId"', 1)
        self.path.write_text(html, encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "ID differs"):
            load_report_document(self.path)

    def test_recipe_identity_must_be_derived_and_recipe_size_is_bounded(self):
        for field, value in (("sourceKey", "other-derived-identity"), ("sourceSha256", "a" * 64)):
            recipe = self.recipe()
            recipe["meta"][field] = value
            self.write_bundle([self.a, self.b, recipe])
            with self.assertRaisesRegex(ValueError, "derived sourceKey"):
                load_report_document(self.path)
        self.write_bundle()
        with patch("cfd_review.report._MAX_COMPOSITION_RECIPE_BYTES", 64):
            with self.assertRaisesRegex(ValueError, "1 MiB input limit"):
                load_report_document(self.path)
            self.path.unlink()
            with self.assertRaisesRegex(ValueError, "1 MiB output limit"):
                build_report(self.project, self.path)
        self.assertFalse(self.path.exists())

    def test_full_legacy_comparison_with_noncanonical_identity_is_not_rewritten(self):
        derived = self.project["cases"][2]
        derived["data"]["meta"]["sourceKey"] = "legacy-comparison-identity"
        self.project["views"][0]["state"]["sourceId"] = "legacy-comparison-identity"
        self.project["notes"][0]["state"]["sourceId"] = "legacy-comparison-identity"
        build_report(self.project, self.path)
        self.assertEqual(load_report_document(self.path), self.project)
        self.assertNotIn('"schema":"cfd-review-composition"', self.path.read_text(encoding="utf-8"))

    def test_missing_duplicate_forged_and_recipe_sources_are_rejected_before_composition(self):
        variants = []
        for field, value in (("caseId", "missing-case"), ("caseId", self.composed["id"]),
                             ("caseId", self.b["id"]), ("sourceId", "forged-result")):
            recipe = self.recipe()
            recipe["meta"]["comparison"]["sources"][0][field] = value
            variants.append(recipe)
        for recipe in variants:
            with self.subTest(recipe=recipe):
                self.write_bundle([self.a, self.b, recipe])
                with patch("cfd_review.comparison.compose_half_comparison", side_effect=AssertionError("Must reject before building geometry")):
                    with self.assertRaises(ValueError):
                        load_report_document(self.path)

    def test_recipe_cannot_reference_another_recipe_or_cycle(self):
        first, second = self.recipe(), self.recipe()
        second["id"] = "second-recipe"
        second["meta"]["sourceKey"] = "half-stitch:" + second["id"]
        first["meta"]["comparison"]["sources"][0]["caseId"] = second["id"]
        second["meta"]["comparison"]["sources"][0]["caseId"] = first["id"]
        self.write_bundle([self.a, self.b, first, second])
        with self.assertRaisesRegex(ValueError, "original non-comparison"):
            load_report_document(self.path)

    def test_recipe_cannot_reference_a_retained_full_comparison(self):
        recipe = self.recipe()
        recipe["id"] = "another-comparison"
        recipe["meta"]["sourceKey"] = "half-stitch:" + recipe["id"]
        recipe["meta"]["comparison"]["sources"][0]["caseId"] = self.composed["id"]
        self.write_bundle([self.a, self.b, self.composed, recipe])
        with self.assertRaisesRegex(ValueError, "original non-comparison"):
            load_report_document(self.path)

    def test_invalid_meta_mapping_provenance_and_ranges_are_rejected(self):
        variants = []
        for mutate in (lambda m: m.update(halfCar=True),
                       lambda m: m.update(ranges={"Cp": [0, 0], "CpT": [-.5, 1]}),
                       lambda m: m["comparison"].update(version=True),
                       lambda m: m["comparison"].update(sourceSectionXs=[[999], [999]]),
                       lambda m: m["comparison"].update(coefficientReferences=[{}, {}]),
                       lambda m: m["comparison"]["sources"][0].update(sourceYSign=1),
                       lambda m: m["comparison"]["sources"][0].update(sourceKey="forged")):
            recipe = self.recipe()
            mutate(recipe["meta"])
            variants.append(recipe)
        for recipe in variants:
            with self.subTest(recipe=recipe):
                self.write_bundle([self.a, self.b, recipe])
                with self.assertRaises(ValueError):
                    load_report_document(self.path)

    def test_recipe_never_invents_common_x_or_missing_fields(self):
        self.b["data"]["sections"] = self.b["data"]["sections"][:1]
        self.composed = compose_half_comparison(self.a, self.b, case_id="display-pair")
        self.project = project_from_cases([self.a, self.b, self.composed])
        build_report(self.project, self.path)
        result = load_report_document(self.path)
        self.assertEqual(result, self.project)
        self.assertEqual([s["x"] for s in result["cases"][2]["data"]["sections"]], [0])
        self.b["data"]["sections"] = []
        self.composed = compose_half_comparison(self.a, self.b, case_id="display-pair")
        self.project = project_from_cases([self.a, self.b, self.composed])
        build_report(self.project, self.path, overwrite=True)
        self.assertEqual(load_report_document(self.path)["cases"][2]["data"]["sections"], [])

    def test_expanded_numeric_budget_is_checked_before_any_geometry_allocation(self):
        self.write_bundle()
        # Each source and the stored recipe are below this synthetic bound; the
        # expanded three-case project is above it. No large fixtures are needed.
        with patch("cfd_review.schema._JSON_NUMERIC_LIMIT", 200), patch(
                "cfd_review.comparison.compose_half_comparison",
                side_effect=AssertionError("Budget rejection must precede geometry allocation")) as compose:
            with self.assertRaisesRegex(ValueError, "JSON numeric-data limit"):
                load_report_document(self.path)
            compose.assert_not_called()


if __name__ == "__main__":
    unittest.main()
