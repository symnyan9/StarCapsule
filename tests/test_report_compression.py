"""Lossless bounded HTML compression; all meshes and values are synthetic."""
from __future__ import annotations

import base64
import copy
import gzip
import json
import math
from pathlib import Path
import re
import random
import tempfile
import unittest
from unittest.mock import patch

from cfd_review.comparison import compose_half_comparison
from cfd_review.demo import make_demo_project
from cfd_review.report import _json_fragments, _json_payload, build_report, load_report_document, upgrade_report


def envelope(raw, *, width=5):
    packed = gzip.compress(raw, compresslevel=6, mtime=0)
    return {"schema": "cfd-review-compressed", "version": 1, "encoding": "gzip-base64",
            "decodedBytes": len(raw), "chunks": [base64.b64encode(packed[i:i + width]).decode("ascii")
                                                   for i in range(0, len(packed), width)]}


class ReportCompressionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "compressed.html"
        self.project = make_demo_project()
        for case in self.project["cases"]:
            case["data"]["parts"] = [{"id": "wall", "name": "Synthetic wall",
                "positions": [0, 0, .2, .2, .2, .2, .4, .3, .4], "indices": [0, 1, 2],
                "cp": [-0.0, .12345678901234568, 1e-300]}]
            case["data"]["sections"] = []
            case["data"]["layers"] = []
        self.project["title"] = 'Synthetic 压力 </script> & \u2028 \u2029'

    def write_slot(self, document):
        self.path.write_text('<script id="cfd-project-data" type="application/json">' +
                             _json_payload(document) + '</script>', encoding="utf-8")

    def primary(self):
        html = self.path.read_text(encoding="utf-8")
        return json.loads(re.search(r'<script id="cfd-project-data" type="application/json">(.*?)</script>', html, re.S)[1])

    def test_independently_padded_chunks_restore_exact_scientific_values(self):
        raw = _json_payload(self.project).encode("utf-8")
        packed = envelope(raw)
        self.assertTrue(all(chunk.endswith("=") for chunk in packed["chunks"][:-1]))
        self.write_slot(packed)
        result = load_report_document(self.path)
        self.assertEqual(result, self.project)
        value = result["cases"][0]["data"]["parts"][0]["cp"][0]
        self.assertEqual(math.copysign(1, value), -1)

    def test_default_large_slot_compresses_with_streamed_json_and_no_legacy_dumps(self):
        self.project["cases"][0]["data"]["meta"]["syntheticRepeatedText"] = "Synthetic field data " * 60000
        with patch("cfd_review.report._json_payload", side_effect=AssertionError("Do not allocate one large JSON string")):
            build_report(self.project, self.path)
        self.assertEqual(self.primary()["schema"], "cfd-review-compressed")
        self.assertEqual(load_report_document(self.path), self.project)

    def test_small_legacy_document_stays_plain_and_streamed_json_matches_legacy_text(self):
        self.assertEqual("".join(_json_fragments(self.project)), _json_payload(self.project))
        build_report(self.project, self.path)
        self.assertEqual(self.primary(), self.project)
        self.assertEqual(load_report_document(self.path), self.project)

    def test_writer_is_deterministic_and_chunks_respect_the_envelope_contract(self):
        with patch("cfd_review.report._COMPRESSION_THRESHOLD_BYTES", 1):
            build_report(self.project, self.path)
            first = self.primary()
            build_report(self.project, self.path, overwrite=True)
        self.assertEqual(self.primary(), first)
        self.assertEqual(set(first), {"schema", "version", "encoding", "decodedBytes", "chunks"})
        self.assertTrue(all(1 <= len(chunk) <= 1024 * 1024 for chunk in first["chunks"]))
        raw = gzip.decompress(b"".join(base64.b64decode(c, validate=True) for c in first["chunks"]))
        self.assertEqual(raw, _json_payload(self.project).encode("utf-8"))
        self.assertEqual(first["decodedBytes"], len(raw))

    def test_large_compressed_payload_uses_multiple_bounded_independent_chunks(self):
        self.project["cases"][0]["data"]["meta"]["syntheticRandomHex"] = random.Random(42).randbytes(1024 * 1024).hex()
        build_report(self.project, self.path)
        stored = self.primary()
        self.assertGreaterEqual(len(stored["chunks"]), 2)
        self.assertTrue(all(len(chunk) == 1024 * 1024 for chunk in stored["chunks"][:-1]))
        self.assertEqual(load_report_document(self.path), self.project)

    def test_primary_bundle_cases_and_recipe_can_each_be_decoded(self):
        a, b = self.project["cases"]
        derived = compose_half_comparison(a, b, case_id="synthetic-stitch")
        self.project["cases"].append(derived)
        with patch("cfd_review.report._COMPRESSION_THRESHOLD_BYTES", 1):
            build_report(self.project, self.path)
        self.assertEqual(self.primary()["schema"], "cfd-review-compressed")
        html = self.path.read_text(encoding="utf-8")
        recipe = json.loads(re.search(r'<script id="cfd-case-data-2" type="application/json">(.*?)</script>', html, re.S)[1])
        self.assertEqual(recipe["schema"], "cfd-review-composition")
        self.assertEqual(load_report_document(self.path), self.project)
        # Any slot may be compressed, including a small recipe supplied by a
        # compatible writer. The normal writer deliberately leaves it plain.
        html = html.replace(_json_payload(recipe), _json_payload(envelope(_json_payload(recipe).encode("utf-8"))))
        self.path.write_text(html, encoding="utf-8")
        self.assertEqual(load_report_document(self.path), self.project)

    def test_upgrading_compressed_report_keeps_source_file_and_scientific_data(self):
        self.write_slot(envelope(_json_payload(self.project).encode("utf-8")))
        before = self.path.read_bytes()
        output = self.path.with_name("updated.html")
        upgrade_report(self.path, output)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(load_report_document(output), self.project)

    def test_envelope_requires_exact_keys_version_encoding_sizes_and_chunks(self):
        valid = envelope(_json_payload(self.project).encode("utf-8"))
        mutations = [("extra", True), ("version", True), ("version", 2), ("encoding", "deflate"),
                     ("decodedBytes", True), ("decodedBytes", 0), ("decodedBytes", 500 * 1024 * 1024 + 1),
                     ("chunks", "wrong-type"), ("chunks", []), ("chunks", [""]), ("chunks", [None]),
                     ("chunks", ["a" * (1024 * 1024 + 1)])]
        for key, value in mutations:
            with self.subTest(key=key, value=str(value)[:40]):
                invalid = copy.deepcopy(valid)
                invalid[key] = value
                self.write_slot(invalid)
                with self.assertRaises(ValueError):
                    load_report_document(self.path)

    def test_base64_must_be_strict_canonical_and_independently_decodable(self):
        valid = envelope(_json_payload(self.project).encode("utf-8"))
        for value in ("!!!=", "Zg=", "Zg==\n", "Zg==Zg==", "Zh==", "压力"):
            invalid = copy.deepcopy(valid)
            invalid["chunks"] = [value]
            self.write_slot(invalid)
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "base64"):
                load_report_document(self.path)

    def test_corrupt_truncated_and_trailing_invalid_gzip_are_rejected(self):
        raw = _json_payload(self.project).encode("utf-8")
        packed = gzip.compress(raw, mtime=0)
        corrupt = bytearray(packed)
        corrupt[-8] ^= 1
        for data in (packed[:-1], packed[:-8], bytes(corrupt), packed + b"invalid-trailer", b"not-gzip"):
            invalid = envelope(raw)
            invalid["chunks"] = [base64.b64encode(data).decode("ascii")]
            self.write_slot(invalid)
            with self.subTest(length=len(data)), self.assertRaisesRegex(ValueError, "gzip"):
                load_report_document(self.path)

    def test_declared_size_mismatch_and_small_declared_zip_bomb_are_rejected(self):
        raw = _json_payload(self.project).encode("utf-8")
        for declared in (1, len(raw) - 1, len(raw) + 1):
            invalid = envelope(raw)
            invalid["decodedBytes"] = declared
            self.write_slot(invalid)
            with self.subTest(declared=declared), self.assertRaisesRegex(ValueError, "decodedBytes"):
                load_report_document(self.path)
        invalid = envelope(b'"' + b"a" * 100000 + b'"')
        invalid["decodedBytes"] = 128
        self.write_slot(invalid)
        with self.assertRaisesRegex(ValueError, "exceeds.*decodedBytes"):
            load_report_document(self.path)

    def test_nested_envelope_duplicate_keys_nonfinite_and_invalid_utf8_are_rejected(self):
        inner = envelope(_json_payload(self.project).encode("utf-8"))
        variants = [_json_payload(inner).encode("utf-8"), b'{"a":1,"a":2}', b'{"value":NaN}', b"\xff"]
        for raw in variants:
            self.write_slot(envelope(raw))
            with self.subTest(raw=raw[:40]), self.assertRaises(ValueError):
                load_report_document(self.path)

    def test_raw_and_packed_output_bounds_remove_partial_report(self):
        with patch("cfd_review.report._MAX_JSON_SLOT_BYTES", 64):
            with self.assertRaisesRegex(ValueError, "500 MiB output limit"):
                build_report(self.project, self.path)
        self.assertFalse(self.path.exists())
        with patch("cfd_review.report._MAX_JSON_SLOT_BYTES", 4096), patch(
                "cfd_review.report._COMPRESSION_THRESHOLD_BYTES", 1), patch(
                "cfd_review.report._BASE64_INPUT_BYTES", 1):
            with self.assertRaisesRegex(ValueError, "500 MiB output limit"):
                build_report(self.project, self.path)
        self.assertFalse(self.path.exists())

    def test_build_spools_all_scientific_data_beside_output_and_cleans_up(self):
        self.path = self.path.parent / "chosen-output" / self.path.name
        temporary_file = tempfile.TemporaryFile
        with patch("cfd_review.report.tempfile.TemporaryFile", wraps=temporary_file) as spools, patch(
                "cfd_review.report._COMPRESSION_THRESHOLD_BYTES", 1), patch(
                "cfd_review.report._BUNDLE_THRESHOLD_BYTES", 1):
            build_report(self.project, self.path)
        self.assertGreaterEqual(spools.call_count, 9)
        self.assertTrue(all(call.kwargs["dir"] == self.path.parent.resolve() for call in spools.call_args_list))
        self.assertEqual(set(self.path.parent.iterdir()), {self.path})

    def test_compression_error_preserves_existing_output_and_removes_its_spools(self):
        self.path.write_bytes(b"existing report must remain unchanged")
        temporary_file = tempfile.TemporaryFile
        with patch("cfd_review.report.tempfile.TemporaryFile", wraps=temporary_file) as spools, patch(
                "cfd_review.report._COMPRESSION_THRESHOLD_BYTES", 1), patch(
                "cfd_review.report.gzip.GzipFile", side_effect=OSError("Synthetic compression failure")):
            with self.assertRaisesRegex(OSError, "Synthetic compression failure"):
                build_report(self.project, self.path, overwrite=True)
        self.assertTrue(all(call.kwargs["dir"] == self.path.parent.resolve() for call in spools.call_args_list))
        self.assertEqual(self.path.read_bytes(), b"existing report must remain unchanged")
        self.assertEqual(set(self.path.parent.iterdir()), {self.path})


if __name__ == "__main__":
    unittest.main()
