"""Display-only CpT thresholds preserve source values and saved review state."""
import copy
from html.parser import HTMLParser
import json
from pathlib import Path
import shutil
import subprocess
import unittest

from cfd_review.demo import make_demo_project
from cfd_review.report import render_report
from cfd_review.schema import validate_case, validate_project, validate_state


ASSETS = Path(__file__).resolve().parents[1] / "src" / "cfd_review" / "assets"


class ThresholdChecks(unittest.TestCase):
    def setUp(self):
        self.project = make_demo_project()
        self.case = self.project["cases"][0]
        self.state = {"sourceId": self.case["data"]["meta"]["sourceKey"],
                      "hideNearOne": True, "cptTransparentAbove": 1.035}

    def test_finite_thresholds_are_not_artificially_bounded_to_zero_one(self):
        for threshold in (-5, 0, .98, 1.048, 12):
            self.case["data"]["meta"]["cptTransparentAbove"] = threshold
            self.state["cptTransparentAbove"] = threshold
            validate_case(self.case)
            validate_state(self.state, self.case)

    def test_invalid_meta_and_state_thresholds_are_rejected(self):
        for threshold in (None, True, False, "1", [], {}, float("nan"),
                          float("inf"), -float("inf")):
            with self.subTest(value=threshold):
                case = copy.deepcopy(self.case)
                case["data"]["meta"]["cptTransparentAbove"] = threshold
                with self.assertRaises(ValueError):
                    validate_case(case)
                state = {**self.state, "cptTransparentAbove": threshold}
                with self.assertRaises(ValueError):
                    validate_state(state, self.case)

    def test_view_and_note_thresholds_survive_html_json_roundtrip(self):
        self.project["views"][0]["state"] = self.state
        self.project["notes"] = [{"id": "threshold-check", "caseId": self.case["id"],
            "view": 0, "text": "Inspect retained low-total-pressure region",
            "state": copy.deepcopy(self.state)}]
        before = copy.deepcopy(self.project["cases"])
        restored = json.loads(json.dumps(validate_project(self.project)))
        html = render_report(restored)

        class Payload(HTMLParser):
            def __init__(self):
                super().__init__(); self.active = False; self.parts = []
            def handle_starttag(self, tag, attrs):
                if tag == "script": self.active = dict(attrs).get("id") == "cfd-project-data"
            def handle_endtag(self, tag):
                if tag == "script": self.active = False
            def handle_data(self, text):
                if self.active: self.parts.append(text)

        parser = Payload(); parser.feed(html)
        exported = json.loads("".join(parser.parts))
        self.assertEqual(exported["views"][0]["state"], self.state)
        self.assertEqual(exported["notes"][0]["state"], self.state)
        self.assertEqual(exported["cases"], before)
        # Legacy saved reviews keep working without a threshold field.
        del restored["views"][0]["state"]["cptTransparentAbove"]
        del restored["notes"][0]["state"]["cptTransparentAbove"]
        validate_project(restored)

    def test_production_viewer_alpha_picking_modes_and_state(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node unavailable; Python roundtrip checks still run")
        script = r"""
const fs=require('fs'),vm=require('vm'),assert=require('assert');
global.window={};global.document={documentElement:{lang:'zh-CN'}};
global.THREE=require(process.argv[1]);window.THREE=THREE;
let source=fs.readFileSync(process.argv[2],'utf8');
// Test-only exposure of the production class, with no exported product test API.
source=source.replace('window.DefenseFieldViewer={mount:(root,data)=>new FieldViewer(root,data)};',
                      'window.TestFieldViewer=FieldViewer;');
vm.runInThisContext(source);
const v=Object.create(window.TestFieldViewer.prototype),nodes=new Map();
const element=key=>{if(!nodes.has(key))nodes.set(key,{value:'',checked:false,hidden:false,disabled:false,
 textContent:'',setAttribute(k,x){this[k]=x},removeAttribute(k){delete this[k]}});return nodes.get(key)};
const payload={x:0,positions:[0,0,0,0,1,0,0,0,1,0,0,0,0,1,0,0,0,1,0,.5,.5],
 indices:[0,1,2,3,4,5],cpt:[.1,.2,.3,.98,1.048,2,.9799999],cp:[.4,.5,.6,1,2,3,.9]};
const original=JSON.stringify(payload),ranges={surfaceCp:[-3,1],section:{Cp:[-3,1],CpT:[-.5,1]}};
Object.assign(v,{meta:{sourceKey:'synthetic-threshold',units:'m'},data:{parts:[]},sections:[payload],
 parts:[],layers:[],meshes:[],layerMeshes:[],availableFields:['Cp','CpT'],sectionIndex:0,
 variable:'CpT',hideNearOne:true,cptTransparentAbove:.98,sectionOpacity:.75,sectionVisible:true,
 bodyMode:'context',bodyOpacity:1,playing:false,_loadToken:0,_initialFitDone:true,mirror:false,
 // Structured readout DOM is exercised by the browser suite; this fixture isolates scalar alpha/state.
 _mirrorEligibility:{enabled:false,reason:'test source is not half'},_syncMirrorControls(){},_showPick(){},
 fieldLabel:n=>n,lengthFactor:1000,lengthUnit:'mm',el:element,$:element,$$:()=>[],
 colorRanges:JSON.parse(JSON.stringify(ranges)),defaultColorRanges:ranges,
 camera:new THREE.PerspectiveCamera(),controls:{target:new THREE.Vector3(),update(){},enableDamping:false},
 sectionGroup:new THREE.Group(),scene:new THREE.Scene(),pointer:new THREE.Vector2(),
 renderer:{domElement:{getBoundingClientRect:()=>({left:0,top:0,width:100,height:100})}},
 _emit(){},_updateLegends(){},_fit(){return true}});
v.camera.position.set(2,-3,2);
const alphas=()=>Array.from(v.sectionMesh.geometry.getAttribute('color').array).filter((_,i)=>i%4===3);
const point=new THREE.Vector3(0,.25,.25);let face=0;
v.raycaster={setFromCamera(){},intersectObjects(){return [{object:v.sectionMesh,faceIndex:face,
 face:{materialIndex:0},point:point.clone()}]}};
const pick=()=>v._pick({clientX:50,clientY:50},false);
(async()=>{
 await v.setSection(0);
 assert.deepStrictEqual(alphas(),[1,1,1,0,0,0,1]); // Equality and values well above 1 disappear.
 const reading=pick();assert(Math.abs(reading.value-.175)<1e-12);
 face=1;assert.strictEqual(pick(),null);face=0;
 v.setColorRange('section',-10,20,'CpT');
 assert.deepStrictEqual(alphas(),[1,1,1,0,0,0,1]);assert.strictEqual(pick().value,reading.value);
 element('cpt-threshold-value').value='1.05';assert(v._applyThresholdInput());
 assert.deepStrictEqual(alphas(),[1,1,1,1,1,0,1]);
 element('cpt-threshold-value').value='';assert.strictEqual(v._applyThresholdInput(),false);
 assert.strictEqual(v.cptTransparentAbove,1.05);assert(element('cpt-threshold-value')['aria-invalid']);
 element('cpt-threshold-value').value='-2';assert(v._applyThresholdInput());
 assert(alphas().every(n=>n===0));
 element('cpt-threshold-value').value='1.05';assert(v._applyThresholdInput());
 await v.setField('Cp');assert(alphas().every(n=>n===1));
 assert(element('cpt-threshold-controls').hidden);assert(element('cpt-threshold-value').disabled);
 await v.setField('CpT');assert(!element('cpt-threshold-controls').hidden);
 assert.deepStrictEqual(alphas(),[1,1,1,1,1,0,1]);
 v.hideNearOne=false;v._updateSectionAppearance();assert(alphas().every(n=>n===1));
 v.hideNearOne=true;v._updateSectionAppearance();pick();
 const saved=JSON.parse(JSON.stringify(v.getState()));assert.strictEqual(saved.cptTransparentAbove,1.05);
 v.cptTransparentAbove=.5;await v.setState(saved);
 assert.strictEqual(v.cptTransparentAbove,1.05);assert.strictEqual(v.lastPick.value,reading.value);
 assert.strictEqual(element('cpt-threshold-value').value,'1.05');
 const legacy={...saved};delete legacy.cptTransparentAbove;await v.setState(legacy);
 assert.strictEqual(v.cptTransparentAbove,1.05);
 for(const invalid of [null,true,'1',NaN,Infinity,-Infinity]){
  await assert.rejects(v.setState({...saved,cptTransparentAbove:invalid}),/有限/);
 }
 assert.strictEqual(JSON.stringify(payload),original);assert.strictEqual(pick().value,reading.value);
 assert(!source.includes('this.nearOneTolerance'));assert(source.includes('this.meta.cptTransparentAbove:.98'));
 process.stdout.write(JSON.stringify({passed:true,sourceValuesPreserved:true,thresholdState:saved.cptTransparentAbove}));
})().catch(error=>{console.error(error);process.exitCode=1});
"""
        result = subprocess.run([node, "-e", script, str(ASSETS / "vendor" / "three.min.js"),
            str(ASSETS / "field-viewer.js")], capture_output=True, text=True,
            encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)["passed"])


if __name__ == "__main__":
    unittest.main()
