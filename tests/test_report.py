"""Portable report packaging checks. Fixtures are synthetic, never team CFD data."""
from __future__ import annotations

import copy
from html.parser import HTMLParser
import json
from pathlib import Path
import tempfile
import unittest

from cfd_review.demo import make_demo_project
from cfd_review.report import build_report


class _ReportParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.external_assets = []
        self.project_chunks = []
        self.in_project = False
        self.csp = ""

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "script":
            if "src" in attrs:
                self.external_assets.append(attrs["src"])
            self.in_project = attrs.get("id") == "cfd-project-data"
        if tag == "link" and "href" in attrs:
            self.external_assets.append(attrs["href"])
        if tag == "meta" and attrs.get("http-equiv", "").lower() == "content-security-policy":
            self.csp = attrs.get("content", "")

    def handle_data(self, value):
        if self.in_project:
            self.project_chunks.append(value)

    def handle_endtag(self, tag):
        if tag == "script":
            self.in_project = False


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.output = Path(self.directory.name) / "portable.html"
        self.project = make_demo_project()

    def parse(self, output):
        parser = _ReportParser()
        parser.feed(Path(output).read_text(encoding="utf-8"))
        return parser

    def test_single_html_contains_complete_project_without_asset_dependencies(self):
        before = copy.deepcopy(self.project)
        result = build_report(self.project, self.output)
        self.assertEqual(Path(result).resolve(), self.output.resolve())
        parser = self.parse(result)
        self.assertEqual(parser.external_assets, [])
        self.assertIn("connect-src 'none'", parser.csp)
        self.assertEqual(json.loads("".join(parser.project_chunks)), before)
        self.assertEqual(self.project, before, "packaging must not mutate caller data")
        self.assertEqual(list(self.output.parent.iterdir()), [self.output])

    def test_case_input_is_wrapped_without_changing_raw_fields(self):
        case = copy.deepcopy(self.project["cases"][0])
        build_report(case, self.output)
        project = json.loads("".join(self.parse(self.output).project_chunks))
        self.assertEqual(project["schema"], "cfd-review-project")
        self.assertEqual(project["cases"], [case])
        self.assertEqual(project["views"][0]["caseId"], case["id"])

    def test_html_closing_script_and_unicode_remain_data(self):
        title = '</script><script>window.UNSAFE_REPORT=1</script> 压力 & "审阅"'
        self.project["title"] = title
        self.project["cases"][0]["name"] = title
        build_report(self.project, self.output)
        html = self.output.read_text(encoding="utf-8")
        parser = self.parse(self.output)
        restored = json.loads("".join(parser.project_chunks))
        self.assertEqual(restored["title"], title)
        self.assertEqual(restored["cases"][0]["name"], title)
        self.assertNotIn('<script>window.UNSAFE_REPORT=1</script>', html)

    def test_template_tokens_in_user_text_are_never_replaced(self):
        title = "{{STUDIO_JS}} {{PROJECT_JSON}} {{THREE_JS}}"
        self.project["title"] = title
        build_report(self.project, self.output)
        restored = json.loads("".join(self.parse(self.output).project_chunks))
        self.assertEqual(restored["title"], title)

    def test_missing_optional_fields_stay_missing(self):
        data = self.project["cases"][0]["data"]
        data["parts"][0].pop("cp")
        for section in data["sections"]:
            section.pop("cpt")
        build_report(self.project, self.output)
        restored = json.loads("".join(self.parse(self.output).project_chunks))
        self.assertEqual(restored["cases"][0]["data"], data)
        self.assertNotIn("cp", restored["cases"][0]["data"]["parts"][0])
        self.assertTrue(all("cpt" not in s for s in restored["cases"][0]["data"]["sections"]))

    def test_existing_file_is_preserved_without_explicit_overwrite(self):
        self.output.write_text("user-owned file", encoding="utf-8")
        with self.assertRaises(FileExistsError):
            build_report(self.project, self.output)
        self.assertEqual(self.output.read_text(encoding="utf-8"), "user-owned file")
        build_report(self.project, self.output, overwrite=True)
        self.assertEqual(json.loads("".join(self.parse(self.output).project_chunks)), self.project)

    def test_invalid_project_never_leaves_partial_html(self):
        for label, value in (("empty", {}), ("null", None), ("list", []),
                             ("wrong version", {**self.project, "version": 999}),
                             ("no cases", {**self.project, "cases": []})):
            with self.subTest(label=label):
                with self.assertRaises(ValueError):
                    build_report(value, self.output)
                self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main()
