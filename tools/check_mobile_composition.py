"""Review pre-composed offline HTML on an emulated touch tablet.

Uses mathematical synthetic cases only. Tests both Python-saved compositions and
the browser's compose button. Chromium touch emulation is not physical iPad or
Safari validation, and this small fixture is not a real-model capacity test.
"""
from __future__ import annotations

import argparse
import base64
import copy
import gzip
import hashlib
import json
from pathlib import Path
import re
import sys
import traceback
from unittest.mock import patch

from playwright.sync_api import sync_playwright

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS.parent / "src"))
sys.path.insert(0, str(TOOLS))
from check_mobile import PRECISION, exact_differences, synthetic_project
from cfd_review import report
from cfd_review.comparison import compose_half_comparison
from cfd_review.demo import _section


SLOTS = re.compile(r'<script\b[^>]*\bid="(cfd-project-data|cfd-case-data-\d+|'
                   r'cfd-section-data-\d+-\d+|cfd-layer-data-\d+-\d+)"[^>]*>'
                   r'([\s\S]*?)</script\s*>', re.I)
FIND_POINT = """wanted => {
 const v=CFDStudio.viewers[0],r=v.renderer.domElement.getBoundingClientRect();
 v.camera.updateMatrixWorld(true);v.scene.updateMatrixWorld(true);
 const candidates=[...v.meshes,...v.sectionGroup.children,...v.layerMeshes]
  .filter(m=>m.visible&&m.userData.kind===wanted.kind);
 for(const mesh of candidates){const p=mesh.geometry.getAttribute('position'),ix=mesh.geometry.index;
  for(let j=0;j<ix.count;j+=3){const ids=[ix.getX(j),ix.getX(j+1),ix.getX(j+2)],
   center=ids.reduce((sum,i)=>sum.add(new THREE.Vector3().fromBufferAttribute(p,i)),new THREE.Vector3()).multiplyScalar(1/3),
   screen=mesh.localToWorld(center).project(v.camera);
   if(Math.abs(screen.x)>.9||Math.abs(screen.y)>.9||screen.z>1)continue;
   const event={clientX:r.left+(screen.x+1)*r.width/2,clientY:r.top+(1-screen.y)*r.height/2},pick=v._pick(event,false);
   if(pick?.sourceSide===wanted.side&&pick.kind===wanted.kind)return {x:event.clientX,y:event.clientY};
  }
 }throw Error('No visible source triangle for '+wanted.kind+' / '+wanted.side);
}"""


def slots_from(path):
    result = {}
    for identifier, text in SLOTS.findall(path.read_text(encoding="utf-8")):
        item = json.loads(text)
        if item.get("schema") == "cfd-review-compressed":
            packed = b"".join(base64.b64decode(chunk, validate=True) for chunk in item["chunks"])
            item = json.loads(gzip.decompress(packed))
        if identifier in result:
            raise AssertionError("Duplicate data slot")
        result[identifier] = item
    return result


def fixtures():
    a, b = synthetic_project()["cases"][:2]
    # Both sources have fourteen genuinely shared X coordinates. Scalars differ.
    b["data"]["sections"] = [_section(cut["x"], 1) for cut in a["data"]["sections"]]
    for cut in (b["data"]["sections"][0], b["data"]["sections"][-1]):
        cut["cp"][:3] = PRECISION
        cut["cpt"][:3] = PRECISION
    derived = compose_half_comparison(a, b)
    composed = report.project_from_cases([a, b, derived], "Synthetic pre-composed tablet review")
    composed["views"] = [{"caseId": derived["id"], "state": None}]
    composed["ui"] = {"language": "en", "mobileMode": "auto"}
    originals = report.project_from_cases([a, b], "Synthetic tablet compose button")
    originals["ui"] = {"language": "en", "mobileMode": "auto"}
    legacy = copy.deepcopy(derived)
    legacy["id"] = "synthetic-legacy-full-derived"
    legacy["name"] = "DEMO legacy full-derived composition"
    legacy["data"]["meta"]["title"] = legacy["name"]
    legacy["data"]["meta"]["sourceKey"] = "synthetic-legacy-full-derived-source"
    legacy_project = report.project_from_cases([a, b, legacy], "Synthetic legacy full-derived tablet review")
    legacy_project["views"] = [{"caseId": legacy["id"], "state": None}]
    legacy_project["ui"] = {"language": "en", "mobileMode": "auto"}
    return composed, originals, legacy_project


