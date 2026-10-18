"""Offline single-canvas half-model checks using explicit synthetic cases only.

No native STAR process or network request is needed. Requires optional Playwright.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import traceback

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from cfd_review.comparison import compose_half_comparison
from cfd_review.schema import validate_project


PICK_SIDE = """side=>{
 const v=CFDStudio.viewers[0],r=v.renderer.domElement.getBoundingClientRect();
 v.camera.updateMatrixWorld(true);v.scene.updateMatrixWorld(true);
 const candidates=[...v.meshes,...v.sectionGroup.children,...v.layerMeshes].filter(m=>m.visible);
 for(const mesh of candidates){const p=mesh.geometry.getAttribute('position'),ix=mesh.geometry.index;
  for(let j=0;j<ix.count;j+=3){const ids=[ix.getX(j),ix.getX(j+1),ix.getX(j+2)],
   center=ids.reduce((sum,i)=>sum.add(new THREE.Vector3().fromBufferAttribute(p,i)),new THREE.Vector3()).multiplyScalar(1/3);
   const screen=mesh.localToWorld(center).project(v.camera);if(Math.abs(screen.x)>.95||Math.abs(screen.y)>.95||screen.z>1)continue;
   const event={clientX:r.left+(screen.x+1)*r.width/2,clientY:r.top+(1-screen.y)*r.height/2},pick=v._pick(event,false);
   if(pick?.sourceSide===side){v._showPick(pick);return {pick,event};}
  }
 }throw Error('No visible native triangle for side '+side);
}"""

CREDIT_STATUS = """view=>{
 const hs=document.querySelectorAll('#cfd-creator-credit'),h=hs[0],s=h&&getComputedStyle(h),
  row=CFDStudio.viewers[view].el('frame-status').parentElement,r=h?.getBoundingClientRect(),
  b=row.getBoundingClientRect(),text=row.querySelector('strong').getBoundingClientRect();
 return hs.length===1&&h.getAttribute('aria-label')==='Designed by Symn'&&h.shadowRoot===null&&
  h.parentElement===row&&s.position==='absolute'&&s.display==='block'&&s.visibility==='visible'&&
  s.opacity==='1'&&s.fontSize==='11px'&&r.width>75&&r.height>15&&r.top>=b.top&&r.bottom<=b.bottom&&
  r.right<=b.right&&text.right<=r.left-4&&!document.getElementById('cfd-creator-credit-space')&&
  getComputedStyle(document.getElementById('app')).paddingBottom!=='34px';
}"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--html", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--no-screenshots", action="store_true", help="Run functional checks without visual captures")
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    receipt = {"fixture": "Synthetic DEMO only; not CFD or native STAR validation", "checks": {}, "errors": [], "network": []}

    def check(name, passed):
        receipt["checks"][name] = bool(passed)
        if not passed:
            raise AssertionError(name)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, args=["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"])
        context = browser.new_context(viewport={"width": 1440, "height": 1100}, offline=True, accept_downloads=True)
        def open_page(path):
            page = context.new_page()
            page.on("pageerror", lambda error: receipt["errors"].append(str(error)))
            page.on("request", lambda request: receipt["network"].append(request.url) if request.url.startswith(("http:", "https:")) else None)
            page.goto(path.resolve().as_uri())
            page.wait_for_function("()=>window.CFDStudio&&CFDStudio.viewers.length>0")
            page.evaluate("CFDStudio.ready")
            page.wait_for_function("()=>CFDStudio.viewers.every(v=>v.renderer)")
            return page
        try:
            page = open_page(args.html)
            check("one creator credit shares the primary status row without extra bottom space", page.evaluate(CREDIT_STATUS, 0))
            page.add_style_tag(content="#cfd-creator-credit{display:none!important;opacity:0!important;visibility:hidden!important;color:transparent!important;font-size:0!important;transform:scale(0)!important}#cfd-creator-credit span{font-family:monospace!important;color:transparent!important;font-size:0!important}")
            check("template CSS cannot accidentally hide or restyle the creator credit", page.evaluate(CREDIT_STATUS, 0))
            page.locator('.studio-view[data-view="1"] [data-action="top"]').click()
            active_credit = page.evaluate(CREDIT_STATUS, 1)
            page.locator('.studio-view[data-view="1"] [data-action="fullscreen"]').click()
            page.wait_for_function("()=>document.fullscreenElement&&document.fullscreenElement.contains(document.getElementById('cfd-creator-credit'))")
            full_credit = page.evaluate(CREDIT_STATUS, 1)
            page.evaluate("document.exitFullscreen()")
            page.wait_for_function("()=>!document.fullscreenElement&&document.getElementById('cfd-creator-credit').parentElement===CFDStudio.viewers[0].el('frame-status').parentElement")
            check("one creator credit follows active and fullscreen views and returns to the primary row", active_credit and full_credit and page.evaluate(CREDIT_STATUS, 0))
            originals = page.evaluate("CFDStudio.project.cases.filter(c=>!c.data.meta.comparison)")
            check("two original synthetic half sources", len(originals) == 2 and all(c["data"]["meta"]["isDemo"] and c["data"]["meta"]["halfCar"] for c in originals))
            page.evaluate("window.__splitOriginals=JSON.stringify(CFDStudio.project.cases.map(c=>c.data))")
            expected = compose_half_comparison(*originals)
            composed = page.evaluate("()=>CFDStudio.composeHalfComparison(...CFDStudio.project.cases)")
            check("Python and browser composition are equivalent", composed == expected)
            page.locator('[data-control="stitch-a"]').select_option(originals[0]["id"])
            page.locator('[data-control="stitch-b"]').select_option(originals[1]["id"])
            page.locator('[data-action="stitch-half"]').click()
            page.wait_for_function("()=>CFDStudio.viewers.length===1&&CFDStudio.viewers[0].meta.comparison")
            page.evaluate("CFDStudio.viewers[0].ready")
            check("one canvas and one camera contain two independent halves", page.evaluate(CREDIT_STATUS, 0) and page.evaluate("""()=>{
             const v=CFDStudio.viewers[0];return document.querySelectorAll('.fv-canvas canvas').length===1&&
              !v.mirror&&v.meshes.length===v.data.parts.length&&v.meshes.some(m=>m.userData.sourceSide==='A')&&v.meshes.some(m=>m.userData.sourceSide==='B');
            }"""))
            check("opposite Y geometry without per-case full-model mirroring", page.evaluate("""()=>{
             const v=CFDStudio.viewers[0];return v.meshes.every(m=>{const y=m.geometry.getAttribute('position');for(let i=0;i<y.count;i++)if(m.userData.sourceSide==='A'?y.getY(i)>1e-6:y.getY(i)<-1e-6)return false;return !m.userData.mirrored;});
            }"""))
            check("real common X planes only, originals retain unequal grids", page.evaluate("""()=>{
             const [a,b]=CFDStudio.project.cases,v=CFDStudio.viewers[0];return a.data.sections.length!==b.data.sections.length&&v.sections.length>1&&v.sections.every(c=>c.comparisonRanges.every((r,i)=>r.sourceX===[a,b][i].data.sections[r.sourceSectionIndex].x));
            }"""))
            before = page.evaluate("CFDStudio.viewers[0].getState().camera")
            rect = page.locator(".fv-canvas canvas").bounding_box()
            page.mouse.move(rect["x"] + rect["width"] * .55, rect["y"] + rect["height"] * .5)
            page.mouse.down()
            page.mouse.move(rect["x"] + rect["width"] * .55 + 70, rect["y"] + rect["height"] * .5 + 25, steps=10)
            page.mouse.up()
            page.wait_for_timeout(300)
            check("native mouse drag rotates the shared camera", before != page.evaluate("CFDStudio.viewers[0].getState().camera"))
            page.evaluate("""()=>{const v=CFDStudio.viewers[0];v.controls.enableDamping=false;v.sectionVisible=false;v.sectionGroup.visible=false;v.el('section-visible').checked=false;for(const l of v.layers)v.setLayerSettings(l.id,{visible:false});v._fit('top');}""")
            picks = [page.evaluate(PICK_SIDE, side) for side in ("A", "B")]
            check("surface picks identify both originals and inverse Y source coordinates", all(p["pick"]["kind"] == "surface" and p["pick"]["sourceCaseId"] == originals[i]["id"] and abs(p["pick"]["sourcePoint"][1] - p["pick"]["displayPoint"][1] * p["pick"]["sourceYSign"]) < 1e-8 for i, p in enumerate(picks)))
            page.locator('[data-fv="surface-range-min"]').fill("-1.5")
            page.locator('[data-fv="surface-range-max"]').fill("0.5")
            page.locator('[data-action="apply-surface-range"]').click()
            repicks = [page.evaluate("e=>CFDStudio.viewers[0]._pick(e,false)", p["event"]) for p in picks]
            check("shared manual color limits retain both raw point readings", all(abs(a["pick"]["value"] - b["value"]) < 1e-9 for a, b in zip(picks, repicks)))
            check("original source arrays stay immutable", page.evaluate("window.__splitOriginals===JSON.stringify(CFDStudio.project.cases.slice(0,2).map(c=>c.data))"))
            if not args.no_screenshots:
                page.screenshot(path=str(out / "single-canvas-halves.png"), full_page=True)
            page.evaluate("""async()=>{const v=CFDStudio.viewers[0];v.bodyMode='hidden';v._updateBody();v.sectionVisible=true;v.sectionGroup.visible=true;v.hideNearOne=false;v.sectionOpacity=1;await v.setSection(1);v._fit('front');}""")
            cuts = [page.evaluate(PICK_SIDE, side)["pick"] for side in ("A", "B")]
            check("section picking resolves each native source range", all(p["kind"] == "section" and p["sourceCaseId"] == originals[i]["id"] and "sourceSectionIndex" in p for i, p in enumerate(cuts)))
            page.evaluate("""()=>{const v=CFDStudio.viewers[0];v.sectionVisible=false;v.sectionGroup.visible=false;for(const l of v.layers)v.setLayerSettings(l.id,{visible:true,opacity:1});v._fit('isometric');}""")
            layer_picks = [page.evaluate(PICK_SIDE, side)["pick"] for side in ("A", "B")]
            check("independent 3D layers keep scalar definitions and source picking", all(p["kind"] == "layer" and p["sourceLayerId"] == originals[i]["data"]["layers"][0]["id"] and p["sourceCaseId"] == originals[i]["id"] for i, p in enumerate(layer_picks)))
            saved = page.evaluate("""()=>{const v=CFDStudio.viewers[0];CFDStudio.addNote('Synthetic stitched-source pick',0,v.getState());return CFDStudio.exportProject();}""")
            validate_project(saved)
            page.evaluate("value=>CFDStudio.importProject(value)", saved)
            check("project roundtrip retains composition and source-attributed note", page.evaluate(CREDIT_STATUS, 0) and page.evaluate("""()=>CFDStudio.viewers.length===1&&CFDStudio.project.cases.length===3&&CFDStudio.project.notes[0].state.selection.sourceSide==='B'"""))
            page.evaluate("CFDStudio.restoreNote(CFDStudio.project.notes[0].id)")
            check("note restores original source point and shared range", page.evaluate("""()=>{const v=CFDStudio.viewers[0];return v.lastPick.sourceSide==='B'&&v.lastPick.sourceCaseId===v.meta.comparison.sources[1].caseId&&v.colorRanges.surfaceCp[0]===-1.5;}"""))
            with page.expect_download() as download:
                page.evaluate("()=>{CFDStudio.downloadHTML();}")
            portable = out / "isolated" / "stitched-review.html"
            portable.parent.mkdir(exist_ok=True)
            download.value.save_as(portable)
            other = open_page(portable)
            check("self-contained exported HTML reopens one canvas with attributed notes", other.evaluate("""()=>CFDStudio.viewers.length===1&&document.querySelectorAll('.fv-canvas canvas').length===1&&CFDStudio.project.cases.length===3&&CFDStudio.project.notes[0].state.selection.sourceCaseId===CFDStudio.viewers[0].meta.comparison.sources[1].caseId"""))
            check("exported HTML recreates exactly one creator credit in the existing status row", other.evaluate(CREDIT_STATUS, 0))
            other.close()
            page.evaluate("""async()=>{const original=CFDStudio.project.cases.slice(0,2),a=JSON.parse(JSON.stringify(original[0])),b=JSON.parse(JSON.stringify(original[1]));b.id='disjoint-x';for(const s of b.data.sections){s.x+=100;for(let j=0;j<s.positions.length;j+=3)s.positions[j]+=100;}const d=CFDStudio.composeHalfComparison(a,b);await CFDStudio.importProject({schema:'cfd-review-project',version:1,title:'Synthetic disjoint cuts',cases:[a,b,d],views:[{caseId:d.id,state:null}],links:{camera:true,section:true,field:true,color:true},notes:[]});}""")
            check("no common real X planes keeps surface and layers usable", page.evaluate("""()=>{const v=CFDStudio.viewers[0];return v.meta.comparison.sectionsStatus==='no-common-x'&&v.sections.length===0&&v.meshes.length>0&&v.layers.length===2&&v.el('variable').disabled;}"""))
            page.evaluate("""async()=>{const originals=CFDStudio.project.cases.slice(0,2),a=JSON.parse(JSON.stringify(originals[0])),b=JSON.parse(JSON.stringify(originals[0]));b.id='other-fields';for(const s of a.data.sections)delete s.cpt;for(const s of b.data.sections)delete s.cp;const d=CFDStudio.composeHalfComparison(a,b);await CFDStudio.importProject({schema:'cfd-review-project',version:1,title:'Synthetic differing fields',cases:[a,b,d],views:[{caseId:d.id,state:null}],links:{camera:true,section:true,field:true,color:true},notes:[]});}""")
            check("incompatible cut fields are omitted without invented scalars", page.evaluate("""()=>{const v=CFDStudio.viewers[0];return v.sections.length===0&&v.meta.comparison.sectionsStatus==='no-common-fields'&&v.meshes.length>0;}"""))
            page.evaluate("""async()=>{const originals=CFDStudio.project.cases.slice(0,2),a=JSON.parse(JSON.stringify(originals[0])),b=JSON.parse(JSON.stringify(originals[1]));a.id='layer-only-a';b.id='layer-only-b';for(const c of [a,b]){c.data.parts=[];c.data.sections=[];}const d=CFDStudio.composeHalfComparison(a,b);await CFDStudio.importProject({schema:'cfd-review-project',version:1,title:'Synthetic native layers',cases:[a,b,d],views:[{caseId:d.id,state:null}],links:{camera:true,section:true,field:true,color:true},notes:[]});}""")
            check("layer-only sources render two attributed groups in one canvas", page.evaluate("""()=>{const v=CFDStudio.viewers[0];return v.parts.length===0&&v.layers.length===2&&document.querySelectorAll('.fv-canvas canvas').length===1&&v.layers.some(l=>l.mesh.userData.sourceSide==='A')&&v.layers.some(l=>l.mesh.userData.sourceSide==='B');}"""))
            check("full or two-sided geometry cannot masquerade as a half model", page.evaluate("""()=>{const [a,b]=CFDStudio.project.cases,full=JSON.parse(JSON.stringify(a)),cross=JSON.parse(JSON.stringify(a));full.data.meta.halfCar=false;full.data.meta.scalarMirror=false;cross.data.layers[0].positions[1]=-10;let n=0;for(const c of [full,cross])try{CFDStudio.composeHalfComparison(c,b);}catch(_){n++;}return n===2;}"""))
            check("no external requests", not receipt["network"])
            check("no uncaught page errors", not receipt["errors"])
            receipt["passed"] = True
        except Exception:
            receipt["passed"] = False
            receipt["exception"] = traceback.format_exc()
        finally:
            context.close()
            browser.close()
    path = out / "split-comparison-checks.json"
    path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"passed": receipt["passed"], "checks": len(receipt["checks"]), "receipt": str(path)}, ensure_ascii=False))
    if not receipt["passed"]:
        print(receipt.get("exception", ""))
    return 0 if receipt["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
