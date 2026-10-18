"""Exercise the portable Studio in an offline browser using synthetic data only.

Requires the optional Playwright development dependency. No STAR process is started.
Run against a fresh ``python -m cfd_review demo --output ...`` HTML file.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import traceback

from playwright.sync_api import sync_playwright


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--html", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--browser-executable", type=Path)
    args = parser.parse_args()
    report = args.html.resolve(strict=True)
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    receipt = {"fixture": "Explicit synthetic DEMO only; not real-SIM validation",
               "html": str(report), "checks": {}, "errors": [], "network": []}

    def record(label, passed):
        receipt["checks"][label] = bool(passed)
        if not passed:
            raise AssertionError(label)

    def open_report(context, path):
        page = context.new_page()
        page.on("pageerror", lambda error: receipt["errors"].append(str(error)))
        page.on("request", lambda req: receipt["network"].append(req.url)
                if req.url.startswith(("http:", "https:")) else None)
        page.goto(path.as_uri())
        page.wait_for_function("() => window.CFDStudio && window.CFDStudio.viewers.length === 2")
        page.evaluate("CFDStudio.ready")
        page.wait_for_function("() => CFDStudio.viewers.every(v => v.sectionMesh)")
        return page

    with sync_playwright() as playwright:
        launch = {"headless": True, "args": ["--use-gl=angle", "--use-angle=swiftshader",
                                             "--enable-unsafe-swiftshader"]}
        if args.browser_executable:
            launch["executable_path"] = str(args.browser_executable.resolve(strict=True))
        browser = playwright.chromium.launch(**launch)
        context = browser.new_context(viewport={"width": 1440, "height": 1100},
                                      offline=True, accept_downloads=True)
        page = None
        try:
            page = open_report(context, report)
            # Remove timing-dependent inertia from the fixture, retaining real mouse events.
            page.evaluate("CFDStudio.viewers.forEach(v=>v.controls.enableDamping=false)")
            record("two explicitly synthetic cases and isosurface layers", page.evaluate("""() => {
              const p=CFDStudio.project;
              return p.cases.length===2 && p.cases.every(c=>c.data.meta.isDemo===true&&c.data.layers.length>0)
                && p.cases[0].data.sections.length!==p.cases[1].data.sections.length;
            }"""))
            page.evaluate("window.__qaRaw=JSON.stringify(CFDStudio.project.cases.map(c=>c.data))")

            # A real mouse drag, including OrbitControls damping, must reach the other view.
            page.evaluate("CFDStudio.setLink('camera',true)")
            before = page.evaluate("CFDStudio.viewers.map(v=>v.getState().camera)")
            bounds = page.evaluate("""() => {
              const r=CFDStudio.viewers[0].renderer.domElement.getBoundingClientRect();
              return {x:r.left+r.width*.54,y:r.top+r.height*.5};
            }""")
            page.mouse.move(bounds["x"], bounds["y"])
            page.mouse.down()
            page.mouse.move(bounds["x"] + 95, bounds["y"] + 38, steps=12)
            page.mouse.up()
            page.wait_for_timeout(800)
            after = page.evaluate("CFDStudio.viewers.map(v=>v.getState().camera)")
            receipt["mouse_camera_before"] = before
            receipt["mouse_camera_after"] = after
            record("native mouse drag changes camera", before[0] != after[0])
            record("native mouse camera linking", page.evaluate("""() => {
              const a=CFDStudio.viewers[0].getState().camera,b=CFDStudio.viewers[1].getState().camera;
              return [...a.position,...a.target].every((x,i)=>Math.abs(x-[...b.position,...b.target][i])<1e-5);
            }"""))
            page.evaluate("CFDStudio.setLink('camera',false)")
            fixed = page.evaluate("CFDStudio.viewers[1].getState().camera")
            page.mouse.move(bounds["x"], bounds["y"])
            page.mouse.down()
            page.mouse.move(bounds["x"] - 80, bounds["y"] + 30, steps=10)
            page.mouse.up()
            page.wait_for_timeout(800)
            record("unlink keeps the other camera independent", page.evaluate("""fixed=>{
              const actual=CFDStudio.viewers[1].getState().camera;
              return [...fixed.position,...fixed.target].every((x,i)=>Math.abs(x-[...actual.position,...actual.target][i])<1e-8);
            }""", fixed))
            zoom_before = page.evaluate("CFDStudio.viewers[0].camera.position.distanceTo(CFDStudio.viewers[0].controls.target)")
            page.locator('.studio-view[data-view="0"] [data-action="zoom-in"]').click()
            page.wait_for_timeout(300)
            record("native zoom button decreases camera distance", page.evaluate("CFDStudio.viewers[0].camera.position.distanceTo(CFDStudio.viewers[0].controls.target)") < zoom_before)

            # Native form controls dispatch the same events used in ordinary operation.
            page.evaluate("CFDStudio.setLink('section',true)")
            selected = page.evaluate("""() => {
              const a=CFDStudio.viewers[0],b=CFDStudio.viewers[1];
              for(let i=1;i<a.sections.length-1;i++) {
                const x=a.sections[i].x,j=b.sections.reduce((best,s,k)=>Math.abs(s.x-x)<Math.abs(b.sections[best].x-x)?k:best,0);
                if(i!==j) return {index:i,x,other:j};
              }
              throw Error('Fixture must have unequal indices for at least one shared spatial location');
            }""")
            view0 = page.locator('.studio-view[data-view="0"]')
            view0.locator('[data-fv="x-input"]').fill(str(selected["x"] * 1000))
            view0.locator('[data-action="apply-x"]').click()
            page.wait_for_timeout(250)
            record("slice linking uses nearest common X, not frame index", page.evaluate("""expected => {
              const [a,b]=CFDStudio.viewers;
              return a.sectionIndex===expected.index && b.sectionIndex===expected.other && a.sectionIndex!==b.sectionIndex;
            }""", selected))
            page.evaluate("CFDStudio.setLink('field',true);CFDStudio.setLink('color',true)")
            view0.locator('[data-fv="variable"]').select_option("Cp")
            page.wait_for_timeout(120)
            record("variable selector links Cp", page.evaluate("CFDStudio.viewers.every(v=>v.variable==='Cp')"))
            view0.locator('[data-fv="section-range-min"]').fill("-0.25")
            view0.locator('[data-fv="section-range-max"]').fill("0.75")
            view0.locator('[data-action="apply-section-range"]').click()
            page.wait_for_timeout(120)
            record("manual Cp range synchronizes", page.evaluate("CFDStudio.viewers.every(v=>JSON.stringify(v.colorRanges.section.Cp)==='[-0.25,0.75]')"))
            view0.locator('[data-fv="variable"]').select_option("CpT")
            page.wait_for_timeout(120)
            view0.locator('[data-fv="section-range-min"]').fill("-0.1")
            view0.locator('[data-fv="section-range-max"]').fill("0.8")
            view0.locator('[data-action="apply-section-range"]').click()
            page.wait_for_timeout(120)
            record("Cp and CpT ranges have independent memories", page.evaluate("""CFDStudio.viewers.every(v=>
              JSON.stringify(v.colorRanges.section.Cp)==='[-0.25,0.75]'&&JSON.stringify(v.colorRanges.section.CpT)==='[-0.1,0.8]')"""))
            record("actual section colors use the linked legend range", page.evaluate("""CFDStudio.viewers.every(v=>
              JSON.stringify(v.sectionMesh.geometry.userData.scalarRange)==='[-0.1,0.8]')"""))
            previous = page.evaluate("JSON.stringify(CFDStudio.viewers[0].colorRanges)")
            view0.locator('[data-fv="section-range-min"]').fill("1")
            view0.locator('[data-fv="section-range-max"]').fill("0")
            view0.locator('[data-action="apply-section-range"]').click()
            record("invalid UI color range preserves last valid range", previous == page.evaluate("JSON.stringify(CFDStudio.viewers[0].colorRanges)"))

            receipt["checks"].update(page.evaluate("""async () => {
              const S=CFDStudio,a=S.viewers[0],b=S.viewers[1],checks={};
              const test=(n,ok)=>{checks[n]=!!ok;if(!ok)throw Error(n)},same=(x,y)=>JSON.stringify(x)===JSON.stringify(y);
              window.__qaChecks=checks;
              S.setLink('section',false);const otherIndex=b.sectionIndex;
              await a.setSection(a.sections.length-1);test('unlink keeps other slice independent',otherIndex===b.sectionIndex);
              const seen=[],original=a.setSection.bind(a);a.setSection=async i=>{seen.push(i);return original(i)};
              a.direction=1;a.play();await new Promise(r=>setTimeout(r,420));a.pause();
              test('sweep reverses at real final plane',seen.length>0&&seen[0]===a.sections.length-2);
              const stopped=a.sectionIndex;await new Promise(r=>setTimeout(r,250));test('pause stops sweep',a.sectionIndex===stopped);a.setSection=original;
              const id=a.data.layers[0].id,before=b.getState().layerSettings;
              const toggle=a.root.querySelector('[data-layer]');toggle.checked=false;toggle.dispatchEvent(new Event('change',{bubbles:true}));
              test('isosurface hides independently',a.getState().layerSettings[id].visible===false&&!a.layers[0].mesh.visible&&same(before,b.getState().layerSettings));
              toggle.checked=true;toggle.dispatchEvent(new Event('change',{bubbles:true}));
              const opacity=a.root.querySelector('[data-layer-opacity]');opacity.value='0.35';opacity.dispatchEvent(new Event('input',{bubbles:true}));
              test('isosurface opacity remains independent',Math.abs(a.getState().layerSettings[id].opacity-.35)<1e-6&&Math.abs(a.layers[0].mesh.material.opacity-.35)<1e-6&&same(before,b.getState().layerSettings));
              a.root.querySelector('[data-layer-min]').value='.15';a.root.querySelector('[data-layer-max]').value='.85';a.root.querySelector('[data-layer-apply]').click();
              test('isosurface color range uses an independent actual buffer',same(a.getState().layerSettings[id].colorRange,[.15,.85])&&same(a.layers[0].mesh.geometry.userData.scalarRange,[.15,.85])&&same(before,b.getState().layerSettings));
              const part=a.root.querySelector('[data-part]'),partId=part.dataset.part,bParts=b.getState().partSelection;
              part.checked=false;part.dispatchEvent(new Event('change',{bubbles:true}));test('part visibility is independent',!a.getState().partSelection.includes(partId)&&same(bParts,b.getState().partSelection));
              part.checked=true;part.dispatchEvent(new Event('change',{bubbles:true}));
              a.sectionVisible=false;a.sectionGroup.visible=false;for(const mesh of a.layerMeshes||[])mesh.visible=false;
              a._fit('isometric');a.camera.updateMatrixWorld(true);a.scene.updateMatrixWorld(true);
              const rect=a.renderer.domElement.getBoundingClientRect();let picked=null,event=null;
              for(let y=.15;y<.9&&!picked;y+=.05)for(let x=.15;x<.9&&!picked;x+=.05){const e={clientX:rect.left+rect.width*x,clientY:rect.top+rect.height*y};const p=a._pick(e,false);if(p){picked=p;event=e}}
              test('native triangle raw-value pick succeeds',!!picked&&Number.isFinite(picked.value));
              a.setColorRange('surface',-.001,.001);test('color saturation does not alter same-point raw pick',same(picked,a._pick(event,false)));
              test('geometry and scalar source arrays stay unchanged',window.__qaRaw===JSON.stringify(S.project.cases.map(c=>c.data)));
              await a.setState({...a.getState(),sectionVisible:true});
              return checks;
            }"""))

            # Right click opens an actual anchored annotation editor.
            bounds = page.evaluate("""() => {const r=CFDStudio.viewers[0].renderer.domElement.getBoundingClientRect();return{x:r.left+r.width*.55,y:r.top+r.height*.55}}""")
            page.mouse.click(bounds["x"], bounds["y"], button="right")
            page.locator('[data-control="note-text"]').fill("合成演示批注：检查相同截面的压力差异。")
            page.locator('[data-action="save-note"]').click()
            page.evaluate("window.__qaNote=CFDStudio.exportProject().notes.at(-1)")
            record("right-click annotation includes complete view state", page.evaluate("""() => {
              const n=window.__qaNote;return !!n&&!!n.state.camera&&!!n.state.colorRanges&&!!n.state.layerSettings&&n.text.includes('合成演示');
            }"""))
            page.evaluate("""async () => {
              const v=CFDStudio.viewers[0];v._fit('top');v.setColorRange('surface',-5,5);await v.setSection(0);
              await CFDStudio.restoreNote(window.__qaNote.id);
            }""")
            record("annotation restores camera, frame, field, ranges and layers", page.evaluate("""() => {
              const a=CFDStudio.viewers[0].getState(),b=window.__qaNote.state;
              return ['sectionIndex','variable','colorRanges','layerSettings','partSelection','sectionOpacity'].every(k=>JSON.stringify(a[k])===JSON.stringify(b[k]))
                && [...a.camera.position,...a.camera.target].every((x,i)=>Math.abs(x-[...b.camera.position,...b.camera.target][i])<1e-8);
            }"""))

            title = 'Offline comparison <审阅> & "DEMO"'
            page.locator('[data-control="project-title"]').fill(title)
            page.locator('[data-control="project-title"]').dispatch_event("change")
            renamed = "合成方案 A — edited"
            view0.locator('[data-control="case-name"]').fill(renamed)
            view0.locator('[data-control="case-name"]').dispatch_event("change")
            record("title and case name are editable", page.evaluate("""expected=>{
              const p=CFDStudio.exportProject();return p.title===expected.title&&p.cases.find(c=>c.id===p.views[0].caseId).name===expected.name;
            }""", {"title": title, "name": renamed}))
            extra = page.evaluate("""() => {
              const c=structuredClone(CFDStudio.project.cases[0]);c.id+='-imported';c.name='Imported synthetic case';
              c.data.meta.sourceKey+='-imported';return c;
            }""")
            case_path = out / "synthetic-additional-case.json"
            case_path.write_text(json.dumps(extra, ensure_ascii=False), encoding="utf-8")
            page.locator('input[data-control="import-file"]').set_input_files(str(case_path))
            page.wait_for_function("() => CFDStudio.project.cases.length===3")
            record("native file import adds another independent case", page.evaluate("CFDStudio.project.cases.at(-1).name==='Imported synthetic case'"))

            with page.expect_download() as download_info:
                page.locator('[data-action="export-project"]').click()
            project_path = out / "roundtrip-project.json"
            download_info.value.save_as(str(project_path))
            expected = json.loads(project_path.read_text(encoding="utf-8"))
            page.locator('input[data-control="import-file"]').set_input_files(str(project_path))
            page.wait_for_timeout(500)
            record("downloaded project JSON restores notes and all cases", page.evaluate("""expected => {
              const p=CFDStudio.exportProject();return p.title===expected.title&&p.cases.length===expected.cases.length
                && JSON.stringify(p.notes)===JSON.stringify(expected.notes)
                && p.views.every((v,i)=>JSON.stringify(v.state.colorRanges)===JSON.stringify(expected.views[i].state.colorRanges));
            }""", expected))

            record("optional missing fields remain missing and unavailable", page.evaluate("""async () => {
              const c=structuredClone(CFDStudio.project.cases[0]);c.id+='-cp-only';c.name='Cp-only synthetic case';c.data.meta.sourceKey+='-cp-only';
              delete c.data.parts[0].cp;for(const section of c.data.sections)delete section.cpt;
              await CFDStudio.importCase(c);const v=CFDStudio.viewers[1],o=v.el('variable').querySelector('option[value="CpT"]');
              const saved=CFDStudio.exportProject().cases.find(item=>item.id===c.id);
              return v.variable==='Cp'&&v.availableFields.length===1&&(!o||o.disabled)
                &&!v.parts[0].hasCp&&!('cp' in saved.data.parts[0])&&saved.data.sections.every(s=>!('cpt' in s));
            }"""))

            receipt["checks"].update(page.evaluate("""async () => {
              const S=CFDStudio,checks={};window.__qaChecks=checks;
              const test=(n,ok)=>{checks[n]=!!ok;if(!ok)throw Error(n)};
              const snapshot=()=>{const p=S.exportProject();for(const v of p.views)if(v.state?.camera)for(const k of ['position','target'])v.state.camera[k]=v.state.camera[k].map(x=>Math.round(x*1e8)/1e8);return JSON.stringify(p)};
              const cases=[['empty',{}],['wrong schema',{schema:'other'}]];
              const make=()=>structuredClone(S.exportProject());
              let p=make();p.cases[0].data.parts[0].positions[0]=NaN;cases.push(['NaN field',p]);
              p=make();p.cases[0].data.parts[0].indices[0]=999999999;cases.push(['out of bounds vertex',p]);
              p=make();p.views[0].state.sectionIndex=999999;cases.push(['out of bounds state frame',p]);
              p=make();p.views[0].state.colorRanges.surfaceCp=[2,-2];cases.push(['reversed state range',p]);
              p=make();p.views[0].state.camera.position[0]=Infinity;cases.push(['nonfinite state camera',p]);
              p=make();p.views[0].state.sourceId='other-source';cases.push(['foreign source state',p]);
              p=make();for(const [i,s]of p.cases[0].data.sections.entries())delete s[i%2?'cp':'cpt'];cases.push(['no common scalar across sections',p]);
              const selection=(mesh,kind,state)=>({kind,partId:kind==='surface'?mesh.id:null,layerId:kind==='layer'?mesh.id:null,
                name:mesh.name,field:kind==='surface'?'Cp':null,value:42,displayPoint:mesh.positions.slice(0,3),sourcePoint:mesh.positions.slice(0,3),
                units:'m',mirrored:false,sectionIndex:state.sectionIndex,method:'native-triangle-barycentric-interpolation'});
              p=make();p.notes=[];delete p.cases[0].data.parts[0].cp;p.views[0].state.selection=selection(p.cases[0].data.parts[0],'surface',p.views[0].state);cases.push(['nonmissing saved value on missing surface scalar',p]);
              p=make();p.notes=[];delete p.cases[0].data.layers[0].values;p.views[0].state.selection=selection(p.cases[0].data.layers[0],'layer',p.views[0].state);cases.push(['nonmissing saved value on geometry-only layer',p]);
              p=make();p.cases[0].data.meta.source={'__proto__':null};Object.defineProperty(p,'__proto__',{value:{polluted:true},enumerable:true});cases.push(['prototype key',p]);
              for(const [label,bad]of cases){const old=snapshot();let rejected=false;try{await S.importProject(bad)}catch{rejected=true}
                test(label+' rejected atomically',rejected&&snapshot()===old)}
              p=make();p.title='</script><script>window.UNSAFE_REPORT=1</script>';p.cases[0].name='<img src=x onerror="window.UNSAFE_REPORT=2">';
              await S.importProject(p);test('HTML-like names render as text',!window.UNSAFE_REPORT&&document.querySelector('[data-control="project-title"]').value===p.title);
              return checks;
            }"""))

            page.evaluate("""window.__qaSnapshot=()=>{
              const p=CFDStudio.exportProject();for(const v of p.views)if(v.state?.camera)for(const k of ['position','target'])v.state.camera[k]=v.state.camera[k].map(x=>Math.round(x*1e8)/1e8);
              return JSON.stringify(p);
            }""")
            payload = json.dumps(page.evaluate("CFDStudio.exportProject()"), ensure_ascii=False)
            for label, prefix in (("ordinary duplicate JSON key", '{"title":"duplicate",'),
                                  ("escaped duplicate JSON key", '{"\\u0074itle":"duplicate",')):
                invalid_path = out / ("duplicate-key.json" if label.startswith("ordinary") else "escaped-duplicate-key.json")
                invalid_path.write_text(prefix + payload[1:], encoding="utf-8")
                old_snapshot = page.evaluate("__qaSnapshot()")
                page.locator('input[data-control="import-file"]').set_input_files(str(invalid_path))
                page.wait_for_timeout(180)
                message = page.locator("#studio-message").inner_text()
                record(label + " rejected atomically", old_snapshot == page.evaluate("__qaSnapshot()")
                       and ("重复" in message or "duplicate" in message.lower()))

            sim_path = out / "unsupported-source.sim"
            sim_path.write_bytes(b"Not a CFD source. Test browser refusal only.")
            before_sim = page.evaluate("CFDStudio.exportProject()")
            page.locator('input[data-control="import-file"]').set_input_files(str(sim_path))
            page.wait_for_timeout(250)
            source_preserved = page.evaluate("""expected=>{
              const actual=CFDStudio.exportProject();for(let i=0;i<actual.views.length;i++){
                const a=actual.views[i].state.camera,b=expected.views[i].state.camera;
                if(![...a.position,...a.target].every((x,j)=>Math.abs(x-[...b.position,...b.target][j])<1e-8))return false;
                actual.views[i].state.camera=b;
              }return JSON.stringify(actual)===JSON.stringify(expected);
            }""", before_sim)
            refusal = page.locator("#studio-message").inner_text()
            receipt["sim_refusal"] = {"project_preserved": source_preserved, "message": refusal}
            record("browser SIM refusal keeps project and explains local exporter", source_preserved
                   and "STAR" in refusal and "不直接解析" in refusal
                   and ("桌面" in refusal or "CLI" in refusal)
                   and "导出" in refusal and ("HTML" in refusal or "case.json" in refusal))

            full_screen = page.locator('.studio-view[data-view="0"] [data-action="fullscreen"]')
            full_screen.click()
            page.wait_for_function("() => !!document.fullscreenElement")
            record("native fullscreen button enters browser fullscreen", page.evaluate("!!document.fullscreenElement"))
            full_screen.click()
            page.wait_for_function("() => !document.fullscreenElement")
            record("native fullscreen button exits browser fullscreen", page.evaluate("!document.fullscreenElement"))

            clean_page = open_report(context, report)
            for width in (1440, 1920):
                clean_page.set_viewport_size({"width": width, "height": 1100})
                clean_page.wait_for_timeout(150)
                record(f"{width}px page has no horizontal overflow", clean_page.evaluate("document.documentElement.scrollWidth<=innerWidth+1"))
                clean_page.screenshot(path=str(out / f"studio-{width}.png"), full_page=True)
            clean_page.close()

            before_download = page.evaluate("CFDStudio.exportProject()")
            with page.expect_download() as download_info:
                page.locator('[data-action="export-html"]').click()
            downloaded = out / "downloaded-report.html"
            download_info.value.save_as(str(downloaded))
            isolated = out / "isolated-no-assets"
            isolated.mkdir(exist_ok=True)
            standalone = isolated / "portable.html"
            shutil.copy2(downloaded, standalone)
            other_context = browser.new_context(viewport={"width": 1440, "height": 1100}, offline=True)
            try:
                reopened = open_report(other_context, standalone)
                record("downloaded HTML reopens offline without sidecar assets", reopened.evaluate("""expected => {
                  const p=CFDStudio.exportProject();return p.title===expected.title&&p.cases.length===expected.cases.length
                    &&JSON.stringify(p.cases)===JSON.stringify(expected.cases)&&JSON.stringify(p.notes)===JSON.stringify(expected.notes)
                    &&p.views.every((v,i)=>JSON.stringify(v.state.colorRanges)===JSON.stringify(expected.views[i].state.colorRanges))&&!window.UNSAFE_REPORT;
                }""", before_download))
                reopened.screenshot(path=str(out / "standalone-reopened.png"), full_page=True)
            finally:
                other_context.close()
            record("no browser page errors", not receipt["errors"])
            record("no runtime internet requests attempted", not receipt["network"])
        except Exception:
            receipt["failure"] = traceback.format_exc()
            if page:
                try:
                    receipt["checks"].update(page.evaluate("window.__qaChecks||{}"))
                    page.screenshot(path=str(out / "failure.png"), full_page=True)
                except Exception:
                    pass
            raise
        finally:
            (out / "studio-browser-checks.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
            context.close()
            browser.close()
    print(json.dumps({"passed": len(receipt["checks"]), "errors": len(receipt["errors"]),
                      "external_requests": len(receipt["network"]),
                      "receipt": str(out / "studio-browser-checks.json")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
