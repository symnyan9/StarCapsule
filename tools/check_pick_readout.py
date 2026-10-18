"""Offline browser check for the top-of-canvas scalar readout; synthetic data only."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cfd_review.demo import make_demo_project
from cfd_review.report import build_report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--browser-executable", type=Path)
    args = parser.parse_args()
    out = args.output.resolve(); out.mkdir(parents=True, exist_ok=True)
    receipt = {"fixture": "Explicit synthetic DEMO; no STAR process or real CFD data",
               "checks": {}, "pageErrors": [], "network": []}
    report = build_report(make_demo_project(), out / "pick-readout-demo.html")

    def check(label, condition):
        receipt["checks"][label] = bool(condition)
        if not condition:
            raise AssertionError(label)

    with sync_playwright() as playwright:
        options = {"headless": True, "args": ["--use-gl=angle", "--use-angle=swiftshader",
                                                "--enable-unsafe-swiftshader"]}
        if args.browser_executable:
            options["executable_path"] = str(args.browser_executable.resolve(strict=True))
        browser = playwright.chromium.launch(**options)
        context = browser.new_context(viewport={"width": 1440, "height": 1100},
                                      offline=True, accept_downloads=True)
        try:
            page = context.new_page()
            page.on("pageerror", lambda error: receipt["pageErrors"].append(str(error)))
            page.on("request", lambda req: receipt["network"].append(req.url)
                    if req.url.startswith(("http:", "https:")) else None)
            page.goto(report.as_uri())
            page.wait_for_function("() => window.CFDStudio?.viewers.length===2")
            page.evaluate("CFDStudio.ready")
            page.wait_for_function("() => CFDStudio.viewers.every(v=>v.sectionMesh)")
            check("both readouts sit between camera tools and canvas", page.evaluate("""() =>
              CFDStudio.viewers.every(v=>{const b=v.el('pick-strip').getBoundingClientRect(),
              a=v.root.querySelector('.fv-camera-tools').getBoundingClientRect(),
              c=v.el('canvas').getBoundingClientRect();return b.top>=a.bottom&&b.bottom<=c.top&&b.height>=32;})"""))
            check("initial empty state is distinct", page.evaluate("""() =>
              CFDStudio.viewers.every(v=>v.el('pick-strip').dataset.state==='empty'&&
              v.el('pick-result').textContent.includes('双击'))"""))
            page.evaluate("window.__emptyCanvas=CFDStudio.viewers[0].el('canvas').getBoundingClientRect().toJSON()")
            point = page.evaluate("""() => {
              const v=CFDStudio.viewers[0];v.sectionVisible=false;v.sectionGroup.visible=false;
              v.layerMeshes.forEach(m=>m.visible=false);v.controls.enableDamping=false;
              v._fit('isometric');v.camera.updateMatrixWorld(true);v.scene.updateMatrixWorld(true);
              const r=v.renderer.domElement.getBoundingClientRect();
              for(let y=.1;y<.95;y+=.04)for(let x=.1;x<.95;x+=.04){
               const p={clientX:r.left+r.width*x,clientY:r.top+r.height*y};
               if(v._pick(p,false))return {x:p.clientX,y:p.clientY};}
              throw Error('Synthetic source triangles were not pickable');
            }""")
            page.mouse.dblclick(point["x"], point["y"])
            check("actual double click populates highlighted raw reading", page.evaluate("""() => {
              const v=CFDStudio.viewers[0],s=v.el('pick-strip'),r=v.el('pick-result');
              return !!v.lastPick&&Number.isFinite(v.lastPick.value)&&s.dataset.state==='reading'
               &&r.dataset.state==='reading'&&r.textContent.includes('三角面内插值')
               &&getComputedStyle(s).backgroundColor==='rgb(231, 242, 255)';}"""))
            page.evaluate("window.__pickSaved=CFDStudio.viewers[0].getState()")
            check("a real scalar is isolated in a filled metric rectangle", page.evaluate("""() => {
              const v=CFDStudio.viewers[0],metric=v.el('pick-metric'),value=v.el('pick-value');
              return metric.tagName==='OUTPUT'&&metric.textContent.startsWith('Cp=')&&
               metric.contains(value)&&getComputedStyle(metric).backgroundColor==='rgb(21, 91, 147)'&&
               getComputedStyle(metric).color==='rgb(255, 255, 255)'&&
               parseFloat(getComputedStyle(value).fontSize)>parseFloat(getComputedStyle(v.root.querySelector('.fv-pick-coordinates')).fontSize);
            }"""))
            check("first picked result does not move or shrink the canvas", page.evaluate("""() => {
              const r=CFDStudio.viewers[0].el('canvas').getBoundingClientRect(),b=window.__emptyCanvas;
              return Math.abs(r.top-b.top)<.1&&Math.abs(r.height-b.height)<.1;
            }"""))
            # Render-only format samples exercise zero/missing/geometry; restore the real pick before saving.
            check("zero remains an explicit scalar value", page.evaluate("""() => {
              const v=CFDStudio.viewers[0];v._showPick({...v.lastPick,value:0});
              return v.el('pick-value').textContent==='0'&&!v.el('pick-metric').classList.contains('is-missing');
            }"""))
            check("CpT uses the same independent scalar emphasis", page.evaluate("""() => {
              const v=CFDStudio.viewers[0];v._showPick({...v.lastPick,field:'CpT',value:-.06});
              return v.el('pick-metric').textContent==='CpT=-0.06';
            }"""))
            check("missing scalar has an explicit missing state", page.evaluate("""() => {
              const v=CFDStudio.viewers[0];v._showPick({...v.lastPick,value:null});
              return v.el('pick-value').textContent==='缺测'&&v.el('pick-metric').classList.contains('is-missing');
            }"""))
            check("geometry-only readout has no fabricated scalar rectangle", page.evaluate("""() => {
              const v=CFDStudio.viewers[0];v._showPick({...v.lastPick,field:null,value:null});
              return !v.el('pick-metric')&&v.el('pick-result').textContent.includes('几何图层');
            }"""))
            page.evaluate("CFDStudio.viewers[0].setState(window.__pickSaved)")
            check("color changes retain raw pick and reading state", page.evaluate("""() => {
              const v=CFDStudio.viewers[0],n=v.lastPick.value,state=v.el('pick-strip').dataset.state;v.setColorRange('surface',-.001,.001);
              return v.lastPick.value===n&&v.el('pick-strip').dataset.state===state;}"""))
            # Existing reset semantics now explicitly clear the stale selection display.
            page.locator('.studio-view[data-view="0"] [data-action="reset"]').click()
            check("reset clears selected reading and returns to empty", page.evaluate("""() => {
              const v=CFDStudio.viewers[0];return v.lastPick===null&&
               v.el('pick-strip').dataset.state==='empty'&&v.el('pick-result').textContent.includes('双击');}"""))
            page.evaluate("CFDStudio.viewers[0].setState(window.__pickSaved)")
            check("saved selection restores its readout and highlight", page.evaluate("""() => {
              const v=CFDStudio.viewers[0];return v.lastPick.value===window.__pickSaved.selection.value&&
               v.el('pick-strip').dataset.state==='restored'&&v.el('pick-result').textContent.includes('批注保存读数');}"""))
            check("a visible miss clears the former selected reading", page.evaluate("""() => {
              const v=CFDStudio.viewers[0];v._pick({clientX:-1000,clientY:-1000},true);
              return v.lastPick===null&&v.el('pick-strip').dataset.state==='miss'&&
               v.el('pick-result').textContent.includes('未命中');}"""))
            page.evaluate("CFDStudio.viewers[0].setState(window.__pickSaved)")
            check("switching section clears a now irrelevant selection", page.evaluate("""async() => {
              const v=CFDStudio.viewers[0];await v.setSection((v.sectionIndex+1)%v.sections.length);
              return v.lastPick===null&&v.el('pick-strip').dataset.state==='empty';}"""))
            page.evaluate("CFDStudio.viewers[0].setState(window.__pickSaved)")
            check("long names remain safe readable text in a bounded strip", page.evaluate("""() => {
              const v=CFDStudio.viewers[0],s=v.lastPick;
              v._showPick({...s,name:'<img src=x onerror=alert(1)> · '+('长部件名称 / '.repeat(35))});
              const result=v.el('pick-result'),strip=v.el('pick-strip').getBoundingClientRect(),
               canvas=v.el('canvas').getBoundingClientRect();return !result.querySelector('img')&&
               result.textContent.includes('<img')&&result.getBoundingClientRect().height<=81&&
               strip.bottom<=canvas.top&&canvas.height>=220;
            }"""))
            page.screenshot(path=str(out / "readout-dual-1440.png"))
            page.evaluate("CFDStudio.viewers[0].setState(window.__pickSaved)")
            check("selected critical actions differ from ordinary view presets", page.evaluate("""() => {
              const v=CFDStudio.viewers[0],pick=v.root.querySelector('[data-action="pick"]'),
               preset=v.root.querySelector('[data-action="top"]'),play=v.root.querySelector('[data-action="play"]');
              return getComputedStyle(pick).borderColor!==getComputedStyle(preset).borderColor&&
               getComputedStyle(play).backgroundColor==='rgb(44, 109, 159)';}"""))
            with page.expect_download() as download_info:
                page.locator('[data-action="export-html"]').click()
            saved = out / "readout-reopened.html"
            download_info.value.save_as(saved)
            reopened = context.new_page()
            reopened.on("pageerror", lambda error: receipt["pageErrors"].append(str(error)))
            reopened.goto(saved.as_uri()); reopened.evaluate("CFDStudio.ready")
            reopened.wait_for_function("() => CFDStudio.viewers.every(v=>v.sectionMesh)")
            check("exported HTML restores the scientific pick and top highlight", reopened.evaluate("""() => {
              const v=CFDStudio.viewers[0],s=CFDStudio.project.views[0].state;
              return !!v.lastPick&&v.lastPick.value===s.selection.value&&
               v.el('pick-metric')?.textContent.startsWith('Cp=')&&
               v.el('pick-strip').dataset.state==='restored'&&
               v.el('pick-strip').getBoundingClientRect().bottom<=v.el('canvas').getBoundingClientRect().top;}
            """))
            page.set_viewport_size({"width": 1920, "height": 1080})
            page.screenshot(path=str(out / "readout-dual-1920.png"))
            check("desktop canvas remains usable in both viewports", page.evaluate("""() =>
              CFDStudio.viewers.every(v=>{const c=v.el('canvas').getBoundingClientRect();
              return c.width>=260&&c.height>=220&&c.bottom<=innerHeight;})"""))
            check("no browser errors or online requests", not receipt["pageErrors"] and not receipt["network"])
        finally:
            context.close(); browser.close()
            (out / "pick-readout-checks.json").write_text(json.dumps(receipt, ensure_ascii=False,
                indent=2), encoding="utf-8")
    print(json.dumps({"passed": len(receipt["checks"]), "receipt": str(out / "pick-readout-checks.json")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
