"""Version-2 section slots use synthetic meshes only; no STAR or real datasets."""
from __future__ import annotations

import copy
import json
import math
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

from cfd_review.comparison import compose_half_comparison
from cfd_review.report import (_case_summary, _decompress_document, _json_payload, _prepare_json_slot,
                               _section_reference, build_report, load_report_document,
                               project_from_cases, upgrade_report)
from cfd_review.schema import validate_project


def original(case_id):
    triangle = {"positions": [-0.0, 0, .1, .2, .2, .1, .4, .2, .3], "indices": [0, 1, 2]}
    fields = {"cp": [-0.0, 1e-300, .12345678901234568], "cpt": [1.0, .9, .8]}
    return {"schema": "cfd-review-case", "version": 1, "id": case_id, "name": "Synthetic " + case_id,
            "data": {"meta": {"title": case_id, "source": "Synthetic section-slot fixture",
                              "sourceKey": "synthetic:" + case_id, "units": "m", "axis": {"up": "z"},
                              "isDemo": True, "halfCar": True, "mirrorAxis": "y", "scalarMirror": True,
                              "ranges": {"Cp": [-3, 1], "CpT": [-.5, 1]}, "surfaceRange": [-3, 1]},
                     "parts": [{"id": "wall", "name": "Synthetic wall", **copy.deepcopy(triangle),
                                **copy.deepcopy(fields), "customLabel": "Pressure Ω"}],
                     "layers": [{"id": "q", "name": "Synthetic Q", "kind": "isosurface",
                                 **copy.deepcopy(triangle), "values": [-0.0, 1e-280, 1], "field": "Q",
                                 "units": "1/s²", "colorRange": [-1, 1], "criterion": "Q", "threshold": 1500}],
                     "sections": [{"x": x, "positions": [x, 0, .1, x, .2, .1, x, .2, .4],
                                   "indices": [0, 1, 2], **copy.deepcopy(fields)}
                                  for x in (-0.0, .25, .5)]}}


class LazyReportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "lazy.html"
        self.a, self.b = original("case-a"), original("case-b")
        self.project = project_from_cases([self.a, self.b])
        self.project["ui"] = {"language": "en", "mobileMode": "auto", "sidebarCollapsed": True}
        state = {"sourceId": self.a["data"]["meta"]["sourceKey"], "sectionIndex": 1,
                 "variable": "CpT", "sectionVisible": True, "hideNearOne": True}
        self.project["views"] = [{"caseId": self.a["id"], "state": copy.deepcopy(state)}]
        self.project["notes"] = [{"id": "synthetic-note", "caseId": self.a["id"], "view": 0,
                                  "text": "Synthetic pressure review 压力", "state": state}]

    def build(self, project=None, *, compressed=False):
        with patch("cfd_review.report._SECTION_BUNDLE_THRESHOLD_BYTES", 1), patch(
                "cfd_review.report._COMPRESSION_THRESHOLD_BYTES", 1 if compressed else 10**12), patch(
                "cfd_review.report._SECTION_COMPRESSION_THRESHOLD_BYTES", 1 if compressed else 10**12):
            build_report(project or self.project, self.path, overwrite=True)
        return self.documents()

    def documents(self):
        pattern = r'<script id="(cfd-(?:project-data|case-data-\d+|section-data-\d+-\d+|layer-data-\d+-\d+))" type="application/json">(.*?)</script>'
        return {name: json.loads(text) for name, text in re.findall(pattern, self.path.read_text(encoding="utf-8"), re.S)}

    def write_documents(self, documents):
        self.path.write_text("\n".join('<script id="' + name + '" type="application/json">' +
                                      _json_payload(value) + '</script>' for name, value in documents.items()), encoding="utf-8")

    def test_small_legacy_and_version_one_bundles_remain_compatible(self):
        build_report(self.project, self.path)
        self.assertEqual(self.documents()["cfd-project-data"], self.project)
        self.assertEqual(load_report_document(self.path), self.project)
        with patch("cfd_review.report._BUNDLE_THRESHOLD_BYTES", 1):
            build_report(self.project, self.path, overwrite=True)
        self.assertEqual(self.documents()["cfd-project-data"]["version"], 1)
        self.assertEqual(load_report_document(self.path), self.project)

    def test_default_decoded_threshold_uses_v2_even_for_one_case(self):
        project = project_from_cases([self.a])
        # A compressible synthetic metadata string exercises the actual 8 MiB
        # decoded threshold without allocating millions of fake CFD samples.
        project["cases"][0]["data"]["meta"]["syntheticPayload"] = "Synthetic " * 900000
        with patch("cfd_review.report._json_payload", side_effect=AssertionError("aggregate JSON is forbidden")):
            build_report(project, self.path)
        primary = self.documents()["cfd-project-data"]
        if primary.get("schema") == "cfd-review-compressed":
            primary, _ = _decompress_document(primary)
        self.assertEqual(primary["schema"], "cfd-review-html-bundle")
        self.assertEqual(primary["version"], 2)
        self.assertEqual(load_report_document(self.path), project)

    def test_v2_core_summary_sections_state_and_numeric_precision_roundtrip(self):
        before = copy.deepcopy(self.project)
        docs = self.build()
        manifest = docs["cfd-project-data"]
        self.assertEqual(manifest["version"], 2)
        self.assertNotIn("cases", manifest["project"])
        for index, case in enumerate(self.project["cases"]):
            entry = manifest["cases"][index]
            self.assertEqual(entry["summary"], _case_summary(case))
            self.assertEqual(entry["summary"]["parts"][0]["fields"], ["cp", "cpt"])
            self.assertEqual(entry["summary"]["layers"][0]["fields"], ["values"])
            self.assertNotIn("positions", entry["summary"]["parts"][0])
            core = docs[entry["elementId"]]
            self.assertEqual(core["data"]["sections"], [])
            self.assertEqual(core["data"]["layers"], [])
            self.assertEqual(core["data"]["parts"], case["data"]["parts"])
            self.assertEqual(entry["decodedBytes"], len(_json_payload(core).encode("utf-8")))
            self.assertEqual(entry["numericValues"], 18)
            layer_ref = entry["layerSlots"][0]
            self.assertEqual(docs[layer_ref["elementId"]], case["data"]["layers"][0])
            self.assertEqual(layer_ref["numericValues"], 15)
            self.assertEqual(layer_ref["decodedBytes"], len(_json_payload(docs[layer_ref["elementId"]]).encode("utf-8")))
            for section_index, cut in enumerate(case["data"]["sections"]):
                descriptor = entry["sections"][section_index]
                self.assertEqual(descriptor, _section_reference(cut, index, section_index))
                self.assertEqual(docs[descriptor["elementId"]], cut)
        restored = load_report_document(self.path)
        self.assertEqual(restored, before)
        self.assertEqual(self.project, before, "writing cannot move sections out of the caller's case")
        for case in restored["cases"]:
            for cut in case["data"]["sections"]:
                self.assertEqual(math.copysign(1, cut["cp"][0]), -1)
                self.assertEqual(cut["cp"][1], 1e-300)
                self.assertEqual(cut["cp"][2], .12345678901234568)
            self.assertEqual(math.copysign(1, case["data"]["layers"][0]["values"][0]), -1)

    def test_gzip_sections_and_small_feed_chunks_roundtrip(self):
        docs = self.build(compressed=True)
        self.assertTrue(all(value["schema"] == "cfd-review-compressed" for value in docs.values()))
        with patch("cfd_review.report._READ_CHUNK_BYTES", 127):
            self.assertEqual(load_report_document(self.path), self.project)

    def test_empty_sections_and_missing_optional_layers_remain_absent(self):
        self.project["cases"][0]["data"]["sections"] = []
        self.project["cases"][0]["data"].pop("layers")
        self.project["views"][0]["state"] = None
        self.project["notes"] = []
        docs = self.build()
        entry = docs["cfd-project-data"]["cases"][0]
        self.assertEqual(entry["sections"], [])
        self.assertEqual(entry["summary"]["layers"], [])
        self.assertEqual(load_report_document(self.path), self.project)

    def test_compact_recipe_can_precede_originals_with_full_provenance(self):
        derived = compose_half_comparison(self.a, self.b, case_id="synthetic-comparison")
        project = project_from_cases([derived, self.a, self.b])
        project["ui"] = {"mobileMode": "on", "language": "zh-CN"}
        docs = self.build(project)
        entry = docs["cfd-project-data"]["cases"][0]
        self.assertEqual(set(entry), {"id", "elementId"})
        self.assertEqual(docs[entry["elementId"]]["schema"], "cfd-review-composition")
        self.assertNotIn("cfd-section-data-0-0", docs)
        self.assertEqual(load_report_document(self.path), project)
        docs[entry["elementId"]]["meta"]["comparison"]["sources"][0]["sourceId"] = "forged"
        self.write_documents(docs)
        with self.assertRaisesRegex(ValueError, "identity differs"):
            load_report_document(self.path)

    def test_legacy_full_comparison_keeps_its_identity_and_section_ranges_in_v2(self):
        derived = compose_half_comparison(self.a, self.b, case_id="legacy-full-comparison")
        derived["data"]["meta"]["sourceKey"] = "synthetic:legacy-comparison-identity"
        project = project_from_cases([self.a, self.b, derived])
        docs = self.build(project)
        entry = docs["cfd-project-data"]["cases"][2]
        self.assertEqual(set(entry), {"id", "elementId", "summary", "sections", "decodedBytes", "numericValues", "layerSlots"})
        self.assertEqual(entry["sections"][0]["comparisonRanges"], derived["data"]["sections"][0]["comparisonRanges"])
        self.assertEqual(load_report_document(self.path), project)

    def test_missing_duplicate_malformed_and_unreferenced_slots_rejected(self):
        docs = self.build()
        missing = copy.deepcopy(docs)
        missing.pop("cfd-section-data-0-0")
        extra = copy.deepcopy(docs)
        extra["cfd-section-data-0-9"] = copy.deepcopy(docs["cfd-section-data-0-0"])
        for changed in (missing, extra):
            self.write_documents(changed)
            with self.assertRaises(ValueError):
                load_report_document(self.path)
        self.write_documents(docs)
        original_html = self.path.read_text(encoding="utf-8")
        cut = '<script id="cfd-section-data-0-0" type="application/json">{}</script>'
        variants = [original_html + cut,
                    original_html.replace('id="cfd-section-data-0-0"', 'id="cfd-section-data-00-0"', 1),
                    original_html.replace('id="cfd-section-data-0-0"', 'id="cfd-section-data-0-10000"', 1),
                    original_html.replace('id="cfd-section-data-0-0" type="application/json"',
                                          'id="cfd-section-data-0-0" type="application/json" src="remote.js"', 1),
                    original_html + '<script id="cfd-section-data-0-9" type="application/json"/>']
        for html in variants:
            self.path.write_text(html, encoding="utf-8")
            with self.subTest(html=html[-90:]), self.assertRaises(ValueError):
                load_report_document(self.path)

    def test_summary_and_section_descriptor_tampering_rejected(self):
        docs = self.build()
        mutations = [lambda entry: entry["summary"].update(name="forged"),
                     lambda entry: entry["summary"]["meta"].update(isDemo=1),
                     lambda entry: entry["summary"]["parts"][0].update(fields=[]),
                     lambda entry: entry["sections"][0].update(x=100),
                     lambda entry: entry["sections"][0].update(fields=["cp"]),
                     lambda entry: entry["sections"][0].update(vertexCount=4),
                     lambda entry: entry["sections"][0].update(indexCount=3.0),
                     lambda entry: entry["sections"][0].update(comparisonRanges=[]),
                     lambda entry: entry["sections"][0].update(extra="forged"),
                     lambda entry: entry["sections"].reverse(),
                     lambda entry: entry.update(extra="forged")]
        for mutate in mutations:
            changed = copy.deepcopy(docs)
            mutate(changed["cfd-project-data"]["cases"][0])
            self.write_documents(changed)
            with self.subTest(mutation=mutate), self.assertRaises(ValueError):
                load_report_document(self.path)

    def test_section_comparison_metadata_and_browser_number_semantics(self):
        self.project["cases"][0]["data"]["sections"][0]["comparisonRanges"] = [{"source": "synthetic", "start": 0, "count": 3}]
        docs = self.build()
        descriptor = docs["cfd-project-data"]["cases"][0]["sections"][0]
        self.assertEqual(descriptor["comparisonRanges"], [{"source": "synthetic", "start": 0, "count": 3}])
        descriptor["x"] = 0  # JSON.stringify does not retain a distinct -0.0 token.
        docs["cfd-project-data"]["cases"][0]["summary"]["meta"]["ranges"]["CpT"][0] = -.5
        self.write_documents(docs)
        result = load_report_document(self.path)
        self.assertEqual(result, self.project)
        self.assertEqual(math.copysign(1, result["cases"][0]["data"]["sections"][0]["x"]), -1)

    def large_section_project(self):
        project = copy.deepcopy(self.project)
        for case in project["cases"]:
            for section in case["data"]["sections"]:
                for field in ("positions", "cp", "cpt"):
                    section[field] *= 60
                section["indices"] = list(range(180))
        return project

    def test_aggregate_case_budget_applies_to_reader_and_writer(self):
        project = self.large_section_project()
        docs = self.build(project)
        limit = max(len(_json_payload(value).encode("utf-8")) for value in docs.values()) + 1
        self.write_documents(docs)
        with patch("cfd_review.report._MAX_JSON_SLOT_BYTES", limit):
            with self.assertRaisesRegex(ValueError, "case core and sections exceed"):
                load_report_document(self.path)
            output = self.path.with_name("over-budget.html")
            with patch("cfd_review.report._SECTION_BUNDLE_THRESHOLD_BYTES", 1), patch(
                    "cfd_review.report._COMPRESSION_THRESHOLD_BYTES", 10**12), self.assertRaisesRegex(
                        ValueError, "case core and sections exceed"):
                build_report(project, output)
            self.assertFalse(output.exists())

    def test_section_and_slot_limits_and_final_numeric_guard_remain_active(self):
        docs = self.build()
        with patch("cfd_review.report._MAX_REPORT_SECTIONS", 2), self.assertRaises(ValueError):
            load_report_document(self.path)
        with patch("cfd_review.report._MAX_DATA_SLOTS", 3), self.assertRaisesRegex(ValueError, "data-slot"):
            load_report_document(self.path)
        with patch("cfd_review.schema._JSON_NUMERIC_LIMIT", 20), self.assertRaisesRegex(ValueError, "numeric-data"):
            load_report_document(self.path)
        with patch("cfd_review.report._MAX_REPORT_SECTIONS", 2), patch(
                "cfd_review.report._SECTION_BUNDLE_THRESHOLD_BYTES", 1), self.assertRaisesRegex(ValueError, "section"):
            build_report(self.project, self.path, overwrite=True)
        self.write_documents(docs)

    def test_spools_are_closed_on_mid_section_failure_and_existing_output_preserved(self):
        self.path.write_bytes(b"existing report")
        original_temporary = tempfile.TemporaryFile
        opened, peak, active = [], [0], [0]
        class Tracked:
            def __init__(self, handle):
                self.handle = handle
                self.closed = False
                active[0] += 1
                peak[0] = max(peak[0], active[0])
            def __getattr__(self, key):
                return getattr(self.handle, key)
            def close(self):
                if not self.closed:
                    self.closed = True
                    active[0] -= 1
                    self.handle.close()
            def __enter__(self):
                return self
            def __exit__(self, *args):
                self.close()
        def spool(*args, **kwargs):
            result = Tracked(original_temporary(*args, **kwargs))
            opened.append(result)
            return result
        from cfd_review import report
        prepare = report._prepare_json_slot
        def fail_on_second_cut(value, **kwargs):
            if value.get("x") == .25:
                raise OSError("Synthetic section failure")
            return prepare(value, **kwargs)
        with patch("cfd_review.report._SECTION_BUNDLE_THRESHOLD_BYTES", 1), patch(
                "cfd_review.report.tempfile.TemporaryFile", side_effect=spool), patch(
                "cfd_review.report._prepare_json_slot", side_effect=fail_on_second_cut), self.assertRaisesRegex(
                    OSError, "Synthetic section failure"):
            build_report(self.project, self.path, overwrite=True)
        self.assertEqual(active[0], 0)
        self.assertTrue(all(handle.closed for handle in opened))
        self.assertLessEqual(peak[0], 2, "only primary and current plain slot should remain open")
        self.assertEqual(self.path.read_bytes(), b"existing report")
        self.assertEqual(set(self.path.parent.iterdir()), {self.path})

    def test_mobile_mode_enum_and_upgrade_preserve_preferences(self):
        for mode in ("auto", "on", "off"):
            self.project["ui"]["mobileMode"] = mode
            self.assertIs(validate_project(self.project), self.project)
        for mode in (True, "mobile", None, [], 1):
            self.project["ui"]["mobileMode"] = mode
            with self.subTest(mode=mode), self.assertRaisesRegex(ValueError, "mobileMode"):
                validate_project(self.project)
        self.project["ui"]["mobileMode"] = "on"
        self.build()
        upgraded = self.path.with_name("upgraded.html")
        with patch("cfd_review.report._SECTION_BUNDLE_THRESHOLD_BYTES", 1):
            upgrade_report(self.path, upgraded)
        self.assertEqual(load_report_document(upgraded), self.project)

    def test_older_v2_inline_layers_without_declared_budgets_remain_compatible(self):
        docs = self.build()
        for entry in docs["cfd-project-data"]["cases"]:
            core = docs[entry["elementId"]]
            core["data"]["layers"] = [docs.pop(layer["elementId"]) for layer in entry.pop("layerSlots")]
            for ref in [entry, *entry["sections"]]:
                ref.pop("decodedBytes")
                ref.pop("numericValues")
        self.write_documents(docs)
        self.assertEqual(load_report_document(self.path), self.project)

    def test_layer_only_case_keeps_its_valid_inline_core(self):
        project = project_from_cases([self.a])
        project["cases"][0]["data"]["parts"] = []
        docs = self.build(project)
        entry = docs["cfd-project-data"]["cases"][0]
        self.assertNotIn("layerSlots", entry)
        self.assertTrue(docs[entry["elementId"]]["data"]["layers"])
        self.assertEqual(entry["numericValues"], 15)
        self.assertEqual(load_report_document(self.path), project)

    def test_layer_slot_budget_summary_references_and_payload_tampering_rejected(self):
        docs = self.build()
        mutations = [lambda d: d.pop("cfd-layer-data-0-0"),
                     lambda d: d.update({"cfd-layer-data-0-1": d["cfd-layer-data-0-0"]}),
                     lambda d: d["cfd-project-data"]["cases"][0]["layerSlots"][0].update(elementId="cfd-layer-data-0-1"),
                     lambda d: d["cfd-project-data"]["cases"][0]["layerSlots"][0].update(decodedBytes=1),
                     lambda d: d["cfd-project-data"]["cases"][0]["layerSlots"][0].update(numericValues=15.0),
                     lambda d: d["cfd-project-data"]["cases"][0].update(decodedBytes=1),
                     lambda d: d["cfd-project-data"]["cases"][0].update(numericValues=True),
                     lambda d: d["cfd-project-data"]["cases"][0]["sections"][0].update(decodedBytes=1),
                     lambda d: d["cfd-project-data"]["cases"][0]["sections"][0].update(numericValues=0),
                     lambda d: d["cfd-layer-data-0-0"].update(name="Changed layer metadata")]
        for mutate in mutations:
            changed = copy.deepcopy(docs)
            mutate(changed)
            self.write_documents(changed)
            with self.subTest(mutation=mutate), self.assertRaises(ValueError):
                load_report_document(self.path)
        self.write_documents(docs)
        html = self.path.read_text(encoding="utf-8")
        for changed in (html + '<script id="cfd-layer-data-0-0" type="application/json">{}</script>',
                        html.replace('id="cfd-layer-data-0-0"', 'id="cfd-layer-data-0-1000"', 1),
                        html.replace('id="cfd-layer-data-0-0"', 'id="cfd-layer-data-00-0"', 1),
                        html + '<script id="cfd-layer-data-0-9" type="application/json"/>'):
            self.path.write_text(changed, encoding="utf-8")
            with self.assertRaises(ValueError):
                load_report_document(self.path)

    def test_layer_bytes_share_case_budget_and_layer_count_remains_bounded(self):
        project = project_from_cases([self.a])
        layer = project["cases"][0]["data"]["layers"][0]
        for field in ("positions", "values"):
            layer[field] *= 60
        layer["indices"] = list(range(180))
        docs = self.build(project)
        limit = max(len(_json_payload(value).encode("utf-8")) for value in docs.values()) + 1
        self.write_documents(docs)
        with patch("cfd_review.report._MAX_JSON_SLOT_BYTES", limit):
            with self.assertRaisesRegex(ValueError, "including layers"):
                load_report_document(self.path)
            with patch("cfd_review.report._SECTION_BUNDLE_THRESHOLD_BYTES", 1), self.assertRaisesRegex(ValueError, "including layers"):
                build_report(project, self.path.with_name("layer-over-budget.html"))
        with patch("cfd_review.report._MAX_REPORT_LAYERS", 0):
            with self.assertRaisesRegex(ValueError, "layer"):
                load_report_document(self.path)
            with patch("cfd_review.report._SECTION_BUNDLE_THRESHOLD_BYTES", 1), self.assertRaisesRegex(ValueError, "layer"):
                build_report(project, self.path, overwrite=True)

    def test_v2_medium_section_compresses_without_changing_raw_values_or_decoded_bytes(self):
        project = project_from_cases([self.a])
        cut = project["cases"][0]["data"]["sections"][0]
        for field in ("positions", "cp", "cpt"):
            cut[field] *= 1000
        cut["indices"] = list(range(3000))
        project["cases"][0]["data"]["sections"] = [cut]
        raw = _json_payload(cut).encode("utf-8")
        self.assertGreaterEqual(len(raw), 64 * 1024)
        self.assertLess(len(raw), 1024 * 1024)
        # Legacy callers retain the one-MiB default; only v2 opts into 64 KiB.
        stream, size = _prepare_json_slot(cut)
        with stream:
            self.assertEqual(stream.read(), raw)
            self.assertEqual(size, len(raw))
        with patch("cfd_review.report._SECTION_BUNDLE_THRESHOLD_BYTES", 1):
            build_report(project, self.path)
        docs = self.documents()
        envelope = docs["cfd-section-data-0-0"]
        self.assertEqual(envelope["schema"], "cfd-review-compressed")
        self.assertEqual(envelope["decodedBytes"], len(raw))
        self.assertEqual(docs["cfd-project-data"]["cases"][0]["sections"][0]["decodedBytes"], len(raw))
        decoded, decoded_bytes = _decompress_document(envelope)
        self.assertEqual(decoded_bytes, len(raw))
        self.assertEqual(_json_payload(decoded).encode("utf-8"), raw)
        self.assertEqual(math.copysign(1, decoded["cp"][0]), -1)
        self.assertEqual(decoded["cp"][1], 1e-300)
        self.assertEqual(load_report_document(self.path), project)


if __name__ == "__main__":
    unittest.main()
