"""Language is presentation metadata; source names and numeric arrays stay intact."""
import copy
from pathlib import Path
import tempfile
import unittest

from cfd_review.demo import make_demo_project
from cfd_review.report import build_report, load_report_document
from cfd_review.schema import validate_project


class ReportLanguageChecks(unittest.TestCase):
    def test_missing_language_defaults_to_english_without_mutating_input(self):
        document = make_demo_project()
        document.pop("ui", None)
        before = copy.deepcopy(document)
        with tempfile.TemporaryDirectory() as folder:
            target = build_report(document, Path(folder) / "review.html")
            self.assertIn('<html lang="en">', target.read_text(encoding="utf-8"))
            self.assertEqual(load_report_document(target), before)
        self.assertEqual(document, before)

    def test_explicit_and_saved_languages_keep_scientific_data_and_titles(self):
        document = make_demo_project()
        document["title"] = "用户标题 · User title"
        document["cases"][0]["name"] = "原始部件名称 · Source name"
        before = copy.deepcopy(document)
        with tempfile.TemporaryDirectory() as folder:
            for language in ("en", "zh-CN"):
                target = build_report(document, Path(folder) / (language + ".html"), language=language)
                result = load_report_document(target)
                self.assertEqual(result["ui"]["language"], language)
                self.assertEqual(result["cases"], document["cases"])
                self.assertEqual(result["title"], document["title"])
                self.assertIn(f'<html lang="{language}">', target.read_text(encoding="utf-8"))
                saved = build_report(result, Path(folder) / (language + "-saved.html"))
                self.assertEqual(load_report_document(saved)["ui"]["language"], language)
        self.assertEqual(document, before)

    def test_invalid_ui_language_is_rejected_before_writing(self):
        for language in ("fr", "EN", "zh", "", None, True, [], {}):
            document = make_demo_project()
            document["ui"] = {"language": language}
            with self.subTest(language=language), self.assertRaisesRegex(ValueError, "project.ui.language"):
                validate_project(document)

    def test_invalid_override_preserves_existing_output(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "existing.html"
            target.write_bytes(b"original content")
            with self.assertRaisesRegex(ValueError, "Language"):
                build_report(make_demo_project(), target, overwrite=True, language="fr")
            self.assertEqual(target.read_bytes(), b"original content")
