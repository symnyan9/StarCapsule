"""Contract checks use synthetic data. Mocked STAR calls do not validate STAR runtime."""
import copy
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

from cfd_review.demo import make_demo_project
from cfd_review.mesh_io import match_csv_to_stl, pack_case, read_stl
from cfd_review.schema import load_document, validate_case, validate_project
from cfd_review.star import _run, prepare_macro


def case():
    return {"schema": "cfd-review-case", "version": 1, "id": "test", "name": "Synthetic triangle",
            "data": {"meta": {"title": "Synthetic", "source": "Unit test only", "sourceKey": "test-v1",
            "units": "m", "axis": {"up": "z"}, "isDemo": True, "halfCar": False,
            "ranges": {"Cp": [-3, 3], "CpT": [-.5, 1]}, "surfaceRange": [-3, 3]},
            "parts": [{"id": "p", "name": "Triangle", "positions": [0,0,0, 0,1,0, 0,0,1],
                       "indices": [0,1,2], "cp": [1,2,3]}], "sections": []}}


def config():
    return {"schema": "cfd-review-star-config", "version": 1, "id": "synthetic", "name": "Synthetic configuration",
            "representation": "Volume Mesh", "meta": case()["data"]["meta"],
            "fields": {"Cp": {"function": "PressureCoefficient"}, "CpT": {"expression": "(${TotalPressure}-0)/100"}},
            "surfaces": [{"id": "part", "name": "Placeholder", "boundaries": [{"region": "EXAMPLE", "name": "EXAMPLE"}]}],
            "sectionRegions": ["EXAMPLE"], "xSections": [0, 1]}


