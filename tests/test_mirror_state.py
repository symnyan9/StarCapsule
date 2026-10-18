"""Saved mirror display is explicit, source-preserving and separate from half declarations."""
import copy
import unittest

from cfd_review.comparison import compose_half_comparison
from cfd_review.demo import make_demo_project
from cfd_review.schema import validate_project, validate_state


class MirrorStateChecks(unittest.TestCase):
    def setUp(self):
        self.project = make_demo_project()
        self.case = self.project['cases'][0]
        self.state = {'sourceId': self.case['data']['meta']['sourceKey'], 'mirrorDisplay': True}

    def test_boolean_display_does_not_change_source_or_default(self):
        self.case['data']['meta']['scalarMirror'] = False
        before = copy.deepcopy(self.case)
        for choice in (True, False):
            validate_state({**self.state, 'mirrorDisplay': choice}, self.case)
        validate_state({'sourceId': self.state['sourceId']}, self.case)
        self.assertEqual(self.case, before)
        for value in (0, 1, None, 'true', [], {}):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'mirrorDisplay'):
                validate_state({**self.state, 'mirrorDisplay': value}, self.case)

    def test_full_cross_axis_and_comparison_sources_reject_enabled_state(self):
        full = copy.deepcopy(self.case)
        full['data']['meta'].update(halfCar=False, scalarMirror=False)
        crossing = copy.deepcopy(self.case)
        crossing['data']['parts'][0]['positions'][1] = -1
        comparison = compose_half_comparison(*self.project['cases'])
        for case in (full, crossing, comparison):
            with self.subTest(case=case['id']), self.assertRaisesRegex(ValueError, 'mirrorDisplay'):
                validate_state({'sourceId': case['data']['meta']['sourceKey'], 'mirrorDisplay': True}, case)
            validate_state({'sourceId': case['data']['meta']['sourceKey'], 'mirrorDisplay': False}, case)

    def test_mirrored_pick_needs_enabled_display_and_inverse_source_y(self):
        selection = {'kind':'surface', 'partId':self.case['data']['parts'][0]['id'],
            'field':'Cp', 'value':0, 'displayPoint':[0,-.2,.1], 'sourcePoint':[0,.2,.1],
            'mirrored':True, 'method':'native-triangle-barycentric-interpolation'}
        validate_state({**self.state, 'selection':selection}, self.case)
        with self.assertRaisesRegex(ValueError, 'mirrored'):
            validate_state({**self.state, 'mirrorDisplay':False, 'selection':selection}, self.case)
        with self.assertRaisesRegex(ValueError, 'source coordinates'):
            validate_state({**self.state, 'selection':{**selection,'sourcePoint':[0,-.2,.1]}}, self.case)

    def test_views_and_notes_roundtrip_mirror_preference(self):
        self.project['views'][0]['state'] = copy.deepcopy(self.state)
        self.project['notes'] = [{'id':'mirror-check', 'caseId':self.case['id'],
            'view':0, 'text':'Inspect the symmetric display', 'state':copy.deepcopy(self.state)}]
        before = copy.deepcopy(self.project)
        validate_project(self.project)
        self.assertEqual(self.project, before)


if __name__ == '__main__':
    unittest.main()
