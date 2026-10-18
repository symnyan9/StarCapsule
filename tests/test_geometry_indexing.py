"""Exact STL display indexing preserves ordered native triangle corners."""
import copy
from pathlib import Path
import struct
import tempfile
import unittest

from cfd_review.demo import make_demo_project
from cfd_review.mesh_io import _transform, pack_case, read_stl


class GeometryIndexingChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.path = self.root / "mesh.stl"

    def write_stl(self, triangles, binary=False):
        if binary:
            self.path.write_bytes(b"synthetic indexing check".ljust(80, b" ") +
                struct.pack("<I", len(triangles)) + b"".join(
                    struct.pack("<12fH", 0, 0, 1, *triangle, 0) for triangle in triangles))
        else:
            body = []
            for triangle in triangles:
                vertices = "\n".join("vertex " + " ".join(repr(v) for v in triangle[i:i+3])
                                     for i in range(0, 9, 3))
                body.append("facet normal 0 0 1\nouter loop\n" + vertices + "\nendloop\nendfacet")
            self.path.write_text("solid test\n" + "\n".join(body) + "\nendsolid test\n", encoding="ascii")

    def pack(self, transform=None, **entry):
        meta = copy.deepcopy(make_demo_project()["cases"][0]["data"]["meta"])
        config = {"schema": "cfd-review-pack", "version": 1, "id": "exact-stl", "name": "Synthetic",
                  "meta": meta, "fields": {}, "transform": transform,
                  "parts": [{"id": "mesh", "name": "Synthetic geometry", "stl": self.path.name, **entry}]}
        return pack_case(config, self.root)["data"]["parts"][0]

    def assert_corners(self, mesh, expected):
        actual = [value for index in mesh["indices"] for value in mesh["positions"][index*3:index*3+3]]
        self.assertEqual(struct.pack("!" + "d"*len(actual), *actual),
                         struct.pack("!" + "d"*len(expected), *expected))

    def test_binary_shared_corners_and_winding_unchanged(self):
        triangles = [(0, 0, 0, 1, 0, 0, 0, 1, 0), (0, 1, 0, 1, 0, 0, 1, 1, 0)]
        self.write_stl(triangles, binary=True)
        original, source_indices = read_stl(self.path)
        mesh = self.pack()
        self.assert_corners(mesh, original)
        self.assertEqual(source_indices, list(range(6)))  # Public reader remains expanded.
        self.assertEqual(mesh["indices"], [0, 1, 2, 2, 1, 3])
        self.assertEqual(mesh["provenance"]["sourceCornerCount"], 6)
        self.assertEqual(mesh["provenance"]["displayVertexCount"], 4)
        self.assertEqual(mesh["provenance"]["displayTriangleCount"], 2)
        self.assertEqual(mesh["provenance"]["omittedStrictZeroAreaTriangles"], 0)
        self.assertNotIn("cp", mesh)

    def test_ascii_repeated_triangle_order_unchanged(self):
        triangle = (0, 0, 0, 1, 0, 0, 0, 1, 0)
        self.write_stl([triangle, triangle])
        mesh = self.pack()
        self.assert_corners(mesh, list(triangle) * 2)
        self.assertEqual(mesh["indices"], [0, 1, 2, 0, 1, 2])
        self.assertEqual(mesh["provenance"]["triangles"], 2)

    def test_signed_zero_and_nearby_coordinates_stay_distinct(self):
        triangles = [(x, 0, 0, 1, 0, 0, 0, 1, 0) for x in (0.0, -0.0, 1e-14)]
        self.write_stl(triangles)
        original, _ = read_stl(self.path)
        mesh = self.pack()
        self.assert_corners(mesh, original)
        self.assertEqual(len({mesh["indices"][i] for i in (0, 3, 6)}), 3)
        self.assertEqual(mesh["provenance"]["displayVertexCount"], 5)

    def test_transform_preserves_each_transformed_corner(self):
        self.write_stl([(0, 0, 0, 1, 0, 0, 0, 1, 0), (0, 1, 0, 1, 0, 0, 1, 1, 0)], binary=True)
        transform = {"scale": .001, "axes": [2, 0, 1], "signs": [-1, 1, -1], "offset": [3, -2, 1]}
        original, _ = read_stl(self.path)
        expected = [v for i in range(0, len(original), 3) for v in _transform(original[i:i+3], transform)]
        mesh = self.pack(transform)
        self.assert_corners(mesh, expected)
        self.assertEqual(mesh["provenance"]["displayVertexCount"], 4)
        self.assertEqual(mesh["provenance"]["transform"], transform)

    def test_strict_zero_area_omission_stays_audited(self):
        kept = (0, 0, 0, 1, 0, 0, 0, 1, 0)
        self.write_stl([(0, 0, 0, 1, 0, 0, 2, 0, 0), kept], binary=True)
        mesh = self.pack()
        self.assert_corners(mesh, list(kept))
        self.assertEqual(mesh["provenance"]["sourceCornerCount"], 6)
        self.assertEqual(mesh["provenance"]["triangles"], 2)
        self.assertEqual(mesh["provenance"]["displayTriangleCount"], 1)
        self.assertEqual(mesh["provenance"]["omittedStrictZeroAreaTriangles"], 1)

    def test_csv_scalar_association_path_remains_unindexed_by_this_change(self):
        triangle = (0, 0, 0, 1, 0, 0, 0, 1, 0)
        self.write_stl([triangle, triangle], binary=True)
        (self.root / "mesh.csv").write_text("X (m),Y (m),Z (m),Cp\n0,0,0,1\n1,0,0,2\n0,1,0,3\n", encoding="ascii")
        mesh = self.pack(csv="mesh.csv", fields={"Cp": "Cp"})
        self.assertEqual(mesh["cp"], [1, 2, 3])
        self.assert_corners(mesh, list(triangle) * 2)
        self.assertEqual(mesh["provenance"]["method"], "native-stl-nearest-coordinate-no-averaging")
        self.assertNotIn("indexingMethod", mesh["provenance"])


if __name__ == "__main__":
    unittest.main()