class SchemaChecks(unittest.TestCase):
    def test_demo_contract(self):
        validate_project(make_demo_project())

    def test_geometry_only_surface(self):
        obj = case()
        del obj["data"]["parts"][0]["cp"]
        self.assertIs(validate_case(obj), obj)

    def test_bad_vertex_field_and_boolean_index(self):
        for key, value in [("cp", [1,2]), ("positions", [0,0,float("nan")]), ("indices", [True,1,2])]:
            obj = case()
            obj["data"]["parts"][0][key] = value
            with self.assertRaises(ValueError): validate_case(obj)

    def test_wrong_units_and_unknown_metadata_nan(self):
        for key, value in [("units", "mm"), ("arbitrary", {"hidden": float("nan")})]:
            obj = case()
            obj["data"]["meta"][key] = value
            with self.assertRaises(ValueError): validate_case(obj)

    def test_plane_location_and_order(self):
        obj = case()
        mesh = {**obj["data"]["parts"][0], "x": 0}
        obj["data"]["sections"] = [mesh]
        validate_case(obj)
        mesh["positions"] = [1,0,0, 1,1,0, 1,0,1]
        with self.assertRaisesRegex(ValueError, "X plane"): validate_case(obj)

    def test_sweep_requires_a_common_field_without_filling(self):
        obj = case()
        first = {**copy.deepcopy(obj["data"]["parts"][0]), "x": 0}
        second = {"x": 1, "positions": [1,0,0,1,1,0,1,0,1], "indices": [0,1,2], "cpt": [.2,.3,.4]}
        obj["data"]["sections"] = [first, second]
        with self.assertRaisesRegex(ValueError, "share at least one"): validate_case(obj)

    def test_duplicate_part_and_unsafe_key(self):
        obj = case()
        obj["data"]["parts"].append(copy.deepcopy(obj["data"]["parts"][0]))
        with self.assertRaisesRegex(ValueError, "duplicate"): validate_case(obj)
        obj = case()
        obj["data"]["meta"]["__proto__"] = {}
        with self.assertRaisesRegex(ValueError, "unsafe"): validate_case(obj)

    def test_state_validation(self):
        obj = make_demo_project()
        state = {"sourceId": obj["cases"][0]["data"]["meta"]["sourceKey"],
                 "camera": {"position": [3,2,1], "target": [0,0,0]}, "sectionIndex": 0,
                 "variable": "Cp", "colorRanges": {"surfaceCp": [-3,3], "section": {"Cp": [-3,3], "CpT": [-.5,1]}}}
        obj["views"][0]["state"] = state
        validate_project(obj)
        for key, invalid in [("sourceId", "wrong-source"), ("bodyOpacity", -1), ("partSelection", ["missing"]),
                             ("sectionIndex", True), ("colorRanges", {"surfaceCp": [3,-3]})]:
            broken = copy.deepcopy(obj)
            broken["views"][0]["state"][key] = invalid
            with self.assertRaises(ValueError): validate_project(broken)

    def test_duplicate_json_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "bad.json"
            p.write_text('{"schema":"x","schema":"y"}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "duplicate"): load_document(p)


class MeshChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.csv = self.root / "mesh.csv"
        self.csv.write_text('X,Y,Z,Pressure,Total\n0,0,0,110,210\n0,1000,0,210,310\n0,0,1000,310,410\n', encoding="utf-8")
        self.stl = self.root / "mesh.stl"
        values = (0,0,1, 0,0,0, 0,1000,0, 0,0,1000, 0)
        self.stl.write_bytes(b"solid binary misleading header".ljust(80, b" ") + struct.pack("<I", 1) + struct.pack("<12fH", *values))
        self.fields = {"Cp": {"column": "Pressure", "referencePressure": 10, "dynamicPressure": 100}, "CpT": "Total"}

    def test_binary_topology_coordinate_conversion(self):
        mesh = match_csv_to_stl(self.csv, self.stl, self.fields,
                               {"scale": .001}, ["X","Y","Z"])
        self.assertEqual(mesh["positions"], [0,0,0, 0,1,0, 0,0,1])
        self.assertEqual(mesh["indices"], [0,1,2])
        self.assertEqual(mesh["cp"], [1,2,3])

    def test_ascii_stl(self):
        self.stl.write_text('solid a\nfacet normal 0 0 1\nouter loop\nvertex 0 0 0\nvertex 0 1 0\nvertex 0 0 1\nendloop\nendfacet\nendsolid a', encoding="ascii")
        self.assertEqual(read_stl(self.stl), ([0,0,0,0,1,0,0,0,1], [0,1,2]))

    def test_missing_values_never_filled(self):
        self.csv.write_text('X,Y,Z,Pressure,Total\n0,0,0,1,2\n', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "unmatched"):
            match_csv_to_stl(self.csv, self.stl, self.fields, coordinate_columns=["X","Y","Z"])

    def test_ambiguous_coincident_values_rejected(self):
        with self.csv.open("a", encoding="utf-8") as stream: stream.write('0,0,0,999,999\n')
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            match_csv_to_stl(self.csv, self.stl, self.fields, coordinate_columns=["X","Y","Z"])

    def test_full_pack(self):
        cfg = {"schema": "cfd-review-pack", "version": 1, "id": "test", "name": "Synthetic",
               "meta": case()["data"]["meta"], "coordinateColumns": ["X","Y","Z"], "fields": self.fields,
               "transform": {"scale": .001}, "parts": [{"id":"p","name":"Triangle","csv":"mesh.csv","stl":"mesh.stl"}],
               "sections": [{"x":0,"csv":"mesh.csv","stl":"mesh.stl"}]}
        packed = pack_case(cfg, self.root)
        self.assertEqual(packed["data"]["sections"][0]["cp"], [1,2,3])

    def test_pure_stl_geometry_has_no_invented_field(self):
        cfg = {"schema": "cfd-review-pack", "version": 1, "id": "test", "name": "Synthetic",
               "meta": case()["data"]["meta"], "fields": {}, "parts": [{"id":"p","name":"Triangle","stl":"mesh.stl"}], "sections": []}
        packed = pack_case(cfg, self.root)
        self.assertNotIn("cp", packed["data"]["parts"][0])
        self.assertNotIn("cpt", packed["data"]["parts"][0])

    def test_only_strict_zero_area_faces_are_omitted_and_recorded(self):
        raw = self.stl.read_bytes()
        self.stl.write_bytes(raw[:80] + struct.pack("<I", 2) + raw[84:] + struct.pack("<12fH", *([0]*13)))
        mesh = match_csv_to_stl(self.csv, self.stl, self.fields, coordinate_columns=["X","Y","Z"])
        self.assertEqual(mesh["provenance"]["triangles"], 2)
        self.assertEqual(mesh["provenance"]["omittedStrictZeroAreaTriangles"], 1)
        self.assertEqual(len(mesh["indices"]), 3)


class StarAdapterChecks(unittest.TestCase):
    def test_preparation_escapes_text_without_unsafe_operations(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = config()
            cfg["surfaces"][0]["boundaries"][0]["name"] = 'Quoted "name" \\ path'
            plan = prepare_macro(cfg, tmp)
            macro = Path(plan["macro"]).read_text(encoding="utf-8")
            self.assertIn('Quoted \\"name\\" \\\\ path', macro)
            for call in ('.run(', '.step(', '.saveState(', '.clearSolution(', '.initializeSolution('):
                self.assertNotIn(call, macro)
            self.assertEqual(len(plan["expectedFiles"]), 7)

    def test_mock_zero_exit_is_not_success(self):
        """Only mock/error-path verification; no STAR executable is launched."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sim = root / "synthetic.sim"
            sim.write_bytes(b"synthetic mock fixture; not a STAR file")
            plan = prepare_macro({}, root / "output", "inspect")
            with patch("cfd_review.star.find_star", return_value=Path("mock-star.exe")), \
                 patch("cfd_review.star.memory_status", return_value=None), \
                 patch("cfd_review.star._execute_owned", return_value=0):
                with self.assertRaisesRegex(ValueError, "no completion"):
                    _run(plan, sim)
            receipt = json.loads((root / "output/run-receipt.json").read_text(encoding="utf-8"))
            self.assertFalse(receipt["runtimeValidated"])
            self.assertTrue(receipt["sourceUnchanged"])

    def test_mock_source_mutation_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sim = root / "synthetic.sim"
            sim.write_bytes(b"synthetic mock fixture")
            plan = prepare_macro({}, root / "output", "inspect")
            def mutate(*args): sim.write_bytes(b"changed synthetic fixture"); return 0
            with patch("cfd_review.star.find_star", return_value=Path("mock-star.exe")), \
                 patch("cfd_review.star.memory_status", return_value=None), \
                 patch("cfd_review.star._execute_owned", side_effect=mutate):
                with self.assertRaisesRegex(ValueError, "identity changed"):
                    _run(plan, sim)


if __name__ == "__main__":
    unittest.main()
