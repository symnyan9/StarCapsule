"""Bound dense CFD arrays independently of JSON structure, on Python and JS.

Small injected budgets exercise real boundaries without allocating huge models.
Node checks extract the private production functions; no test API is published.
"""
import copy
import json
from pathlib import Path
import re
import shutil
import subprocess
import unittest
from unittest.mock import patch

from cfd_review import schema


JS_PATH = Path(schema.__file__).parent / "assets" / "studio.js"
POLICY = {"JSON_STRUCTURE_LIMIT": 1_000_000, "JSON_NUMERIC_LIMIT": 160_000_000,
          "JSON_MAX_DEPTH": 40, "MESH_COORDINATE_LIMIT": 30_000_000,
          "MESH_INDEX_LIMIT": 90_000_000}


def python_guard(value, **limits):
    overrides = {"_" + key: value for key, value in limits.items()}
    with patch.multiple(schema, **overrides):
        schema._json_guard(value)


def javascript_checks(rows, **limits):
    node = shutil.which("node")
    if not node:
        raise unittest.SkipTest("Node is unavailable; Python budget checks still run")
    source = JS_PATH.read_text(encoding="utf-8")
    start = source.index(" function jsonGuard(")
    end = source.index("\n function validateCase(", start)
    policy = {**POLICY, **limits}
    # Load the production translator too: validators now author localized copy.
    # Only its initial language needs a DOM value; no viewer or DOM tree is mounted.
    script = "const fs=require('fs');global.window={};global.document={documentElement:{lang:'zh-CN'}};\n"
    script += "const viewer=fs.readFileSync(process.argv[1],'utf8');\n"
    script += "require('vm').runInThisContext(viewer.slice(0,viewer.indexOf('(() => {')));\n"
    script += "const tr=window.StarCapsuleI18n.t;\n"
    script += "const " + ",".join(f"{key}={value}" for key, value in policy.items()) + ";\n"
    script += "const obj=v=>!!v&&typeof v==='object'&&!Array.isArray(v);\n"
    script += "const finite=v=>typeof v==='number'&&Number.isFinite(v);\n"
    script += "const assert=(ok,message)=>{if(!ok)throw new Error(message);};\n"
    script += source[start:end]
    script += "\nconst rows=JSON.parse(fs.readFileSync(0,'utf8'));const results=rows.map(row=>{"
    script += "try{const value=eval('('+row.expression+')');"
    script += "if(row.mesh)mesh(value,'test',row.fields||[]);else jsonGuard(value);"
    script += "return {ok:true};}catch(error){return {ok:false,error:error.message};}});"
    script += "process.stdout.write(JSON.stringify(results));"
    result = subprocess.run([node, "-e", script, str(JS_PATH.parent / "field-viewer.js")], input=json.dumps(rows), capture_output=True,
                            text=True, encoding="utf-8", timeout=30)
    if result.returncode:
        raise AssertionError(f"Extracted JS check failed: {result.stderr}")
    return json.loads(result.stdout)


