"""Offline compact-layout and linked-view checks on synthetic meshes.

Chromium viewport/touch emulation is not physical iPad or Safari acceptance.
Requires the optional Playwright development dependency; no STAR is started.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import traceback

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from cfd_review import report
from cfd_review.demo import make_demo_case

PROFILES = (("tablet-1024", 1024, 768, True),
            ("tablet-1366", 1366, 800, True),
            ("portrait", 768, 1024, True),
            ("desktop", 1440, 1000, False))
METRICS = """() => {
 const q=s=>{const e=document.querySelector(s);if(!e)return null;
  const r=e.getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height,bottom:r.bottom};};
 return {viewport:{width:innerWidth,height:innerHeight},header:q('.studio-header'),
  compare:q('.studio-compare-bar'),heading:q('.studio-view-heading'),
  toolbar:q('.fv-camera-tools'),readout:q('.fv-pick-strip'),
  canvas:q('.fv-canvas canvas'),frame:q('.fv-frame-status'),
  body:{scrollWidth:document.documentElement.scrollWidth,scrollHeight:document.documentElement.scrollHeight},
  mobile:StarCapsuleMobile.active};
}"""


def fixture(language):
    project = report.project_from_cases([make_demo_case(0), make_demo_case(1)],
                                       "Synthetic compact layout review")
    project["ui"] = {"language": language, "mobileMode": "auto"}
    return project


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, help="Previously captured metrics.json")
    parser.add_argument("--browser-executable", type=Path)
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    receipt = {"scope": "Offline Chromium emulation; no physical iPad/Safari or real CFD test",
               "checks": {}, "errors": [], "network": [], "profiles": {}, "passed": False}
    baseline = json.loads(args.baseline.read_text(encoding="utf-8")) if args.baseline else {}

    def check(label, ok):
        receipt["checks"][label] = bool(ok)

    def settle(page):
        page.evaluate("new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))")

    def open_report(page, path):
        page.goto(path.as_uri())
        page.wait_for_function("window.CFDStudio")
        check("offline report opens: " + path.name, page.evaluate("CFDStudio.ready"))
        page.wait_for_function("CFDStudio.viewers.every(v=>v.sectionMesh)")
        settle(page)

    def linked_actions(page, context, name, touch):
        """Use the actual link checkboxes and actual viewer change events."""
        page.locator('[data-action="layout-compare"]').click()
        page.wait_for_function("CFDStudio.viewers.length===2&&CFDStudio.viewers.every(v=>v.sectionMesh)")
        settle(page)
        menu = page.locator('.studio-link-menu')
        menu.locator('summary').click()
        check(name + ": link options enabled for two live views", page.evaluate("""() =>
          [...document.querySelectorAll('.studio-links input')].every(e=>!e.matches(':disabled'))"""))
        check(name + ": link popover is unclipped", page.evaluate("""() => {
          const r=document.querySelector('.studio-link-popover').getBoundingClientRect();
          const target=document.querySelector('[data-control="link-color"]'),t=target.getBoundingClientRect(),
            hit=document.elementFromPoint(t.x+t.width/2,t.y+t.height/2);
          return r.left>=0&&r.top>=0&&r.right<=innerWidth+1&&r.bottom<=innerHeight+1
            &&target.closest('label').contains(hit);}"""))
        for key in ('camera', 'section', 'field', 'color'):
            page.locator('[data-control="link-' + key + '"]').uncheck()
        menu.locator('summary').click()
        independent = page.evaluate("""async()=>{
          const [a,b]=CFDStudio.viewers;b.controls.enableDamping=false;a.controls.enableDamping=false;
          const before=b.getState();a._fit('top');await a.setSection(a.sections.length-1);
          await a.setField('Cp');a.setColorRange('surface',-.123,.456);
          a.setColorRange('section',-.234,.567,'Cp');return before;}""")
        settle(page)
        check(name + ": disabling four links preserves counterpart after source actions", page.evaluate("""before=>{
          const b=CFDStudio.viewers[1].getState(),same=(a,b)=>JSON.stringify(a)===JSON.stringify(b);
          const stableCamera=[...before.camera.position,...before.camera.target].every((n,i)=>
            Math.abs(n-[...b.camera.position,...b.camera.target][i])<1e-8);
          return stableCamera&&before.sectionIndex===b.sectionIndex
            &&before.variable===b.variable&&same(before.colorRanges,b.colorRanges);}""", independent))
        for key in ('camera', 'section', 'field', 'color'):
            menu.locator('summary').click()
            page.locator('[data-control="link-' + key + '"]').check()
            menu.locator('summary').click()
            if key == 'camera':
                page.wait_for_function("""() => {
                  const [a,b]=CFDStudio.viewers.map(v=>v.getState().camera);
                  return [...a.position,...a.target].every((n,i)=>Math.abs(n-[...b.position,...b.target][i])<1e-7);}""")
            elif key == 'section':
                page.wait_for_function("""() => {const [a,b]=CFDStudio.viewers,x=a.sections[a.sectionIndex].x;
                  const index=b.sections.reduce((best,s,i)=>Math.abs(s.x-x)<Math.abs(b.sections[best].x-x)?i:best,0);
                  return b.sectionIndex===index;}""")
            elif key == 'field':
                page.wait_for_function("CFDStudio.viewers.every(v=>v.variable==='Cp')")
            else:
                page.wait_for_function("""CFDStudio.viewers.every(v=>
                  JSON.stringify(v.colorRanges.surfaceCp)==='[-0.123,0.456]'
                  &&JSON.stringify(v.colorRanges.section.Cp)==='[-0.234,0.567]')""")
            check(name + ': enabling ' + key + ' immediately resynchronizes', True)

        # Source changes can arrive faster than asynchronous target planes finish.
        # After a rapid run the source must not snap to a target's nearest plane.
        page.evaluate("""async()=>{const a=CFDStudio.viewers[0];
          for(const i of [0,2,4,a.sections.length-2]){a.setSection(i);await new Promise(r=>setTimeout(r,1));}
          await a.setSection(a.sections.length-1);}""")
        settle(page)
        check(name + ": rapid slice linking keeps source final plane", page.evaluate("""() => {
          const [a,b]=CFDStudio.viewers,x=a.sections[a.sectionIndex].x;
          const j=b.sections.reduce((best,s,i)=>Math.abs(s.x-x)<Math.abs(b.sections[best].x-x)?i:best,0);
          return a.sectionIndex===a.sections.length-1&&b.sectionIndex===j;}"""))
        race = page.evaluate("""async()=>{const S=CFDStudio,[a,b]=S.viewers;
          await S.setLink('camera',false);await S.setLink('field',false);await S.setLink('color',false);
          const original=b.setSectionX.bind(b);let calls=0;
          b.setSectionX=async x=>{const delay=++calls===1?20:100;
            await new Promise(r=>setTimeout(r,delay));return original(x);};
          try{await a.setSection(4);await a.setSection(2);await new Promise(r=>setTimeout(r,220));
            return {source:a.sectionIndex,target:b.sectionIndex,calls};}
          finally{b.setSectionX=original;}}""")
        check(name + ": overlapping target loads never snap source to target plane", race['source'] == 2
              and race['target'] == 2 and race['calls'] >= 2)
        # Save a nontrivial preference combination; single-view mobile mode must
        # disable applicability without overwriting these saved preferences.
        page.evaluate("""async()=>{await CFDStudio.setLink('camera',false);
          await CFDStudio.setLink('field',false);}""")
        expected_links = page.evaluate("({...CFDStudio.project.links})")
        with page.expect_download() as event:
            page.evaluate("CFDStudio.downloadHTML()")
        saved = out / (name + '-linked-reopen.html')
        event.value.save_as(saved)
        complete = report.load_report_document(saved)
        check(name + ": saved HTML retains four link preferences", complete['links'] == expected_links)
        reopen = context.new_page()
        open_report(reopen, saved)
        check(name + ": reopening retains link preferences", reopen.evaluate("({...CFDStudio.project.links})") == expected_links)
        if touch:
            check(name + ": mobile opens one live view without losing two saved views", reopen.evaluate(
                "CFDStudio.viewers.length===1&&CFDStudio.project.views.length===2"))
            check(name + ": mobile-disabled links retain saved states", reopen.evaluate("""() =>
              [...document.querySelectorAll('.studio-links input')].every(e=>e.matches(':disabled')
                &&e.checked===CFDStudio.project.links[e.dataset.control.slice(5)])"""))
            reopen.locator('[data-action="layout-compare"]').click()
            reopen.wait_for_function("CFDStudio.viewers.length===2&&CFDStudio.viewers.every(v=>v.sectionMesh)")
            check(name + ": explicit tablet comparison restores saved preferences", reopen.evaluate("""expected=>
              JSON.stringify(CFDStudio.project.links)===JSON.stringify(expected)
              &&[...document.querySelectorAll('.studio-links input')].every(e=>!e.matches(':disabled'))""", expected_links))
        reopen.close()

    try:
        sources = {}
        for language in ("en", "zh-CN"):
            path = out / ("compact-" + language + ".html")
            report.build_report(fixture(language), path, overwrite=True)
            sources[language] = path
        with sync_playwright() as playwright:
            launch = {"headless": True, "args": ["--use-gl=angle", "--use-angle=swiftshader",
                                                  "--enable-unsafe-swiftshader"]}
            if args.browser_executable:
                launch["executable_path"] = str(args.browser_executable.resolve(strict=True))
            browser = playwright.chromium.launch(**launch)
            try:
                for profile, width, height, touch in PROFILES:
                    for language in ("en", "zh-CN"):
                        name = profile + "-" + language
                        context = browser.new_context(viewport={"width": width, "height": height},
                            has_touch=touch, is_mobile=touch, device_scale_factor=1,
                            offline=True, accept_downloads=True)
                        context.set_default_timeout(20000)
                        page = context.new_page()
                        page.on("pageerror", lambda error, n=name: receipt["errors"].append(
                            {"profile": n, "message": str(error)}))
                        page.on("request", lambda request, n=name: receipt["network"].append(
                            {"profile": n, "url": request.url}) if request.url.startswith(("http:", "https:")) else None)
                        open_report(page, sources[language])
                        if not touch:
                            page.locator('[data-action="layout-single"]').click()
                            page.wait_for_function("CFDStudio.viewers.length===1")
                        settle(page)
                        metrics = receipt["profiles"][name] = page.evaluate(METRICS)
                        check(name + ": canvas stays in viewport", metrics["canvas"]["bottom"] <= height + 1)
                        check(name + ": document does not overflow", metrics["body"]["scrollWidth"] <= width
                              and metrics["body"]["scrollHeight"] <= height + 1)
                        if name in baseline:
                            gain = metrics["canvas"]["height"] - baseline[name]["canvas"]["height"]
                            metrics["canvasHeightGain"] = gain
                            check(name + ": canvas gains useful height", gain >= (55 if touch else 12))
                        check(name + ": single-view links disabled with explanation", page.evaluate("""() => {
                          const menu=document.querySelector('.studio-link-menu'),
                           status=document.querySelector('[data-role="link-status"]');
                          return CFDStudio.viewers.length===1&&!!status&&status.textContent.trim().length>10
                            &&[...document.querySelectorAll('.studio-links input')].every(e=>e.matches(':disabled'))
                            &&menu.textContent.length>20;}"""))
                        check(name + ": main touch actions remain large", page.evaluate("""touch => !touch ||
                          ['pick','toggle-settings'].every(action=>{
                           const r=document.querySelector('.studio-view [data-action="'+action+'"]').getBoundingClientRect();
                           return r.width>=44&&r.height>=44;})""", touch))
                        page.screenshot(path=str(out / (name + "-main.png")))

                        preset_menu = page.locator('.fv-view-menu').first
                        preset_menu.locator('summary').click()
                        check(name + ": view presets popover is reachable", page.evaluate("""() => {
                          const e=document.querySelector('.fv-view-menu[open] .fv-view-presets'),
                            r=e.getBoundingClientRect(),target=e.querySelector('[data-action="fit-section"]'),
                            t=target.getBoundingClientRect(),hit=document.elementFromPoint(t.x+t.width/2,t.y+t.height/2);
                          return r.left>=0&&r.top>=0&&r.right<=innerWidth+1&&r.bottom<=innerHeight+1
                            &&target.contains(hit);}"""))
                        page.screenshot(path=str(out / (name + "-view-presets.png")))
                        preset_menu.locator('[data-action="top"]').click()
                        page.keyboard.press('Escape')

                        case_menu = page.locator('.studio-case-menu').first
                        case_menu.locator('summary').click()
                        check(name + ": case tools popover fits viewport", page.evaluate("""() => {
                          const e=document.querySelector('.studio-case-menu[open] .studio-case-popover'),
                            r=e.getBoundingClientRect(),target=e.querySelector('[data-control="case-name"]'),
                            t=target.getBoundingClientRect(),hit=document.elementFromPoint(t.x+t.width/2,t.y+t.height/2);
                          return r.left>=0&&r.top>=0&&r.right<=innerWidth+1
                            &&r.bottom<=innerHeight+1&&!!e.querySelector('[data-control="case-name"]')
                            &&!!e.querySelector('[data-action="view-note"]')&&target.contains(hit);}"""))
                        page.screenshot(path=str(out / (name + "-case-tools.png")))
                        case_menu.locator('summary').click()

                        more = page.locator('.studio-more-menu')
                        more.locator('summary').click()
                        check(name + ": More popover fits viewport", page.evaluate("""() => {
                          const e=document.querySelector('.studio-more-popover'),r=e.getBoundingClientRect();
                          const target=e.querySelector('[data-action="export-project"]'),t=target.getBoundingClientRect(),
                            hit=document.elementFromPoint(t.x+t.width/2,t.y+t.height/2);
                          return r.left>=0&&r.top>=0&&r.right<=innerWidth+1&&r.bottom<=innerHeight+1
                            &&e.querySelector('[data-control="language"]')
                            &&e.querySelector('[data-control="mobile-mode"]')
                            &&target.contains(hit);}"""))
                        check(name + ": More touch settings remain large", page.evaluate("""touch=>!touch||
                          [...document.querySelectorAll('.studio-more-popover select,.studio-more-popover button')]
                            .every(e=>e.getBoundingClientRect().height>=44)""", touch))
                        page.screenshot(path=str(out / (name + "-more.png")))
                        more.locator('summary').click()

                        # The per-view settings drawer must remain reachable after
                        # compaction; desktop retains its permanently visible panel.
                        if touch:
                            trigger = page.locator('.studio-view [data-action="toggle-settings"]').first
                            trigger.tap()
                            check(name + ": drawer visible and within viewport", page.evaluate("""() => {
                              const v=CFDStudio.viewers[0],s=v.el('settings'),r=s.getBoundingClientRect();
                              return getComputedStyle(s).display!=='none'&&s.getAttribute('aria-hidden')==='false'
                                &&r.left>=0&&r.right<=innerWidth+1&&r.bottom<=innerHeight+1
                                &&r.width>=250;}"""))
                            page.screenshot(path=str(out / (name + "-settings.png")))
                            page.keyboard.press("Escape")
                            check(name + ": drawer returns focus", trigger.get_attribute("aria-expanded") == "false"
                                  and page.evaluate("document.activeElement.matches('[data-action=\"toggle-settings\"]')"))

                        # Real source-triangle picking, not a fabricated readout.
                        page.evaluate("""async()=>{const v=CFDStudio.viewers[0],s=v.getState();
                          s.sectionVisible=false;for(const l of Object.values(s.layerSettings))l.visible=false;
                          await v.setState(s);v._fit('isometric');v.controls.enableDamping=false;}""")
                        page.locator('.studio-view [data-action="pick"]').first.click()
                        point = page.evaluate("""() => {const v=CFDStudio.viewers[0];v.camera.updateMatrixWorld(true);
                          v.scene.updateMatrixWorld(true);const r=v.renderer.domElement.getBoundingClientRect();
                          for(let y=.2;y<.85;y+=.035)for(let x=.15;x<.85;x+=.035){
                           const e={clientX:r.left+r.width*x,clientY:r.top+r.height*y};
                           if(v._pick(e,false))return{x:e.clientX,y:e.clientY};}throw Error('No source triangle');}""")
                        (page.touchscreen.tap if touch else page.mouse.click)(point["x"], point["y"])
                        check(name + ": picked metric stays prominent and on screen", page.evaluate("""() => {
                          const v=CFDStudio.viewers[0],m=v.el('pick-metric'),r=m?.getBoundingClientRect(),
                           strip=v.el('pick-strip');return !!v.lastPick&&Number.isFinite(v.lastPick.value)
                           &&!!r&&r.height>=24&&r.top>=0&&r.bottom<=innerHeight
                           &&getComputedStyle(m).backgroundColor!==getComputedStyle(strip).backgroundColor;}"""))
                        page.screenshot(path=str(out / (name + "-picked.png")))
                        if language == 'en' and profile in ('tablet-1024', 'desktop'):
                            linked_actions(page, context, name, touch)
                        context.close()
                receipt["passed"] = all(receipt['checks'].values())
            finally:
                browser.close()
        check("no page JavaScript errors", not receipt["errors"])
        check("all review operations stay offline", not receipt["network"])
        receipt["passed"] = all(receipt['checks'].values())
    except Exception:
        receipt["failure"] = traceback.format_exc()
        receipt["passed"] = False
    (out / "compact-layout-checks.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"passed": receipt["passed"], "checks": len(receipt["checks"]),
                      "receipt": str(out / "compact-layout-checks.json"),
                      "failedChecks": [key for key, ok in receipt['checks'].items() if not ok],
                      "failure": receipt.get("failure")}, ensure_ascii=True))
    return 0 if receipt["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
