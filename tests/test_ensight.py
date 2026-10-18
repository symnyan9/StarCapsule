"""Synthetic format fixtures; these are not solver results or vehicle data."""
import hashlib
from collections import Counter
from pathlib import Path
import struct
import tempfile
import unittest

from cfd_review.ensight import read_case, _verified_source_fan


def _label(text):
    raw = text.encode("ascii")
    return raw.ljust(79, b" ") + b"\n"


def fixture(folder, points, blocks, values=None, binary=True, part_id=1):
    geo = folder / "mesh00000.geo"
    scalar = folder / "mesh00000.scalar"
    case = folder / "mesh.case"
    labels, numbers = [], []
    data = bytearray()
    def label(text):
        data.extend(_label(text) if binary else (text + "\n").encode("ascii"))
    def ints(items):
        data.extend(struct.pack("<" + "i" * len(items), *items) if binary else
                    (" ".join(str(v) for v in items) + "\n").encode("ascii"))
    def floats(items):
        data.extend(struct.pack("<" + "f" * len(items), *items) if binary else
                    (" ".join(str(v) for v in items) + "\n").encode("ascii"))
    if binary:
        label("C Binary")
    label("Synthetic source")
    label("Test geometry")
    label("node id off")
    label("element id off")
    label("part")
    ints([part_id])
    label("Synthetic face")
    label("coordinates")
    ints([len(points)])
    floats([point[axis] for axis in range(3) for point in points])
    for kind, faces in blocks:
        label(kind)
        ints([len(faces)])
        if kind == "nsided":
            ints([len(face) for face in faces])
        ints([index for face in faces for index in face])
    geo.write_bytes(data)
    if values is not None:
        data.clear()
        label("FixtureScalar at nodes")
        label("part")
        ints([part_id])
        label("coordinates")
        floats(values)
        scalar.write_bytes(data)
    case.write_text("FORMAT\ntype: ensight gold\nGEOMETRY\nmodel: mesh00000.geo\n" +
                    ("VARIABLE\nscalar per node: FixtureScalar mesh*****.scalar\n" if values is not None else "") +
                    "TIME\ntime set: 1\nnumber of steps: 1\nfilename start number: 0\nfilename increment: 1\ntime values:\n0\n"
                    "#SCRIPTS\n#metadata: ignored.xml\n", encoding="ascii")
    return case, geo, scalar


def area(mesh):
    result = 0.0
    for i in range(0, len(mesh["indices"]), 3):
        a, b, c = [mesh["positions"][3 * j:3 * j + 3] for j in mesh["indices"][i:i + 3]]
        result += abs((b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])) / 2
    return result


class EnSightChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)

    def mixed(self, binary=True):
        points = [(0, 0, 0), (2, 0, 0), (2, 2, 0), (1, 1, 0), (0, 2, 0),
                  (10, 0, 0), (11, 0, 0), (11, 1, 0), (10, 1, 0), (20, 0, 0), (21, 0, 0)]
        return fixture(self.folder, points, [("bar2", [[10, 11]]), ("tria3", [[1, 2, 4]]),
                       ("quad4", [[6, 7, 8, 9]]), ("nsided", [[1, 2, 3, 4, 5]])],
                       list(range(1, 10)) + [1000, -1000], binary)

    def test_real_profile_binary_preserves_node_values_and_face_connectivity(self):
        case, geo, scalar = self.mixed()
        mesh, = read_case(case)
        self.assertEqual(mesh["id"], "1")
        self.assertEqual(len(mesh["positions"]), 33)
        self.assertEqual(mesh["values"], list(range(1, 10)) + [1000, -1000])
        self.assertEqual(mesh["field"], "FixtureScalar")
        self.assertEqual(len(mesh["indices"]), 18)
        self.assertEqual(area(mesh), 5.0)  # triangle 1 + quad 1 + concave polygon 3
        self.assertNotIn("units", mesh)
        provenance = mesh["provenance"]
        self.assertEqual(provenance["coordinateStorage"], "native-binary32")
        self.assertEqual(provenance["scalarStorage"], "native-binary32")
        self.assertEqual(provenance["omittedNonSurfaceElements"], {"bar2": 1})
        self.assertEqual(provenance["sourceElementCounts"], {"bar2": 1, "tria3": 1, "quad4": 1, "nsided": 1})
        self.assertEqual(provenance["surfaceValueRange"], [1, 9])
        self.assertEqual(provenance["unusedNodeCount"], 2)
        self.assertEqual(provenance["geometrySha256"], hashlib.sha256(geo.read_bytes()).hexdigest())
        self.assertEqual(provenance["scalarSha256"], hashlib.sha256(scalar.read_bytes()).hexdigest())

    def test_ascii_equivalent_uses_same_source_node_order(self):
        case, _, _ = self.mixed(binary=False)
        mesh, = read_case(case)
        self.assertEqual(mesh["provenance"]["format"], "ascii")
        self.assertEqual(area(mesh), 5)
        self.assertEqual(mesh["values"][:5], [1, 2, 3, 4, 5])

    def test_concave_polygon_winding_and_no_new_center_nodes(self):
        points = [(0, 0, 0), (2, 0, 0), (2, 2, 0), (1, 1, 0), (0, 2, 0)]
        for reverse in (False, True):
            order = [1, 2, 3, 4, 5][::(-1 if reverse else 1)]
            case, _, _ = fixture(self.folder, points, [("nsided", [order])], [0, 10, 20, 30, 40])
            mesh, = read_case(case)
            self.assertEqual(area(mesh), 3)
            self.assertEqual(len(mesh["positions"]), 15)
            self.assertEqual(mesh["values"], [0, 10, 20, 30, 40])
            for i in range(0, len(mesh["indices"]), 3):
                a, b, c = [points[j] for j in mesh["indices"][i:i + 3]]
                cross = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
                self.assertLess(cross, 0) if reverse else self.assertGreater(cross, 0)

    def test_strict_zero_triangle_omitted_but_positive_tiny_face_kept(self):
        points = [(0, 0, 0), (1e-20, 0, 0), (0, 1e-20, 0)]
        case, _, _ = fixture(self.folder, points, [("tria3", [[1, 1, 2], [1, 2, 3]])], [1, 2, 3])
        mesh, = read_case(case)
        self.assertEqual(mesh["indices"], [0, 1, 2])
        self.assertEqual(mesh["provenance"]["omittedStrictZeroAreaTriangles"], 1)
        self.assertGreater(area(mesh), 0)

    def test_nonplanar_quad_uses_valid_alternative_projection_without_reordering(self):
        # Independently constructed integer corners: the dominant projection
        # crosses, while the X projection is simple.
        points = [(11, -7, 18), (-20, 10, -20), (15, -1, -2), (9, -6, -18)]
        case, _, _ = fixture(self.folder, points, [("quad4", [[1, 2, 3, 4]])], [10, 20, 30, 40])
        mesh, = read_case(case)
        self.assertEqual(len(mesh["indices"]), 6)
        self.assertEqual(mesh["values"], [10, 20, 30, 40])
        self.assertEqual(mesh["positions"], [v for point in points for v in point])
        self.assertEqual(mesh["provenance"]["projectionAxisCounts"], {"x": 1, "nonDominantFallback": 1})
        self.assertEqual(area(mesh), 135)

    def test_exact_nonplanar_quad_can_have_crossing_axis_projections(self):
        points = [(-13, -9, 3), (-2, -16, -2), (3, 13, 13), (11, -14, -6)]
        # Exact scalar triple product is -1276, so the source corners are not
        # coplanar despite all three coordinate-axis projection crossings.
        case, _, _ = fixture(self.folder, points, [("quad4", [[1, 2, 3, 4]])], [1, 4, 9, 16])
        mesh, = read_case(case)
        self.assertEqual(mesh["indices"], [0, 1, 2, 0, 2, 3])
        self.assertEqual(mesh["values"], [1, 4, 9, 16])
        self.assertEqual(mesh["provenance"]["projectionAxisCounts"]["nonplanar-quad-diagonal-rule"], 1)

    def test_nonplanar_polygon_uses_bounded_oblique_view_and_preserves_boundary(self):
        points = [(27, -9, -17), (24, -23, -6), (18, -6, 30), (20, 10, 8),
                  (-2, 16, -7), (-18, -15, -7), (21, 12, -4), (29, -20, 2)]
        values = [i * i for i in range(8)]
        case, _, _ = fixture(self.folder, points, [("nsided", [list(range(1, 9))])], values)
        mesh, = read_case(case)
        self.assertEqual(len(mesh["indices"]), 18)
        self.assertEqual(mesh["positions"], [v for point in points for v in point])
        self.assertEqual(mesh["values"], values)
        self.assertTrue(any(key.startswith("oblique-") for key in mesh["provenance"]["projectionAxisCounts"]))
        edges = Counter()
        for i in range(0, len(mesh["indices"]), 3):
            triangle = mesh["indices"][i:i + 3]
            edges.update(tuple(sorted((a, b))) for a, b in zip(triangle, triangle[1:] + triangle[:1]))
        boundary = {tuple(sorted((i, (i + 1) % 8))) for i in range(8)}
        self.assertEqual({edge for edge, uses in edges.items() if uses == 1}, boundary)
        self.assertTrue(all(uses == (1 if edge in boundary else 2) for edge, uses in edges.items()))

    def test_fixed_sphere_fallback_records_direction_and_preserves_mesh(self):
        # Abstract integer corners requiring a direction beyond all source
        # triangle/corner normals. This is mathematical fixture geometry.
        points = [(-12, -18, -14), (25, -19, -25), (-20, -25, 28), (29, 21, 15),
                  (-20, 23, 27), (9, -1, -7), (-17, -8, 15)]
        case, _, _ = fixture(self.folder, points, [("nsided", [list(range(1, 8))])], list(range(7)))
        mesh, = read_case(case)
        self.assertEqual(mesh["provenance"]["projectionAxisCounts"],
                         {"fixed-sphere-512-25": 1, "nonDominantFallback": 1})
        self.assertIn("i=0..511", mesh["provenance"]["fixedSphereCandidateRule"])
        self.assertEqual(mesh["positions"], [v for p in points for v in p])
        self.assertEqual(mesh["values"], list(range(7)))
        edges = Counter()
        for i in range(0, len(mesh["indices"]), 3):
            triangle = mesh["indices"][i:i + 3]
            edges.update(tuple(sorted((a, b))) for a, b in zip(triangle, triangle[1:] + triangle[:1]))
        boundary = {tuple(sorted((i, (i + 1) % 7))) for i in range(7)}
        self.assertEqual({edge for edge, uses in edges.items() if uses == 1}, boundary)
        self.assertEqual(len(mesh["indices"]), 15)
        self.assertTrue(all(uses == (1 if edge in boundary else 2) for edge, uses in edges.items()))

    def test_exact_3d_fallback_preserves_original_boundary_and_node_fields(self):
        # Independently generated abstract integer polygon, with no accepted
        # bounded plane projection and a fully verified source-order 3D fan.
        points = [(2, 3, 6), (-30, -26, -2), (-21, -1, -13), (24, 24, 16),
                  (5, 2, -22), (-8, 9, 17), (-30, -6, -28)]
        case, _, _ = fixture(self.folder, points, [("nsided", [list(range(1, 8))])], list(range(7)))
        mesh, = read_case(case)
        self.assertEqual(mesh["provenance"]["projectionAxisCounts"],
                         {"verified-3d-source-order-fan-pivot-2": 1})
        self.assertEqual(mesh["positions"], [v for point in points for v in point])
        self.assertEqual(mesh["values"], list(range(7)))
        self.assertEqual(len(mesh["indices"]), 15)
        edges = Counter()
        for i in range(0, len(mesh["indices"]), 3):
            triangle = mesh["indices"][i:i + 3]
            edges.update(tuple(sorted((a, b))) for a, b in zip(triangle, triangle[1:] + triangle[:1]))
        boundary = {tuple(sorted((i, (i + 1) % 7))) for i in range(7)}
        self.assertEqual({edge for edge, uses in edges.items() if uses == 1}, boundary)
        self.assertTrue(all(uses == (1 if edge in boundary else 2) for edge, uses in edges.items()))

    def test_exact_3d_cones_reject_shared_ray_but_accept_opposite_rays(self):
        # First/last triangles lie in z=0/y=0. Both contain +X near
        # the common pivot: a shared segment is forbidden, not just an area.
        crossing = [(0, 0, 0), (1, -1, 0), (1, 1, 0), (1, 0, -1), (1, 0, 1)]
        self.assertIsNone(_verified_source_fan(list(range(5)), crossing))
        # The second cone instead points towards -X; the same two planes
        # intersect only at the original pivot inside these triangles.
        separated = crossing[:3] + [(-1, 0, -1), (-1, 0, 1)]
        triangles, pivot = _verified_source_fan(list(range(5)), separated)
        self.assertEqual(pivot, 0)
        self.assertEqual(triangles, [0, 1, 2, 0, 2, 3, 0, 3, 4])
        # An exact dyadic rescaling leaves the geometric decision unchanged;
        # no area tolerance discards this small but positive geometry.
        tiny = [tuple(value * 2 ** -90 for value in point) for point in separated]
        self.assertEqual(_verified_source_fan(list(range(5)), tiny), (triangles, pivot))

    def test_exact_3d_fan_rejects_coplanar_overlap_and_nonstar_polygon(self):
        bowtie = [(0, 0, 0), (1, 1, 0), (0, 1, 0), (1, 0, 0)]
        self.assertIsNone(_verified_source_fan(list(range(4)), bowtie))
        # A U-shaped planar region has no vertex seeing every other vertex.
        # Ear clipping remains available, but a blind fan would fill its notch.
        points = [(0, 0, 0), (3, 0, 0), (3, 3, 0), (2, 3, 0),
                  (2, 1, 0), (1, 1, 0), (1, 3, 0), (0, 3, 0)]
        self.assertIsNone(_verified_source_fan(list(range(8)), points))
        case, _, _ = fixture(self.folder, points, [("nsided", [list(range(1, 9))])])
        mesh, = read_case(case)
        self.assertEqual(area(mesh), 7)

    def test_geometry_only_does_not_create_scalar_values(self):
        case, _, _ = fixture(self.folder, [(0, 0, 0), (1, 0, 0), (0, 1, 0)], [("tria3", [[1, 2, 3]])])
        mesh, = read_case(case)
        self.assertNotIn("values", mesh)
        self.assertNotIn("field", mesh)

    def test_per_element_and_transient_inputs_rejected(self):
        case, _, _ = self.mixed()
        original = case.read_text()
        case.write_text(original.replace("scalar per node", "scalar per element"))
        with self.assertRaisesRegex(ValueError, "per node"):
            read_case(case)
        case.write_text(original.replace("number of steps: 1", "number of steps: 2"))
        with self.assertRaisesRegex(ValueError, "single recorded"):
            read_case(case)

    def test_reject_volume_connectivity_and_unimplemented_id_mode(self):
        points = [(0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1)]
        case, geo, _ = fixture(self.folder, points, [("tetra4", [[1, 2, 3, 4]])])
        with self.assertRaisesRegex(ValueError, "Unsupported.*type"):
            read_case(case)
        geo.write_bytes(geo.read_bytes().replace(_label("node id off"), _label("node id given")))
        with self.assertRaisesRegex(ValueError, "off/assign"):
            read_case(case)

    def test_reject_self_intersection_missing_nodes_and_nonfinite_values(self):
        case, _, _ = fixture(self.folder, [(0, 0, 0), (1, 1, 0), (0, 1, 0), (1, 0, 0)], [("quad4", [[1, 2, 3, 4]])])
        with self.assertRaises(ValueError):
            read_case(case)
        case, _, _ = fixture(self.folder, [(0, 0, 0), (1, 0, 0), (0, 1, 0)], [("tria3", [[1, 2, 4]])])
        with self.assertRaisesRegex(ValueError, "missing node"):
            read_case(case)
        case, _, _ = fixture(self.folder, [(0, 0, 0), (1, 0, 0), (0, 1, 0)], [("tria3", [[1, 2, 3]])], [1, float("nan"), 3])
        with self.assertRaisesRegex(ValueError, "Non-finite"):
            read_case(case)

    def test_case_references_cannot_escape_or_run_metadata(self):
        case, _, _ = self.mixed()
        self.assertEqual(len(read_case(case)), 1)
        case.write_text(case.read_text().replace("model: mesh00000.geo", "model: ../outside.geo"))
        with self.assertRaisesRegex(ValueError, "escape|missing"):
            read_case(case)

    def test_truncated_or_extra_scalar_data_is_not_filled_or_ignored(self):
        case, _, scalar = self.mixed()
        raw = scalar.read_bytes()
        for content in (raw[:-4], raw + struct.pack("<f", 1)):
            scalar.write_bytes(content)
            with self.assertRaises(ValueError):
                read_case(case)


if __name__ == "__main__":
    unittest.main()
