"""Joint native-layer contract checks; no STAR process or real model is used."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from cfd_review.demo import make_demo_case
from cfd_review.star import _resolve_native_layer_columns,prepare_macro
from cfd_review.mesh_io import pack_case


def configuration(colored=True):
    layer={"id":"q","name":"Synthetic configured surface","derivedPart":"EXAMPLE_ISO","kind":"isosurface"}
    if colored:layer.update(fieldFunction="EXAMPLE_VECTOR_MAGNITUDE",magnitudeOf="EXAMPLE_VECTOR")
    return {"schema":"cfd-review-star-config","version":1,"id":"example","name":"Synthetic preparation",
        "representation":"Volume Mesh","meta":copy.deepcopy(make_demo_case()["data"]["meta"]),
        "surfaces":[],"fields":{},"xSections":[],"layers":[layer]}


class JointAdapterChecks(unittest.TestCase):
    def test_colored_layers_use_one_native_joint_dataset(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan=prepare_macro(configuration(),Path(tmp)/"prepared")
            macro=Path(plan["macro"]).read_text(encoding="utf-8")
            pack=json.loads((Path(plan["rawDirectory"])/"pack-config.json").read_text(encoding="utf-8"))
            layer=pack["layers"][0]
            self.assertEqual(layer["ensight"],"layer_q.case")
            self.assertNotIn("csv",layer);self.assertNotIn("stl",layer)
            self.assertEqual(set(plan["expectedFiles"]),{"references.json","layer_q.case","layer_q.meta.json"})
            self.assertIn('exportJointPart(l0, "layer_q", lf0)',macro)
            self.assertIn('existingScalar("EXAMPLE_VECTOR_MAGNITUDE","EXAMPLE_VECTOR")',macro)
            self.assertIn('reference(lf0)',macro)
            self.assertNotIn('reference("EXAMPLE_VECTOR_MAGNITUDE")',macro)
            self.assertIn('Arrays.asList(part),Arrays.asList(field),false,true',macro)
            self.assertNotIn('setFieldFunctions(Collections.<NamedObject>singletonList(part)',macro)
            for unsafe in ('.run(','.step(','.saveState(','.clearSolution(','.initializeSolution('):
                self.assertNotIn(unsafe,macro)

    def test_geometry_only_layers_preserve_native_stl_without_scalar(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan=prepare_macro(configuration(False),tmp)
            pack=json.loads((Path(plan["rawDirectory"])/"pack-config.json").read_text(encoding="utf-8"))
            self.assertEqual(pack["layers"][0]["stl"],"layer_q.stl")
            self.assertEqual(pack["layers"][0]["fields"],{})
            self.assertNotIn("ensight",pack["layers"][0])
            self.assertNotIn("layer_q.csv",plan["expectedFiles"])

    def test_new_planes_still_require_explicit_coefficient_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            config=configuration();config.update(xSections=[0],sectionRegions=["EXAMPLE"])
            output=Path(tmp)/"unwritten"
            with self.assertRaisesRegex(ValueError,"at least one"):
                prepare_macro(config,output)
            self.assertFalse(output.exists())

    def test_walls_require_a_coefficient_field_even_with_existing_layers(self):
        with tempfile.TemporaryDirectory() as tmp:
            config=configuration();config["surfaces"]=[{"id":"wall","name":"Synthetic wall",
                "boundaries":[{"region":"Synthetic region","name":"Synthetic boundary"}]}]
            output=Path(tmp)/"unwritten"
            with self.assertRaisesRegex(ValueError,"at least one"):
                prepare_macro(config,output)
            self.assertFalse(output.exists())

    def test_actual_native_units_and_association_are_required(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw=Path(tmp);meta={"complete":True,"dataAtVerts":True,"fieldFunction":"Magnitude",
                "internalUnitsSuffix":" (/s)","internalUnitsName":"/s","representation":"Volume Mesh"}
            path=raw/"q.meta.json";path.write_text(json.dumps(meta),encoding="utf-8")
            entry={"ensight":"q.case","nativeMeta":"q.meta.json","sourceFieldFunction":"Magnitude"}
            pack={"layers":[copy.deepcopy(entry)]};_resolve_native_layer_columns(pack,raw)
            self.assertEqual(pack["layers"][0]["units"],"1/s")
            self.assertTrue(pack["layers"][0]["nativeAssociation"]["dataAtVerts"])
            for changes in [{"dataAtVerts":False},{"fieldFunction":"Other"},{"internalUnitsSuffix":None}]:
                path.write_text(json.dumps({**meta,**changes}),encoding="utf-8")
                with self.assertRaises(ValueError):_resolve_native_layer_columns({"layers":[copy.deepcopy(entry)]},raw)
            path.write_text(json.dumps(meta),encoding="utf-8")
            with self.assertRaisesRegex(ValueError,"units"):
                _resolve_native_layer_columns({"layers":[{**entry,"units":"Pa"}]},raw)

    def test_joint_color_range_uses_only_actual_surface_nodes(self):
        native={"id":"1","name":"Native surface","positions":[0,0,0,1,0,0,0,1,0,5,5,5],
            "indices":[0,1,2],"values":[1,2,3,1000],"field":"Scalar",
            "provenance":{"surfaceValueRange":[1,3],"unusedNodeCount":1,
                "omittedNonSurfaceElements":{"bar2":1}}}
        cfg={"schema":"cfd-review-pack","version":1,"id":"example","name":"Synthetic joint packing",
            "meta":copy.deepcopy(make_demo_case()["data"]["meta"]),"parts":[],"sections":[],
            "layers":[{"id":"q","name":"Native face","kind":"isosurface","ensight":"q.case",
                "sourceFieldFunction":"Scalar","field":"Scalar","units":"1/s"}]}
        with patch("cfd_review.ensight.read_case",return_value=[native]):
            layer=pack_case(cfg)["data"]["layers"][0]
        self.assertEqual(layer["values"],[1,2,3,1000])
        self.assertEqual(layer["indices"],[0,1,2])
        self.assertEqual(layer["colorRange"],[1,3])
        self.assertEqual(layer["provenance"]["parts"][0]["provenance"]["omittedNonSurfaceElements"],{"bar2":1})


if __name__=="__main__":unittest.main()
