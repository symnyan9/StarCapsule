"""Representation eligibility uses native type/cell evidence, never mesh names.

All records and sources in these tests are synthetic; no STAR process is opened.
"""
import copy
from pathlib import Path
import tempfile
import unittest

from cfd_review.desktop import DesktopController, exportable_representations


def source(name, cells=120, finite=True, **extra):
    return {"name": name, "type": "FvRepresentation" if finite else "GeometryRepresentation",
            "isFiniteVolume": finite, "cellCount": cells,
            "exportable": finite and type(cells) is int and cells > 0, **extra}


def inventory(*rows):
    return {"representations": [row["name"] for row in rows],
            "representationDetails": list(rows)}


class RepresentationChecks(unittest.TestCase):
    def test_geometry_latest_proxy_and_empty_mesh_are_hidden(self):
        value = inventory(source("Geometry", None, False),
                          source("Latest Surface/Volume", None, False),
                          source("Empty mesh", 0), source("Volume Mesh"))
        self.assertEqual([row["name"] for row in exportable_representations(value)], ["Volume Mesh"])

    def test_misleading_name_never_substitutes_for_native_finite_volume_type(self):
        value = inventory(source("Volume Mesh", None, False),
                          source("Solved mesh", 999, False),
                          source("Renamed finite volume", 42))
        self.assertEqual([row["name"] for row in exportable_representations(value)],
                         ["Renamed finite volume"])

    def test_native_type_evidence_accepts_renamed_and_subclass_mesh(self):
        value = inventory(source("Geometry", 41, type="NativeFvSubclass"))
        self.assertEqual(exportable_representations(value)[0]["cellCount"], 41)

    def test_volume_mesh_default_then_deterministic_exact_names_and_raw_metadata(self):
        rows = [source("z mesh", 30), source(" a mesh ", 20, kind="volume", custom={"kept": True}),
                source("Volume Mesh", 50), source("A mesh", 10)]
        value = inventory(*rows)
        before = copy.deepcopy(value)
        eligible = exportable_representations(value)
        self.assertEqual([row["name"] for row in eligible],
                         ["Volume Mesh", " a mesh ", "A mesh", "z mesh"])
        self.assertEqual(eligible[1], rows[1])
        eligible[1]["custom"]["kept"] = False
        self.assertEqual(value, before)

    def test_legacy_or_malformed_inventory_requires_native_reread(self):
        for value in (None, {}, {"representations": ["Volume Mesh"]},
                      {"representations": ["Volume Mesh"], "representationDetails": None},
                      {"representations": None, "representationDetails": []}):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "重新.*读取仿真内容"):
                exportable_representations(value)

    def test_invalid_flags_types_counts_and_names_are_rejected(self):
        changes = [{"isFiniteVolume": 1}, {"isFiniteVolume": "true"}, {"isFiniteVolume": False},
                   {"exportable": 1}, {"exportable": "true"}, {"exportable": False},
                   {"cellCount": True}, {"cellCount": 1.0}, {"cellCount": "120"},
                   {"cellCount": 0}, {"cellCount": -1}, {"cellCount": None},
                   {"type": None}, {"type": ""}, {"name": " "}, {"name": None}]
        for update in changes:
            row = source("Mesh")
            row.update(update)
            value = {"representations": ["Mesh"], "representationDetails": [row]}
            with self.subTest(update=update):
                self.assertEqual(exportable_representations(value), [])
        self.assertEqual(exportable_representations({"representations": ["Mesh"],
                         "representationDetails": [None, "Mesh", {}, []]}), [])

    def test_unknown_and_duplicate_sources_cannot_be_selected_exactly(self):
        value = inventory(source("Mesh"))
        value["representations"] = ["Other mesh"]
        self.assertEqual(exportable_representations(value), [])
        value = inventory(source("Mesh"), source("Mesh"))
        self.assertEqual(exportable_representations(value), [])
        value["representations"] = ["Mesh"]
        self.assertEqual(exportable_representations(value), [])
        value = inventory(source("Mesh"))
        value["representations"].append("Mesh")
        self.assertEqual(exportable_representations(value), [])

    def test_empty_inventory_does_not_invent_a_default(self):
        self.assertEqual(exportable_representations(inventory()), [])

    def test_iteration_does_not_imply_mesh_or_solution_quality(self):
        value = inventory(source("Volume Mesh", 0))
        value["iteration"] = 10000
        self.assertEqual(exportable_representations(value), [])
        value = inventory(source("Renamed mesh", 120))
        value["iteration"] = 0
        self.assertEqual(exportable_representations(value)[0]["name"], "Renamed mesh")

    def test_controller_rejects_invalid_representation_before_configuration_or_worker(self):
        with tempfile.TemporaryDirectory() as folder:
            controller = DesktopController(Path(folder) / "jobs")
            value = inventory(source("Geometry", None, False), source("Empty", 0), source("Usable"))
            for name in ("Geometry", "Empty", "Unknown", None):
                with self.subTest(name=name), self.assertRaisesRegex(ValueError, "体网格"):
                    controller._export_config({"representation": name}, value, {}, Path(folder) / "case.sim")
                self.assertFalse(controller.busy)

    def test_controller_passes_exact_native_name_not_display_label(self):
        with tempfile.TemporaryDirectory() as folder:
            controller = DesktopController(Path(folder) / "jobs")
            raw_name = "  Renamed FV 网格  "
            value = inventory(source(raw_name))
            value.update(fields=[{"functionName": "cp", "type": "SCALAR"}],
                         regions=[{"name": "Flow", "boundaries": ["Wall"]}])
            options = {"representation": raw_name, "cp_function": "cp", "surfaces": [
                {"id": "wall", "name": "Wall", "boundaries": [{"region": "Flow", "name": "Wall"}]}],
                "ranges": {"Cp": [-3, 1], "CpT": [-.5, 1]}, "surface_range": [-3, 1], "half_car": False}
            config = controller._export_config(options, value, {"sha256": "synthetic"},
                                                Path(folder) / "case.sim")
            self.assertEqual(config["representation"], raw_name)

    def test_multiple_meshes_reject_colored_layers_but_allow_geometry_walls_and_sections(self):
        with tempfile.TemporaryDirectory() as folder:
            controller = DesktopController(Path(folder) / "jobs")
            value = inventory(source("Volume Mesh"), source("Another FV mesh"))
            value.update(fields=[{"functionName": "cp", "type": "SCALAR"}],
                         regions=[{"name": "Flow", "boundaries": ["Wall"]}],
                         derivedParts=["Source iso"], derivedPartDetails=[
                             {"name": "Source iso", "type": "IsoPart", "exportableMesh": True}])
            options = {"representation": "Another FV mesh", "layers": [
                {"id": "iso", "name": "Source iso", "derivedPart": "Source iso", "fieldFunction": "cp"}],
                "ranges": {"Cp": [-3, 1], "CpT": [-.5, 1]}, "surface_range": [-3, 1], "half_car": False}
            identity, sim = {"sha256": "synthetic"}, Path(folder) / "case.sim"
            with self.assertRaisesRegex(ValueError, "多个有效体网格.*仅几何"):
                controller._export_config(options, value, identity, sim)
            options["layers"][0].pop("fieldFunction")
            self.assertEqual(controller._export_config(options, value, identity, sim)["representation"],
                             "Another FV mesh")
            options.update(layers=[], cp_function="cp", surfaces=[
                {"id": "wall", "name": "Wall", "boundaries": [{"region": "Flow", "name": "Wall"}]}],
                x_sections=[0, 1], section_regions=["Flow"])
            self.assertEqual(controller._export_config(options, value, identity, sim)["xSections"], [0, 1])


if __name__ == "__main__":
    unittest.main()