def reflected_zero_equivalent(value):
    """Reflection of integer 0 may produce JS -0; scalar signs stay untouched."""
    if isinstance(value, dict):
        return {key: [0 if n == 0 else n for n in item] if key == "positions" and isinstance(item, list)
                else reflected_zero_equivalent(item) for key, item in value.items()}
    if isinstance(value, list):
        return [reflected_zero_equivalent(item) for item in value]
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--browser-executable", type=Path)
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    receipt = {"fixture": "Synthetic mathematical meshes only; no STAR or real CFD data",
               "scope": "Chromium 1024x768 touch emulation; not a physical iPad/Safari check",
               "checks": {}, "errors": [], "network": [], "metrics": {}, "passed": False}

    def check(label, passed):
        receipt["checks"][label] = bool(passed)
        if not passed:
            raise AssertionError(label)

    def compare(label, expected, actual, reflected=False):
        if reflected:
            expected, actual = map(reflected_zero_equivalent, (expected, actual))
        differences = exact_differences(expected, actual)
        if differences:
            receipt.setdefault("differences", {})[label] = differences
        check(label, not differences)

    try:
        composed, originals, legacy = fixtures()
        documents = {"precomposed": composed, "originals": originals, "legacy": legacy}
        files = {}
        for name, document in documents.items():
            with patch.object(report, "_SECTION_BUNDLE_THRESHOLD_BYTES", 0):
                files[name] = report.build_report(document, out / (name + "-v2.html"), overwrite=True)
        receipt["html"] = {name: {"bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()} for name, path in files.items()}
        packed = slots_from(files["precomposed"])
        manifest = packed["cfd-project-data"]
        check("Python saves a version 2 canonical composition recipe",
              manifest["schema"] == "cfd-review-html-bundle" and manifest["version"] == 2
              and packed["cfd-case-data-2"]["schema"] == "cfd-review-composition"
              and "summary" not in manifest["cases"][2])
        check("both originals retain all fourteen real cuts and separate raw layer slots",
              all(len(entry["sections"]) == 14 and len(entry.get("layerSlots", [])) == 1
                  and packed[entry["elementId"]]["data"]["layers"] == []
                  for entry in manifest["cases"][:2])
              and len([identifier for identifier in packed if identifier.startswith("cfd-section-data-")]) == 28
              and len([identifier for identifier in packed if identifier.startswith("cfd-layer-data-")]) == 2)
        compare("Python canonical recipe roundtrip preserves all scientific values and source identities",
                composed, report.load_report_document(files["precomposed"]))
        legacy_slots = slots_from(files["legacy"])
        check("noncanonical legacy composition is stored as full derived data",
              legacy_slots["cfd-case-data-2"]["schema"] == "cfd-review-case"
              and "summary" in legacy_slots["cfd-project-data"]["cases"][2])

        with sync_playwright() as playwright:
            launch = {"headless": True, "args": ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"]}
            if args.browser_executable:
                launch["executable_path"] = str(args.browser_executable.resolve(strict=True))
            browser = playwright.chromium.launch(**launch)
            context = browser.new_context(viewport={"width": 1024, "height": 768},
                device_scale_factor=2, is_mobile=True, has_touch=True, offline=True, accept_downloads=True)
            context.set_default_timeout(30000)

            def open_page(path, label):
                page = context.new_page()
                page.on("pageerror", lambda error: receipt["errors"].append({"page": label, "error": str(error)}))
                page.on("request", lambda request: receipt["network"].append(request.url)
                        if request.url.startswith(("http:", "https:")) else None)
                page.goto(path.as_uri())
                page.wait_for_function("() => !!window.CFDStudio")
                check(label + " opens offline from file", page.evaluate("CFDStudio.ready"))
                page.wait_for_function("() => CFDStudio.viewers.length===1&&!!CFDStudio.viewers[0].sectionMesh")
                return page

            def pick(page, kind, side, expected_sources, field):
                if not page.evaluate("CFDStudio.viewers[0].pickMode"):
                    page.locator('.studio-view[data-view="0"] [data-action="pick"]').tap()
                point = page.evaluate(FIND_POINT, {"kind": kind, "side": side})
                page.touchscreen.tap(point["x"], point["y"])
                result = page.evaluate("CFDStudio.viewers[0].lastPick")
                source = expected_sources[0 if side == "A" else 1]
                good = bool(result and result["kind"] == kind and result["sourceSide"] == side
                    and result["sourceCaseId"] == source["id"] and result["field"] == field
                    and result["sourceDataId"] == source["data"]["meta"]["sourceKey"]
                    and isinstance(result["value"], (int, float))
                    and abs(result["sourcePoint"][1] - result["displayPoint"][1] * result["sourceYSign"]) < 1e-8)
                if kind == "surface":
                    good = good and result["sourcePartId"] in {part["id"] for part in source["data"]["parts"]}
                if kind == "section":
                    if good:
                        cut = source["data"]["sections"][result["sourceSectionIndex"]]
                        good = abs(result["sourcePoint"][0] - cut["x"]) < 1e-6
                active_id = page.evaluate("CFDStudio.project.views[0].caseId")
                cut_index = result.get("sectionIndex", "missing") if result else "missing"
                check(f"{active_id} at cut {cut_index}: touch {kind} {field} source {side} and inverse Y mapping", good)
                receipt.setdefault("picks", []).append(result)
                return result

            try:
                page = open_page(files["precomposed"], "pre-composed tablet")
                check("pre-composed tablet retains one canvas and both independent surface sides", page.evaluate("""() => {
                  const v=CFDStudio.viewers[0];return document.documentElement.dataset.mobileReview==='true'
                  &&v.renderer.getPixelRatio()===1&&document.querySelectorAll('.fv-canvas canvas').length===1
                  &&v.meta.comparison?.sources.length===2&&!v.mirror&&['A','B'].every(side=>v.meshes.some(m=>m.userData.sourceSide===side))
                  &&v.meshes.every(m=>{const p=m.geometry.getAttribute('position');for(let i=0;i<p.count;i++)
                  if(m.userData.sourceSide==='A'?p.getY(i)>1e-6:p.getY(i)<-1e-6)return false;return !m.userData.mirrored;});}"""))
                first = receipt["metrics"]["initial"] = page.evaluate("CFDStudio.lazyMetrics")
                check("first display loads only the two source cores and their current real X cuts",
                      first["coreLoads"] == 2 and first["sectionLoads"] == 2
                      and first["residentCores"] == 3 and first["residentSections"] == 3)
                check("mobile layer geometry starts hidden and remains undecoded", page.evaluate("""() => {
                  const v=CFDStudio.viewers[0],m=CFDStudio.lazyMetrics;return v.layers.length===2
                  &&v.layers.every(l=>!l.visible&&!l.mesh&&!l.hydrated)
                  &&m.layerLoads===0&&m.residentLayers===0;}"""))
                compare("initial composed cut matches the Python same-X geometry and both scalar fields",
                        composed["cases"][2]["data"]["sections"][0],
                        page.evaluate("CFDStudio.viewers[0]._currentPayload.payload"), reflected=True)
                page.evaluate("CFDStudio.viewers[0].setSection(5)")
                current = receipt["metrics"]["selectedCut"] = page.evaluate("CFDStudio.lazyMetrics")
                check("one cut selection decodes exactly two new native source planes",
                      current["sectionLoads"] - first["sectionLoads"] == 2 and current["residentSections"] <= 6)
                compare("selected composed plane preserves its exact real source X and source ranges",
                        composed["cases"][2]["data"]["sections"][5],
                        page.evaluate("CFDStudio.viewers[0]._currentPayload.payload"), reflected=True)

                page.evaluate("""async () => {const v=CFDStudio.viewers[0],s=v.getState();s.selection=null;
                  s.sectionVisible=false;s.bodyMode='cp';await v.setState(s);
                  v.controls.enableDamping=false;v._fit('top');}""")
                for side in ("A", "B"):
                    pick(page, "surface", side, composed["cases"][:2], "Cp")
                page.screenshot(path=str(out / "tablet-composed-surfaces.png"))
                page.evaluate("""async () => {const v=CFDStudio.viewers[0],s=v.getState();s.selection=null;
                  s.bodyMode='hidden';s.sectionVisible=true;s.sectionOpacity=1;s.hideNearOne=false;
                  await v.setState(s);v._fit('front');}""")
                for field, key in (("Cp", "cp"), ("CpT", "cpt")):
                    page.evaluate("field=>CFDStudio.viewers[0].setField(field)", field)
                    compare("rendered " + field + " uses the source-valued composed vertex array",
                            composed["cases"][2]["data"]["sections"][5][key],
                            page.evaluate("CFDStudio.viewers[0].sectionMesh.userData.values"))
                    for side in ("A", "B"):
                        pick(page, "section", side, composed["cases"][:2], field)
                page.screenshot(path=str(out / "tablet-composed-section-pick.png"))
                scans = receipt["metrics"]["sectionScan"] = page.evaluate("""async () => {
                  const out=[];for(const i of [0,1,2,1,3,4,5,6,7,8,9,10,11,12,13,0]){
                  await CFDStudio.viewers[0].setSection(i);out.push({...CFDStudio.lazyMetrics});}return out;}""")
                check("two sources and composition each retain at most two cuts while scanning",
                      all(m["residentSections"] <= 6 and m["residentCores"] == 3 for m in scans)
                      and scans[3]["sectionCacheHits"] > scans[2]["sectionCacheHits"])

                # This visible checkbox exercises deferred raw-layer decoding,
                # rather than only checking whether GPU objects were allocated.
                page.locator('[data-action="toggle-settings"]').tap()
                page.locator('[data-layer="A-l-0"]').check()
                page.wait_for_function("() => CFDStudio.viewers[0].layers[0].visible&&!!CFDStudio.viewers[0].layers[0].mesh")
                check("enabling source A layer decodes only its raw source and derived layer", page.evaluate("""() => {
                  const v=CFDStudio.viewers[0],m=CFDStudio.lazyMetrics;return m.layerLoads===1
                  &&m.residentLayers===2&&v.layers[0].hydrated&&!v.layers[1].hydrated&&!v.layers[1].mesh;}"""))
                compare("on-demand reflected layer retains original scalar precision and source identity",
                        composed["cases"][2]["data"]["layers"][0],
                        page.evaluate("CFDStudio.viewers[0].layers[0].source"), reflected=True)
                page.locator('[data-layer="A-l-0"]').uncheck()
                page.wait_for_function("() => CFDStudio.lazyMetrics.residentLayers===0")
                check("hiding a layer releases both raw working payloads and GPU meshes", page.evaluate("""() => {
                  const l=CFDStudio.viewers[0].layers[0];return !l.visible&&!l.mesh&&!l.hydrated
                  &&l.source.positions.length===0&&CFDStudio.lazyMetrics.residentLayers===0;}"""))
                page.keyboard.press("Escape")

                page.evaluate("""async () => {const v=CFDStudio.viewers[0];await v.setSection(6);
                  await v.setColorRange('surface',-1.3,.6);await v.setColorRange('section',-.2,.91,'CpT');
                  v._fit('front');}""")
                pick(page, "section", "B", composed["cases"][:2], "CpT")
                page.evaluate("CFDStudio.addNote('Synthetic pre-composed tablet evidence: source B at shared X.',0)")
                before_save = page.evaluate("CFDStudio.lazyMetrics")
                with page.expect_download() as download:
                    page.evaluate("CFDStudio.downloadHTML()")
                saved = out / "tablet-precomposed-saved.html"
                download.value.save_as(saved)
                after_save = receipt["metrics"]["afterSave"] = page.evaluate("CFDStudio.lazyMetrics")
                check("HTML export does not load any additional source core, cut or layer",
                      all(before_save[key] == after_save[key] for key in ("coreLoads", "sectionLoads", "layerLoads")))
                loaded = report.load_report_document(saved)
                compare("tablet-exported HTML preserves both complete originals and exact derived scientific data",
                        composed["cases"], loaded["cases"])
                check("saved active composition retains its field, scales, source-attributed pick and note",
                      loaded["views"][0]["caseId"] == composed["cases"][2]["id"]
                      and loaded["views"][0]["state"]["sectionIndex"] == 6
                      and loaded["views"][0]["state"]["variable"] == "CpT"
                      and loaded["views"][0]["state"]["colorRanges"]["surfaceCp"] == [-1.3, .6]
                      and len(loaded["notes"]) == 1
                      and loaded["notes"][0]["state"]["selection"]["sourceCaseId"] == composed["cases"][1]["id"])
                saved_slots = slots_from(saved)
                check("re-export keeps all source planes and layers while storing only a compact derived recipe",
                      saved_slots["cfd-project-data"]["version"] == 2
                      and saved_slots["cfd-case-data-2"]["schema"] == "cfd-review-composition"
                      and len([s for s in saved_slots if s.startswith("cfd-section-data-")]) == 28
                      and len([s for s in saved_slots if s.startswith("cfd-layer-data-")]) == 2)
                page.close()
                page = open_page(saved, "reopened tablet composition")
                check("tablet reopen restores active composition and attributed readout without rebuilding all planes", page.evaluate("""() => {
                  const s=CFDStudio.project.views[0].state,v=CFDStudio.viewers[0],m=CFDStudio.lazyMetrics;
                  return v.meta.comparison&&v.sectionIndex===6&&v.variable==='CpT'&&v.lastPick?.sourceSide==='B'
                  &&v.el('pick-metric')&&JSON.stringify(v.colorRanges)===JSON.stringify(s.colorRanges)
                  &&m.sectionLoads===2&&m.layerLoads===0&&m.residentSections===3;}"""))
                compare("reopened composition retains complete note state", loaded["notes"], page.evaluate("CFDStudio.project.notes"))
                page.screenshot(path=str(out / "tablet-composition-reopened.png"))
                page.close()

                page = open_page(files["originals"], "originals before touch compose")
                before_stitch = page.evaluate("CFDStudio.lazyMetrics")
                page.locator('[data-action="toggle-sidebar"]').tap()
                page.locator('[data-control="stitch-a"]').select_option(originals["cases"][0]["id"])
                page.locator('[data-control="stitch-b"]').select_option(originals["cases"][1]["id"])
                page.locator('[data-action="stitch-half"]').tap()
                page.wait_for_function("() => CFDStudio.viewers.length===1&&!!CFDStudio.viewers[0].meta.comparison")
                page.evaluate("CFDStudio.viewers[0].ready")
                after_stitch = receipt["metrics"]["afterTouchCompose"] = page.evaluate("CFDStudio.lazyMetrics")
                check("touch compose button creates one shared scene without loading all source cuts",
                      page.evaluate("CFDStudio.project.cases.length") == 3
                      and after_stitch["sectionLoads"] - before_stitch["sectionLoads"] <= 2
                      and after_stitch["sectionLoads"] < 28 and after_stitch["layerLoads"] == 0)
                compare("button composition exposes the same current real-X scientific plane as Python",
                        composed["cases"][2]["data"]["sections"][0],
                        page.evaluate("CFDStudio.viewers[0]._currentPayload.payload"), reflected=True)
                page.close()

                page = open_page(files["legacy"], "legacy full-derived tablet")
                check("legacy noncanonical full-derived composition retains one attributed canvas", page.evaluate("""() => {
                  const v=CFDStudio.viewers[0];return v.meta.sourceKey==='synthetic-legacy-full-derived-source'
                  &&v.meta.comparison&&v.meshes.some(m=>m.userData.sourceSide==='A')
                  &&v.meshes.some(m=>m.userData.sourceSide==='B');}"""))
                page.evaluate("CFDStudio.viewers[0].setSection(7)")
                compare("legacy full-derived selection uses its complete saved source-valued plane",
                        legacy["cases"][2]["data"]["sections"][7],
                        page.evaluate("CFDStudio.viewers[0]._currentPayload.payload"), reflected=True)
                page.evaluate("""async () => {const v=CFDStudio.viewers[0],s=v.getState();s.selection=null;
                  s.bodyMode='hidden';s.sectionVisible=true;s.hideNearOne=false;s.sectionOpacity=1;
                  await v.setState(s);await v.setField('Cp');v.controls.enableDamping=false;v._fit('front');}""")
                compare("legacy full-derived Cp uses its saved scalar array",
                        legacy["cases"][2]["data"]["sections"][7]["cp"],
                        page.evaluate("CFDStudio.viewers[0].sectionMesh.userData.values"))
                pick(page, "section", "B", legacy["cases"][:2], "Cp")
                with page.expect_download() as download:
                    page.evaluate("CFDStudio.downloadHTML()")
                legacy_saved = out / "tablet-legacy-full-derived-saved.html"
                download.value.save_as(legacy_saved)
                compare("legacy full-derived browser export remains lossless and readable in Python",
                        legacy["cases"], report.load_report_document(legacy_saved)["cases"])
                page.screenshot(path=str(out / "tablet-legacy-full-derived.png"))
                page.close()
                check("no uncaught JavaScript errors", not receipt["errors"])
                check("no online requests", not receipt["network"])
                receipt["passed"] = True
            finally:
                context.close()
                browser.close()
    except Exception:
        receipt["exception"] = traceback.format_exc()
    path = out / "mobile-composition-checks.json"
    path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"passed": receipt["passed"], "checks": len(receipt["checks"]), "receipt": str(path)}, ensure_ascii=True))
    if not receipt["passed"]:
        print(receipt.get("exception", ""))
    return 0 if receipt["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
