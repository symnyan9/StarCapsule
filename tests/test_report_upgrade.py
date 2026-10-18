"""Saved-HTML upgrades use synthetic data and never open a native solver."""
from __future__ import annotations

import builtins
import contextlib
import copy
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from cfd_review.cli import main
from cfd_review.demo import make_demo_project
from cfd_review.report import build_report, load_report_document, upgrade_report
from cfd_review.templates import export_builtin_templates


class ReportUpgradeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "saved.html"
        self.output = self.root / "updated.html"
        self.project = make_demo_project()
        state = {"sourceId": self.project["cases"][0]["data"]["meta"]["sourceKey"],
                 "sectionIndex": 2, "variable": "CpT", "sectionVisible": True,
                 "hideNearOne": True, "sectionOpacity": .75}
        self.project["views"][0]["state"] = state
        self.project["notes"] = [{"id": "explanation", "caseId": self.project["cases"][0]["id"],
                                  "view": 0, "text": "Existing review note 压力", "state": copy.deepcopy(state)}]
        build_report(self.project, self.source)

    def test_upgrade_replaces_assets_preserving_source_and_entire_scientific_payload(self):
        html = self.source.read_text(encoding="utf-8")
        # Stale code is never copied or executed, even when its text is hostile.
        html = html.replace('<script id="studio-runtime">', '<script id="studio-runtime">throw new Error("STALE_SCRIPT");')
        self.source.write_text(html, encoding="utf-8")
        before = hashlib.sha256(self.source.read_bytes()).hexdigest()
        result = upgrade_report(self.source, self.output)
        self.assertEqual(result, self.output.resolve())
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(), before)
        self.assertEqual(load_report_document(result), self.project)
        self.assertNotIn("STALE_SCRIPT", self.output.read_text(encoding="utf-8"))
        self.assertEqual(self.project["views"][0]["state"]["sectionIndex"], 2)
        self.assertNotIn("cptTransparentAbove", load_report_document(result)["views"][0]["state"])

    def test_custom_template_can_be_selected_without_changing_project(self):
        template = export_builtin_templates(self.root / "templates")[0]
        upgrade_report(self.source, self.output, template=template)
        self.assertIn('class="engineering-blue"', self.output.read_text(encoding="utf-8"))
        self.assertEqual(load_report_document(self.output), self.project)

    def test_cli_upgrade_does_not_import_star_or_modify_source(self):
        original_import = builtins.__import__
        def no_star(name, *args, **kwargs):
            if name == "star" or name.endswith(".star"):
                raise AssertionError("Saved HTML upgrade must not import STAR adapter")
            return original_import(name, *args, **kwargs)
        source_hash = hashlib.sha256(self.source.read_bytes()).hexdigest()
        with patch("builtins.__import__", side_effect=no_star), contextlib.redirect_stdout(io.StringIO()):
            status = main(["upgrade", str(self.source), "-o", str(self.output)])
        self.assertEqual(status, 0)
        self.assertEqual(load_report_document(self.output), self.project)
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(), source_hash)

    def test_existing_output_and_same_source_require_explicit_force(self):
        self.output.write_text("preserved", encoding="utf-8")
        for destination in (self.source, self.output):
            before = destination.read_bytes()
            with self.assertRaises(FileExistsError):
                upgrade_report(self.source, destination)
            self.assertEqual(destination.read_bytes(), before)
        upgrade_report(self.source, self.output, overwrite=True)
        self.assertEqual(load_report_document(self.output), self.project)

    def test_invalid_source_never_replaces_existing_destination_even_with_force(self):
        self.output.write_text("preserved", encoding="utf-8")
        self.source.write_text("<html>not a report</html>", encoding="utf-8")
        with self.assertRaises(ValueError):
            upgrade_report(self.source, self.output, overwrite=True)
        self.assertEqual(self.output.read_text(encoding="utf-8"), "preserved")

    def test_script_slot_must_be_unique_inline_complete_and_correctly_typed(self):
        data = json.dumps(self.project)
        valid = '<script id="cfd-project-data" type="application/json">' + data + '</script>'
        variants = [valid + valid,
                    valid.replace('type="application/json"', 'type="text/javascript"'),
                    valid.replace('type="application/json"', 'type="application/json" src="remote.js"'),
                    valid.replace('<script ', '<div ').replace('</script>', '</div>'),
                    valid.replace('</script>', ''),
                    '<script id="cfd-project-data" type="application/json"/>',
                    valid.replace('id="cfd-project-data"', 'id="other" id="cfd-project-data"'),
                    '<!--' + valid + '-->',
                    '<script>const fake=\'' + valid.replace('</script>', '<\\/script>') + '\';</script>']
        for text in variants:
            with self.subTest(text=text[:100]):
                self.source.write_text(text, encoding="utf-8")
                with self.assertRaises(ValueError):
                    load_report_document(self.source)

    def test_strict_json_rejects_duplicate_keys_nonfinite_values_and_wrong_schema(self):
        variants = ['{"schema":"one","schema":"two"}',
                    '{"value":NaN}', '{"value":Infinity}',
                    json.dumps({**self.project, "version": 999}),
                    json.dumps(self.project["cases"][0]), '[]']
        for data in variants:
            with self.subTest(data=data[:60]):
                self.source.write_text('<script type="application/json" id="cfd-project-data">' + data + '</script>', encoding="utf-8")
                with self.assertRaises(ValueError):
                    load_report_document(self.source)

    def test_utf8_bom_and_script_safe_user_text_roundtrip(self):
        self.project["title"] = '</script><script>alert("never execute")</script> 压力 & {{STUDIO_JS}}'
        build_report(self.project, self.source, overwrite=True)
        self.source.write_bytes(b"\xef\xbb\xbf" + self.source.read_bytes())
        upgrade_report(self.source, self.output)
        self.assertEqual(load_report_document(self.output), self.project)
        self.assertNotIn('<script>alert("never execute")</script>', self.output.read_text(encoding="utf-8"))

    def test_size_limit_and_extension_validation_precede_rendering(self):
        with patch("cfd_review.report._MAX_REPORT_BYTES", 64):
            with self.assertRaisesRegex(ValueError, "input limit"):
                load_report_document(self.source)
        invalid = self.root / "not-html.json"
        invalid.write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "extension"):
            load_report_document(invalid)
        with self.assertRaisesRegex(ValueError, "extension"):
            upgrade_report(self.source, invalid.with_name("output.txt"))
        self.assertFalse(invalid.with_name("output.txt").exists())

    def bundled_html(self):
        with patch("cfd_review.report._BUNDLE_THRESHOLD_BYTES", 1):
            build_report(self.project, self.output, overwrite=True)
        return self.output.read_text(encoding="utf-8")

    def test_large_multicase_bundle_preserves_cases_states_notes_and_template_hooks(self):
        html = self.bundled_html()
        self.assertIn('"schema":"cfd-review-html-bundle"', html)
        self.assertIn('<script id="cfd-case-data-0" type="application/json">', html)
        self.assertIn('<script id="cfd-case-data-1" type="application/json">', html)
        self.assertEqual(load_report_document(self.output), self.project)
        with patch("cfd_review.report._BUNDLE_THRESHOLD_BYTES", 1):
            upgrade_report(self.output, self.source, overwrite=True)
        self.assertEqual(load_report_document(self.source), self.project)

    def test_bundle_stream_handles_utf8_and_closing_tags_split_across_small_chunks(self):
        html = self.bundled_html()
        # Ignore the old executable text while reading only exact reserved JSON slots.
        self.output.write_text(html.replace("</head>", '<script>throw Error("never execute");</script></head>'), encoding="utf-8")
        with patch("cfd_review.report._READ_CHUNK_BYTES", 127):
            self.assertEqual(load_report_document(self.output), self.project)

    def test_bundle_missing_duplicate_or_wrong_identity_slots_are_rejected(self):
        html = self.bundled_html()
        start = html.index('<script id="cfd-case-data-0"')
        end = html.index("</script>", start) + len("</script>")
        slot = html[start:end]
        variants = [html[:start] + html[end:],
                    html + slot,
                    html.replace('"elementId":"cfd-case-data-0"', '"elementId":"cfd-case-data-3"', 1),
                    html[:start] + slot.replace('"id":"synthetic-a"', '"id":"wrong-source"', 1) + html[end:],
                    html.replace('id="cfd-case-data-0"', 'id="cfd-case-data-7"', 1),
                    html.replace('"schema":"cfd-review-html-bundle","version":1',
                                 '"schema":"cfd-review-html-bundle","version":2', 1)]
        for text in variants:
            self.output.write_text(text, encoding="utf-8")
            with self.subTest(text=text[start:start + 100]):
                with self.assertRaises(ValueError):
                    load_report_document(self.output)

    def test_bundle_slot_limits_are_explicit_and_failed_write_leaves_no_partial_output(self):
        self.bundled_html()
        with patch("cfd_review.report._MAX_JSON_SLOT_BYTES", 64):
            with self.assertRaisesRegex(ValueError, "JSON slot.*input limit"):
                load_report_document(self.output)
            self.output.unlink()
            with self.assertRaisesRegex(ValueError, "500 MiB output limit"):
                build_report(self.project, self.output)
        self.assertFalse(self.output.exists())
        with patch("cfd_review.report._MAX_REPORT_BYTES", 1024):
            with self.assertRaisesRegex(ValueError, "output limit"):
                build_report(self.project, self.output)
        self.assertFalse(self.output.exists())

    def test_legacy_slot_rejects_unreferenced_case_scripts(self):
        extra = '<script id="cfd-case-data-0" type="application/json">{}</script>'
        self.source.write_text(self.source.read_text(encoding="utf-8") + extra, encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "unreferenced"):
            load_report_document(self.source)


if __name__ == "__main__":
    unittest.main()