class JsonBudgetChecks(unittest.TestCase):
    def test_python_and_browser_production_policies_match(self):
        source = JS_PATH.read_text(encoding="utf-8")
        for key, expected in POLICY.items():
            with self.subTest(key=key):
                self.assertEqual(getattr(schema, "_" + key), expected)
                self.assertEqual(int(re.search(r"\b" + key + r"=(\d+)", source)[1]), expected)
        self.assertGreaterEqual(schema._JSON_NUMERIC_LIMIT,
            schema._MESH_COORDINATE_LIMIT + schema._MESH_INDEX_LIMIT + 2 * schema._MESH_COORDINATE_LIMIT // 3)

    def test_dense_data_does_not_consume_scalar_metadata_nodes(self):
        value = {"positions": [0, 1, 2], "indices": [0, 1, 2]}
        before = copy.deepcopy(value)
        original_positions, original_indices = value["positions"], value["indices"]
        python_guard(value, JSON_STRUCTURE_LIMIT=3, JSON_NUMERIC_LIMIT=6)
        self.assertEqual(value, before)
        self.assertIs(value["positions"], original_positions)
        self.assertIs(value["indices"], original_indices)

    def test_numeric_budget_is_aggregate_across_arrays(self):
        value = {"a": [1, 2, 3], "b": [4, 5, 6, 7]}
        with self.assertRaisesRegex(ValueError, r"numeric-data.*7 > 6.*reduce"):
            python_guard(value, JSON_STRUCTURE_LIMIT=3, JSON_NUMERIC_LIMIT=6)

    def test_nested_mixed_and_boolean_arrays_still_consume_structure(self):
        for value in ([[], [], [], [], []], {"a": [1, True, 3, 4]},
                      {"a": [{"b": 1}, {"c": 2}]}):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, r"structure.*6 > 5.*reduce"):
                python_guard(value, JSON_STRUCTURE_LIMIT=5, JSON_NUMERIC_LIMIT=100)

    def test_depth_limit_includes_numeric_leaves(self):
        python_guard([[[[1]]]], JSON_MAX_DEPTH=4)
        with self.assertRaisesRegex(ValueError, r"depth.*5 > 4"):
            python_guard([[[[[1]]]]], JSON_MAX_DEPTH=4)

    def test_flat_and_hidden_nonfinite_numbers_remain_rejected(self):
        for invalid in (float("nan"), float("inf"), -float("inf"), 10 ** 400):
            for value in ([0, invalid], {"metadata": {"unexpected": invalid}}, [0, "mixed", invalid]):
                with self.subTest(value=value), self.assertRaisesRegex(ValueError, "finite"):
                    schema._json_guard(value)

    def test_unsafe_keys_and_nonjson_values_remain_rejected(self):
        for value in ({key: []} for key in ("__proto__", "prototype", "constructor")):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "unsafe"):
                schema._json_guard(value)
        for value in ({1: "nonstring key"}, {"value": {1, 2}}, {"value": object()}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                schema._json_guard(value)

    def test_mesh_coordinate_and_index_limits_match_browser_boundaries(self):
        triangle = {"positions": [0, 0, 0, 0, 1, 0, 0, 0, 1], "indices": [0, 1, 2], "cp": [1, 2, 3]}
        with patch.multiple(schema, _MESH_COORDINATE_LIMIT=9, _MESH_INDEX_LIMIT=3):
            self.assertEqual(schema._mesh(triangle, "test", ["cp"]), 3)
            too_many_indices = {**triangle, "indices": [0, 1, 2, 0, 1, 2]}
            with self.assertRaisesRegex(ValueError, r"index count 6 exceeds 3.*reduce"):
                schema._mesh(too_many_indices, "test", ["cp"])
        with patch.object(schema, "_MESH_COORDINATE_LIMIT", 8), self.assertRaisesRegex(
                ValueError, r"coordinate count 9 exceeds 8.*reduce"):
            schema._mesh(triangle, "test", ["cp"])

    def test_extracted_browser_guard_matches_python_boundary_and_security_vectors(self):
        values = [{"a": [1, 2, 3], "b": [4, 5, 6]},
                  {"a": [1, 2, 3], "b": [4, 5, 6, 7]},
                  [[], [], [], [], []], {"a": [1, True, 3]}, {"a": [1, True, 3, 4]},
                  {"a": {"b": {"c": 1}}}, [[[[1]]]], [[[[[1]]]]],
                  {"metadata": {"hidden": float("nan")}}, [0, float("inf")],
                  [0, "mixed", -float("inf")], {"prototype": {}}, {"constructor": {}},
                  {"__proto__": {}}, [], None, True]
        limits = {"JSON_STRUCTURE_LIMIT": 5, "JSON_NUMERIC_LIMIT": 6, "JSON_MAX_DEPTH": 4}
        expected = []
        for value in values:
            try:
                python_guard(value, **limits)
                expected.append(True)
            except ValueError:
                expected.append(False)
        rows = [{"expression": json.dumps(value)} for value in values]
        results = javascript_checks(rows, **limits)
        self.assertEqual([row["ok"] for row in results], expected)
        self.assertIn("7", results[1]["error"])
        self.assertIn("6", results[1]["error"])
        self.assertIn("拆分", results[1]["error"])

    def test_browser_rejects_sparse_arrays_and_nonjson_objects(self):
        results = javascript_checks([{"expression": expression} for expression in
            ("[0,,2]", "new Date()", "({value:undefined})", "({value:1n})", "({value:NaN})")])
        self.assertTrue(all(not result["ok"] for result in results))

    def test_browser_mesh_limit_errors_report_quantity_and_action(self):
        triangle = {"positions": [0, 0, 0, 0, 1, 0, 0, 0, 1], "indices": [0, 1, 2], "cp": [1, 2, 3]}
        rows = [{"expression": json.dumps(value), "mesh": True, "fields": ["cp"]} for value in
                (triangle, {**triangle, "indices": [0, 1, 2, 0, 1, 2]})]
        results = javascript_checks(rows, MESH_COORDINATE_LIMIT=9, MESH_INDEX_LIMIT=3)
        self.assertEqual([row["ok"] for row in results], [True, False])
        self.assertIn("6", results[1]["error"])
        self.assertIn("3", results[1]["error"])
        self.assertIn("拆分", results[1]["error"])
        result = javascript_checks(rows[:1], MESH_COORDINATE_LIMIT=8)[0]
        self.assertFalse(result["ok"])
        self.assertIn("9", result["error"])
        self.assertIn("8", result["error"])


if __name__ == "__main__":
    unittest.main()
