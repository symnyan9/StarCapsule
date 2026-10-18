"""Optional saved UI preferences preserve scientific data and legacy projects."""
import copy
import unittest

from cfd_review.demo import make_demo_project
from cfd_review.schema import validate_project


class ProjectUiChecks(unittest.TestCase):
    def test_case_library_limit_matches_browser_and_html_bundle(self):
        project = make_demo_project()
        cases = [{**project["cases"][0], "id": f"source-{i}"} for i in range(33)]
        candidate = {**project, "cases": cases[:32], "views": [{"caseId": "source-0", "state": None}], "notes": []}
        self.assertIs(validate_project(candidate), candidate)
        with self.assertRaisesRegex(ValueError, "1 to 32"):
            validate_project({**candidate, "cases": cases})

    def test_sidebar_preference_is_boolean_optional_and_never_filled(self):
        project = make_demo_project()
        before = copy.deepcopy(project)
        self.assertIs(validate_project(project), project)
        self.assertEqual(project, before)
        self.assertNotIn("ui", project)
        for ui in ({}, {"sidebarCollapsed": True}, {"sidebarCollapsed": False}):
            candidate = {**project, "ui": copy.deepcopy(ui)}
            self.assertIs(validate_project(candidate), candidate)
            self.assertEqual(candidate["ui"], ui)
            self.assertEqual(candidate["cases"], before["cases"])
        for ui in (None, [], True, "hidden", {"sidebarCollapsed": 0},
                   {"sidebarCollapsed": 1}, {"sidebarCollapsed": None},
                   {"sidebarCollapsed": "true"}):
            with self.subTest(ui=ui), self.assertRaisesRegex(ValueError, "project.ui"):
                validate_project({**project, "ui": ui})


if __name__ == "__main__":
    unittest.main()
