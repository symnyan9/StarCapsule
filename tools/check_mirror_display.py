"""Check full-car display mirroring with synthetic data in an offline browser.

Requires the optional Playwright development dependency. No STAR process,
real simulation data, screenshots or network access is used.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import traceback

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from cfd_review.demo import make_demo_project
from cfd_review.report import build_report
from cfd_review.schema import validate_project


PICK_MIRROR = """()=>{
 const v=CFDStudio.viewers[0],r=v.renderer.domElement.getBoundingClientRect();
 v.camera.updateMatrixWorld(true);v.scene.updateMatrixWorld(true);
 for(const mesh of v.meshes.filter(m=>m.visible&&m.userData.mirrored)){
  const p=mesh.geometry.getAttribute('position'),ix=mesh.geometry.index;
  for(let j=0;j<ix.count;j+=3){const ids=[ix.getX(j),ix.getX(j+1),ix.getX(j+2)],
   center=ids.reduce((s,i)=>s.add(new THREE.Vector3().fromBufferAttribute(p,i)),new THREE.Vector3()).multiplyScalar(1/3);
   const screen=mesh.localToWorld(center).project(v.camera);
   if(Math.abs(screen.x)>.95||Math.abs(screen.y)>.95||screen.z>1)continue;
   const event={clientX:r.left+(screen.x+1)*r.width/2,clientY:r.top+(1-screen.y)*r.height/2},pick=v._pick(event,true);
   if(pick?.mirrored&&pick.displayPoint[1]<-1e-4)return {pick,event};
  }
 }throw Error('No visible mirrored source triangle');
}"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--template", type=Path)
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    project = make_demo_project()
    # Source A explicitly starts without scalar mirroring, as a SIM whose export
    # omitted the full-car display flag would. Source B checks legacy defaults.
    project["cases"][0]["data"]["meta"]["scalarMirror"] = False
    report = build_report(project, out / "synthetic-mirror.html", overwrite=True, template=args.template)
    receipt = {"fixture": "Synthetic mathematical DEMO only; no CFD or STAR validation",
               "checks": {}, "errors": [], "network": []}

    def check(name, passed):
        receipt["checks"][name] = bool(passed)
        if not passed:
            raise AssertionError(name)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, args=["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"])
        context = browser.new_context(viewport={"width": 1440, "height": 1000}, offline=True, accept_downloads=True)

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
            page = open_page(report)
            check("legacy source metadata supplies independent initial mirror defaults", page.evaluate("()=>!CFDStudio.viewers[0].getState().mirrorDisplay&&CFDStudio.viewers[1].getState().mirrorDisplay"))
            page.evaluate("window.__mirrorOriginal=JSON.stringify(CFDStudio.project.cases.map(c=>c.data));window.__mirrorBase=structuredClone(CFDStudio.project);CFDStudio.setLink('camera',false)")
            toggle = page.locator('.studio-view[data-view="0"] [data-fv="mirror-display"]')
            check("dedicated full-car switch is usable without changing the symmetry declaration", toggle.is_enabled() and not toggle.is_checked())
            toggle.check()
            check("native checkbox adds mirrored surfaces sections and postprocessing layers", page.evaluate("""()=>{const v=CFDStudio.viewers[0];return v.getState().mirrorDisplay&&v.parts.every(p=>p.mirrored?.parent)&&v.layers.every(l=>l.mirrored?.parent)&&v.sectionGroup.children.some(m=>m.userData.mirrored);} """))
            check("mirror meshes share geometry material and source scalar arrays", page.evaluate("""()=>{const v=CFDStudio.viewers[0],pairs=[...v.parts,...v.layers];return pairs.every(p=>p.mirrored.geometry===p.mesh.geometry&&p.mirrored.material===p.mesh.material&&p.mirrored.userData.values===p.mesh.userData.values)&&v.sectionGroup.children.find(m=>m.userData.mirrored).geometry===v.sectionMesh.geometry;}"""))
            check("full-car bounds include the opposite Y half", page.evaluate("()=>{const v=CFDStudio.viewers[0],b=v._visibleBounds();return b.min.y<-.5&&b.max.y>.5&&v.diagonal>0;}"))
            page.evaluate("""async()=>{const v=CFDStudio.viewers[0];await v.setState({...v.getState(),bodyMode:'cp',sectionVisible:false,layerSettings:Object.fromEntries(v.layers.map(l=>[l.id,{visible:false,opacity:l.opacity,colorRange:l.colorRange}]))});v.controls.enableDamping=false;v._fit('top');}""")
            selected = page.evaluate(PICK_MIRROR)
            check("mirrored picking reports unchanged scalar and inverse source Y coordinate", selected["pick"]["mirrored"] and abs(selected["pick"]["sourcePoint"][1] + selected["pick"]["displayPoint"][1]) < 1e-8 and abs(selected["pick"]["sourcePoint"][0] - selected["pick"]["displayPoint"][0]) < 1e-8 and isinstance(selected["pick"]["value"], (float, int)))
            page.evaluate("""()=>{const v=CFDStudio.viewers[0];v.setColorRange('surface',-.05,.05);}""")
            repick = page.evaluate("e=>CFDStudio.viewers[0]._pick(e,true)", selected["event"])
            check("color saturation preserves the mirrored raw reading", abs(repick["value"] - selected["pick"]["value"]) < 1e-9)
            page.evaluate("CFDStudio.viewers[0].setMirrorDisplay(false,{fit:false})")
            check("disabling mirror clears mirrored selection and removes its hit target", page.evaluate("e=>{const v=CFDStudio.viewers[0],pick=v._pick(e,false);return !v.getState().mirrorDisplay&&!v.lastPick&&!pick&&!v.scene.children.some(g=>g.children?.some(m=>m.userData.mirrored&&m.visible));}", selected["event"]))
            page.evaluate("""async()=>{const v=CFDStudio.viewers[0];await v.setMirrorDisplay(true);await v.setState({...v.getState(),sectionVisible:true,variable:'CpT',sectionOpacity:.4,hideNearOne:true,cptTransparentAbove:.98,layerSettings:Object.fromEntries(v.layers.map(l=>[l.id,{visible:true,opacity:.3,colorRange:[.1,.9]}]))});await v.setSection(4);}""")
            check("new cuts and CpT alpha filtering share the mirrored color buffer", page.evaluate("""()=>{const v=CFDStudio.viewers[0],m=v.sectionGroup.children.find(m=>m.userData.mirrored),colors=v.sectionMesh.geometry.getAttribute('color');return m?.geometry===v.sectionMesh.geometry&&m.material===v.sectionMesh.material&&colors.itemSize===4&&v.sections[v.sectionIndex].cpt.every((x,i)=>x<.98||colors.getW(i)===0)&&v.sectionMesh.material.opacity===.4;}"""))
            check("independent layer opacity visibility and limits apply to both halves", page.evaluate("""()=>{const v=CFDStudio.viewers[0],l=v.layers[0];v.setLayerSettings(l.id,{visible:false});const hidden=!l.mesh&&!l.mirrored;v.setLayerSettings(l.id,{visible:true});return hidden&&l.mesh.visible&&l.mirrored.visible&&l.mirrored.material.opacity===.3&&JSON.stringify(l.mesh.geometry.userData.scalarRange)==='[0.1,0.9]';}"""))
            check("part controls hide and restore both halves together", page.evaluate("""()=>{const v=CFDStudio.viewers[0],cb=v.root.querySelector('[data-part]'),p=v.parts.find(p=>p.id===cb.dataset.part);cb.checked=false;cb.dispatchEvent(new Event('change'));const hidden=!p.mesh.visible&&!p.mirrored.visible;cb.checked=true;cb.dispatchEvent(new Event('change'));return hidden&&p.mesh.visible&&p.mirrored.visible;}"""))
            check("repeated toggles have bounded scene and GPU resource counts", page.evaluate("""async()=>{const v=CFDStudio.viewers[0],count=()=>{let n=0;v.scene.traverse(o=>{if(o.isMesh)n++});return n;};v.renderer.render(v.scene,v.camera);const n=count(),g=v.renderer.info.memory.geometries;for(let i=0;i<20;i++){await v.setMirrorDisplay(false,{fit:false});await v.setMirrorDisplay(true,{fit:false});}v.renderer.render(v.scene,v.camera);return count()===n&&v.renderer.info.memory.geometries===g&&new Set(v.meshes).size===v.meshes.length&&new Set(v.layerMeshes).size===v.layerMeshes.length;}"""))
            check("all geometry field and source arrays remain byte-equivalent", page.evaluate("window.__mirrorOriginal===JSON.stringify(CFDStudio.project.cases.map(c=>c.data))"))
            check("state boolean validation rejects truthy strings and numbers atomically", page.evaluate("""async()=>{const v=CFDStudio.viewers[0],old=v.getState();for(const value of [1,'true']){try{await v.setState({...old,mirrorDisplay:value});return false;}catch(e){if(!v.getState().mirrorDisplay)return false;}}return true;}"""))
            check("legacy states without a flag restore the source metadata default", page.evaluate("""async()=>{const v=CFDStudio.viewers[0],s=v.getState();delete s.mirrorDisplay;s.selection=null;await v.setState(s);const a=!v.getState().mirrorDisplay;const b=CFDStudio.viewers[1],t=b.getState();delete t.mirrorDisplay;await b.setMirrorDisplay(false,{fit:false});await b.setState(t);return a&&b.getState().mirrorDisplay;}"""))
            page.evaluate("""async()=>{const v=CFDStudio.viewers[0];await v.setMirrorDisplay(true);CFDStudio.addNote('Synthetic full-car mirror display',0);await v.setMirrorDisplay(false);await CFDStudio.restoreNote(CFDStudio.project.notes[0].id);}""")
            check("annotations restore display mirroring without editing scientific metadata", page.evaluate("()=>CFDStudio.viewers[0].getState().mirrorDisplay&&CFDStudio.project.notes[0].state.mirrorDisplay&&CFDStudio.project.cases[0].data.meta.scalarMirror===false"))
            saved = page.evaluate("CFDStudio.exportProject()")
            validate_project(saved)
            page.evaluate("p=>CFDStudio.importProject(p)", saved)
            check("project save and restore retain independent mirror settings", page.evaluate("()=>CFDStudio.viewers.every(v=>v.getState().mirrorDisplay)&&CFDStudio.project.notes[0].state.mirrorDisplay"))
            with page.expect_download() as download:
                page.evaluate("CFDStudio.downloadHTML()")
            portable = out / "portable-mirror.html"
            download.value.save_as(portable)
            other = open_page(portable)
            check("portable HTML reopens full-car display and notes offline", other.evaluate("()=>CFDStudio.viewers[0].getState().mirrorDisplay&&CFDStudio.viewers[0].meshes.some(m=>m.userData.mirrored)&&CFDStudio.project.notes[0].state.mirrorDisplay"))
            other.close()
            check("same-canvas half comparison keeps both original sources without remirroring", page.evaluate("""async()=>{const p=CFDStudio.exportProject(),d=CFDStudio.composeHalfComparison(p.cases[0],p.cases[1]);p.cases.push(d);p.views=[{caseId:d.id,state:null}];await CFDStudio.importProject(p);const v=CFDStudio.viewers[0];let denied=false;try{await v.setMirrorDisplay(true);}catch(e){denied=true;}return denied&&!v.mirror&&v.el('mirror-display').disabled&&v.meshes.length===v.data.parts.length&&v.meshes.some(m=>m.userData.sourceSide==='A')&&v.meshes.some(m=>m.userData.sourceSide==='B');}"""))
            check("full sources and crossing-Y geometry cannot accidentally gain another half", page.evaluate("""async()=>{for(const kind of ['full','cross']){const p=structuredClone(window.__mirrorBase),c=p.cases[0];p.cases=[c];p.views=[{caseId:c.id,state:null}];p.notes=[];c.data.meta.scalarMirror=false;if(kind==='full')c.data.meta.halfCar=false;else c.data.parts[0].positions[1]=-1;try{await CFDStudio.importProject(p);}catch(e){if(kind==='cross')continue;throw e;}const v=CFDStudio.viewers[0];try{await v.setMirrorDisplay(true);}catch(e){}if(v.getState().mirrorDisplay||v.meshes.some(m=>m.userData.mirrored))return false;}return true;}"""))
            check("explicit half confirmation enables the switch while mirrored notes protect its declaration", page.evaluate("""async()=>{const p=structuredClone(window.__mirrorBase),c=p.cases[0];p.cases=[c];p.views=[{caseId:c.id,state:null}];p.notes=[];c.data.meta.halfCar=false;c.data.meta.scalarMirror=false;await CFDStudio.importProject(p);await CFDStudio.declareHalfCar(c.id,true);await CFDStudio.viewers[0].setMirrorDisplay(true);CFDStudio.addNote('Synthetic mirrored note locks declaration',0);await CFDStudio.viewers[0].setMirrorDisplay(false);let denied=false;try{await CFDStudio.declareHalfCar(c.id,false);}catch(e){denied=true;}return denied&&CFDStudio.project.cases[0].data.meta.halfCar&&CFDStudio.project.notes[0].state.mirrorDisplay;}"""))
            check("reversible unused half confirmation leaves a disabled unchecked mirror switch", page.evaluate("""async()=>{CFDStudio.project.notes=[];const c=CFDStudio.project.cases[0];await CFDStudio.declareHalfCar(c.id,false);const v=CFDStudio.viewers[0];return !v.getState().mirrorDisplay&&v.el('mirror-display').disabled&&!v.el('mirror-display').checked&&!c.data.meta.halfCar;}"""))
            check("no uncaught browser errors or external requests", not receipt["errors"] and not receipt["network"])
            receipt["passed"] = True
        except Exception:
            receipt["passed"] = False
            receipt["failure"] = traceback.format_exc()
        finally:
            context.close()
            browser.close()
    path = out / "mirror-display-checks.json"
    path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"passed": receipt["passed"], "checks": len(receipt["checks"]), "receipt": str(path)}, ensure_ascii=False))
    if not receipt["passed"]:
        print(receipt["failure"])
    return 0 if receipt["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
