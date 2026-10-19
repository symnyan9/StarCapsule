"""Offline mobile-review checks using synthetic, independently packed sections.

Chromium emulates phone/tablet viewports and touch input. This is not a test on
physical iOS/iPadOS hardware, nor a capacity benchmark for real CFD models.
Requires the optional Playwright development dependency; no STAR is started.
"""
from __future__ import annotations

import argparse
import base64
import gzip
import hashlib
import json
import math
from pathlib import Path
import re
import sys
import time
import traceback
from unittest.mock import patch

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cfd_review import report
from cfd_review.demo import _section, make_demo_case


TINY = 1.2345678901234567e-27
PRECISION = [-0.0, TINY, -9.876543210987654e-19]
PROFILES = (
    {"name": "tablet-landscape-1024x768", "viewport": {"width": 1024, "height": 768},
     "touch": True, "dpr": 2},
    {"name": "tablet-portrait-768x1024", "viewport": {"width": 768, "height": 1024},
     "touch": True, "dpr": 2},
    {"name": "desktop-1440x1000", "viewport": {"width": 1440, "height": 1000},
     "touch": False, "dpr": 1.5},
    {"name": "phone-390x844-layout", "viewport": {"width": 390, "height": 844},
     "touch": True, "dpr": 3, "layout_only": True},
)


def synthetic_project():
    """Unequal section counts expose accidental index-only synchronization."""
    cases = []
    for index, count in enumerate((14, 15, 16)):
        case = make_demo_case(index)
        case["id"] = f"synthetic-mobile-{index}"
        case["name"] = f"DEMO mobile case {index + 1}"
        data = case["data"]
        data["meta"]["title"] = case["name"]
        data["meta"]["scalarMirror"] = False
        data["sections"] = [_section(round(-.25 + 2.35 * i / (count - 1), 7), index)
                            for i in range(count)]
        if index == 2:
            # An explicitly synthetic far-field plane must not shrink the body
            # to a speck in the default tablet view. Full-plane fit stays explicit.
            for cut in data["sections"]:
                cut["positions"] = [value * 1000 if axis % 3 else value
                                    for axis, value in enumerate(cut["positions"])]
        # Check both visited and never-visited cuts, plus surface/layer scalars.
        data["parts"][0]["cp"][:3] = PRECISION
        data["layers"][0]["values"][:3] = PRECISION
        for cut in (data["sections"][0], data["sections"][-1]):
            cut["cp"][:3] = PRECISION
            cut["cpt"][:3] = PRECISION
        cases.append(case)
    project = report.project_from_cases(cases, "Synthetic offline mobile review")
    project["ui"] = {"language": "en", "mobileMode": "auto"}
    return project


def exact_differences(expected, actual, path="$", limit=12):
    """JSON numbers may lose the int/float distinction, but never -0 or bits."""
    if isinstance(expected, bool) or isinstance(actual, bool):
        return [] if type(expected) is type(actual) and expected == actual else [path]
    if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
        equal = expected == actual
        if equal and expected == 0:
            equal = math.copysign(1, expected) == math.copysign(1, actual)
        return [] if equal else [path]
    if isinstance(expected, dict) and isinstance(actual, dict):
        if expected.keys() != actual.keys():
            return [path + " [object keys]"]
        differences = []
        for key in expected:
            differences += exact_differences(expected[key], actual[key], f"{path}.{key}", limit)
            if len(differences) >= limit:
                break
        return differences[:limit]
    if isinstance(expected, list) and isinstance(actual, list):
        if len(expected) != len(actual):
            return [path + " [array length]"]
        differences = []
        for index, (left, right) in enumerate(zip(expected, actual)):
            differences += exact_differences(left, right, f"{path}[{index}]", limit)
            if len(differences) >= limit:
                break
        return differences[:limit]
    return [] if type(expected) is type(actual) and expected == actual else [path]


def manifest_version(path):
    text = path.read_text(encoding="utf-8")
    match = re.search(r'<script\b[^>]*\bid="cfd-project-data"[^>]*>([\s\S]*?)</script\s*>',
                      text, re.I)
    if not match:
        raise AssertionError("Primary project slot is missing")
    document = json.loads(match[1])
    if document.get("schema") == "cfd-review-compressed":
        packed = b"".join(base64.b64decode(chunk, validate=True) for chunk in document["chunks"])
        document = json.loads(gzip.decompress(packed))
    return document.get("schema"), document.get("version")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--browser-executable", type=Path)
    parser.add_argument("--profile", action="append", choices=[p["name"] for p in PROFILES],
                        help="Repeat to limit the run; default checks all emulated profiles.")
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    receipt = {
        "fixture": "Synthetic mathematical meshes only; no native STAR or real CFD data",
        "scope": "Desktop Chromium viewport/touch emulation, not physical iOS/iPadOS testing",
        "checks": {}, "errors": [], "network": [], "profiles": {}, "passed": False,
    }
    receipt_path = out / "mobile-review-checks.json"

    def record(label, passed):
        receipt["checks"][label] = bool(passed)
        if not passed:
            raise AssertionError(label)

    def compare(label, expected, actual):
        differences = exact_differences(expected, actual)
        if differences:
            receipt.setdefault("differences", {})[label] = differences
        record(label, not differences)

    try:
        fixture = synthetic_project()
        source = out / "mobile-v2-synthetic.html"
        with patch.object(report, "_SECTION_BUNDLE_THRESHOLD_BYTES", 0):
            report.build_report(fixture, source, overwrite=True)
        receipt["html"] = {"path": str(source), "bytes": source.stat().st_size,
                           "sha256": hashlib.sha256(source.read_bytes()).hexdigest()}
        record("fixture uses version 2 independent section slots",
               manifest_version(source) == ("cfd-review-html-bundle", 2))
        record("fixture has three cases, at least twelve cuts each and two saved views",
               len(fixture["cases"]) == 3 and len(fixture["views"]) == 2
               and all(len(c["data"]["sections"]) >= 12 for c in fixture["cases"]))
        compare("Python writer and loader preserve complete source including negative zero",
                fixture, report.load_report_document(source))

        with sync_playwright() as playwright:
            launch = {"headless": True, "args": ["--use-gl=angle", "--use-angle=swiftshader",
                                                 "--enable-unsafe-swiftshader"]}
            if args.browser_executable:
                launch["executable_path"] = str(args.browser_executable.resolve(strict=True))
            browser = playwright.chromium.launch(**launch)
            try:
                for profile in PROFILES:
                    if args.profile and profile["name"] not in args.profile:
                        continue
                    name, mobile = profile["name"], profile["touch"]
                    info = receipt["profiles"][name] = {"emulated": True, **profile}
                    context = browser.new_context(viewport=profile["viewport"],
                        has_touch=mobile, is_mobile=mobile, device_scale_factor=profile["dpr"],
                        offline=True, accept_downloads=True)
                    context.set_default_timeout(30000)

                    def check(label, condition):
                        record(name + ": " + label, condition)

                    def observe(page):
                        page.on("pageerror", lambda error: receipt["errors"].append(
                            {"profile": name, "error": str(error)}))
                        page.on("request", lambda request: receipt["network"].append(
                            {"profile": name, "url": request.url})
                            if request.url.startswith(("http:", "https:")) else None)

                    def open_page(path):
                        page = context.new_page()
                        observe(page)
                        started = time.perf_counter()
                        page.goto(path.as_uri())
                        page.wait_for_function("() => !!window.CFDStudio")
                        check("file report initializes offline", page.evaluate("CFDStudio.ready"))
                        page.wait_for_function("() => CFDStudio.viewers.length>0 && CFDStudio.viewers.every(v=>v.sectionMesh)")
                        return page, round((time.perf_counter() - started) * 1000, 2)

                    try:
                        page, info["readyWallMs"] = open_page(source)
                        check("mobile APIs are available", page.evaluate("""() =>
                          !!CFDStudio.lazyMetrics && typeof CFDStudio.materializeProject==='function'
                          && typeof CFDStudio.setMobileMode==='function'"""))
                        check("automatic profile matches viewport and pointer", page.evaluate(
                            "() => document.documentElement.dataset.mobileReview==='true'") == mobile)
                        expected_views = 1 if mobile else 2
                        check("actual viewer count is bounded without deleting saved views", page.evaluate(
                            "() => ({live:CFDStudio.viewers.length,saved:CFDStudio.project.views.length})")
                            == {"live": expected_views, "saved": 2})
                        initial = info["initialLazy"] = page.evaluate("CFDStudio.lazyMetrics")
                        check("initial display does not decode all cases or cuts",
                              0 < initial["coreLoads"] < 3 and 0 < initial["sectionLoads"] < 45
                              and initial["residentCores"] <= expected_views
                              and initial["residentSections"] <= 2 * expected_views)
                        check("mobile renderer caps DPR at one", page.evaluate("""mobile =>
                          CFDStudio.viewers.every(v=>!mobile || v.renderer.getPixelRatio()===1)
                          && window.devicePixelRatio>1""", mobile))
                        check("canvas remains visible and useful", page.evaluate("""() =>
                          CFDStudio.viewers.every(v=>{const r=v.renderer.domElement.getBoundingClientRect();
                          return r.width>=250&&r.height>=220&&r.top>=0&&r.bottom<=innerHeight+2;})"""))
                        check("document has no horizontal overflow", page.evaluate("""() =>
                          document.documentElement.scrollWidth<=innerWidth+1
                          && document.body.scrollWidth<=innerWidth+1"""))
                        if profile.get("layout_only"):
                            # Phone is a bounded layout smoke check. Full touch,
                            # caching and roundtrip acceptance targets tablets.
                            page.screenshot(path=str(out / (name + ".png")))
                            check("no phone layout JavaScript error",
                                  not any(e["profile"] == name for e in receipt["errors"]))
                            page.close()
                            continue

                        # Export before touching case 3 or its final cut. A save must
                        # reuse its encoded slots rather than first loading everything.
                        page.evaluate("""async () => {const v=CFDStudio.viewers[0];
                          await CFDStudio.setLink('color',false);
                          await v.setColorRange('surface',-1.2345,.6789);
                          await v.setColorRange('section',-.125,.925,'CpT');
                          CFDStudio.addNote('Synthetic offline mobile review: retain all unvisited evidence.',0);
                        }""")
                        before_export = page.evaluate("CFDStudio.lazyMetrics")
                        with page.expect_download() as download:
                            page.evaluate("CFDStudio.downloadHTML()")
                        saved = out / (name + "-reopened.html")
                        download.value.save_as(saved)
                        after_export = page.evaluate("CFDStudio.lazyMetrics")
                        info["afterExportLazy"] = after_export
                        check("HTML export does not decode unvisited evidence",
                              before_export["coreLoads"] == after_export["coreLoads"]
                              and before_export["sectionLoads"] == after_export["sectionLoads"])
                        check("HTML export retains independently packed sections",
                              manifest_version(saved) == ("cfd-review-html-bundle", 2))
                        complete = report.load_report_document(saved)
                        compare(name + ": downloaded HTML exactly preserves every source array and identity",
                                fixture["cases"], complete["cases"])
                        check("download retains two views, automatic profile and independent links",
                              len(complete["views"]) == 2
                              and complete["ui"]["mobileMode"] == "auto"
                              and complete["links"]["color"] is False)
                        check("download retains both color ranges and complete note state",
                              complete["views"][0]["state"]["colorRanges"]["surfaceCp"] == [-1.2345, .6789]
                              and complete["views"][0]["state"]["colorRanges"]["section"]["CpT"] == [-.125, .925]
                              and len(complete["notes"]) == 1
                              and complete["notes"][0]["state"]["colorRanges"] == complete["views"][0]["state"]["colorRanges"])

                        if mobile:
                            toggle = page.locator('.studio-view[data-view="0"] [data-action="toggle-settings"]')
                            toggle.tap()
                            check("drawer opens with accessible state and a focused close action", page.evaluate("""() => {
                              const v=CFDStudio.viewers[0],b=v.root.querySelector('[data-action="toggle-settings"]'),
                              s=v.el('settings');return b.getAttribute('aria-expanded')==='true'
                              &&s.getAttribute('aria-hidden')==='false'&&!!s.getAttribute('aria-label')
                              &&s.contains(document.activeElement)&&getComputedStyle(s).display!=='none';} """))
                            check("drawer controls have usable touch targets", page.evaluate("""() => {
                              const v=CFDStudio.viewers[0],r=v.el('variable').getBoundingClientRect(),
                              b=v.root.querySelector('[data-action="toggle-settings"]').getBoundingClientRect();
                              return r.height>=44&&b.height>=44&&b.width>=44;}"""))
                            page.screenshot(path=str(out / (name + "-drawer.png")))
                            page.locator('.studio-view[data-view="0"] [data-fv="variable"]').select_option("Cp")
                            check("drawer field selector changes actual section rendering", page.evaluate(
                                "() => CFDStudio.viewers[0].variable==='Cp'"))
                            page.locator('.studio-view[data-view="0"] [data-fv="variable"]').select_option("CpT")
                            page.keyboard.press("Escape")
                            check("Escape closes drawer and returns focus to its trigger", page.evaluate("""() => {
                              const v=CFDStudio.viewers[0],b=v.root.querySelector('[data-action="toggle-settings"]');
                              return b.getAttribute('aria-expanded')==='false'
                              &&v.el('settings').getAttribute('aria-hidden')==='true'&&document.activeElement===b;}"""))
                            # Use a real browser touch tap after locating a hit on
                            # actual synthetic triangles. No fabricated pick result.
                            page.evaluate("""async () => {const v=CFDStudio.viewers[0],s=v.getState();
                              s.sectionVisible=false;for(const layer of Object.values(s.layerSettings))layer.visible=false;
                              await v.setState(s);v.controls.enableDamping=false;v._fit('isometric');
                            }""")
                            page.locator('.studio-view[data-view="0"] [data-action="pick"]').tap()
                            point = page.evaluate("""() => {const v=CFDStudio.viewers[0];
                              v.camera.updateMatrixWorld(true);v.scene.updateMatrixWorld(true);
                              const r=v.renderer.domElement.getBoundingClientRect();
                              for(let y=.2;y<.82;y+=.035)for(let x=.12;x<.82;x+=.035){
                               const p={clientX:r.left+r.width*x,clientY:r.top+r.height*y};
                               if(v._pick(p,false))return{x:p.clientX,y:p.clientY};}
                              throw Error('No visible source triangle in synthetic touch fixture');}""")
                            page.touchscreen.tap(point["x"], point["y"])
                            check("actual touch tap picks a source scalar into a highlighted rectangle", page.evaluate("""() => {
                              const v=CFDStudio.viewers[0],m=v.el('pick-metric');return !!v.lastPick
                              &&Number.isFinite(v.lastPick.value)&&v.el('pick-strip').dataset.state==='reading'
                              &&!!m&&getComputedStyle(m).backgroundColor!==getComputedStyle(v.el('pick-strip')).backgroundColor;}"""))
                            info["touchPick"] = page.evaluate("CFDStudio.viewers[0].lastPick")
                            page.screenshot(path=str(out / (name + "-touch-pick.png")))
                            before_rotation = page.evaluate("""() => ({
                              section:CFDStudio.viewers[0].sectionIndex,
                              notes:JSON.stringify(CFDStudio.project.notes),
                              cores:CFDStudio.lazyMetrics.coreLoads})""")
                            rotated = {"width": profile["viewport"]["height"],
                                       "height": profile["viewport"]["width"]}
                            page.set_viewport_size(rotated)
                            page.evaluate("new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))")
                            check("orientation change keeps one canvas without reloading the source", page.evaluate("""before =>
                              CFDStudio.viewers.length===1&&CFDStudio.project.views.length===2
                              &&CFDStudio.viewers[0].sectionIndex===before.section
                              &&CFDStudio.lazyMetrics.coreLoads===before.cores
                              &&JSON.stringify(CFDStudio.project.notes)===before.notes
                              &&document.documentElement.scrollWidth<=innerWidth+1""", before_rotation))
                            page.set_viewport_size(profile["viewport"])
                            page.evaluate("new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))")
                            check("returning orientation preserves the source-valued touch readout", page.evaluate("""() =>
                              !!CFDStudio.viewers[0].lastPick&&CFDStudio.viewers[0].renderer.getPixelRatio()===1
                              &&document.documentElement.scrollWidth<=innerWidth+1"""))

                        # Delay the real Blob read to inspect the pending-task UI,
                        # rather than racing an intentionally tiny synthetic case.
                        page.evaluate("""() => {
                          window.__blobText=Blob.prototype.text;
                          Blob.prototype.text=function(){const blob=this;return new Promise(resolve=>
                            setTimeout(()=>resolve(window.__blobText.call(blob)),350));};
                          window.__pendingCase=CFDStudio.setViewCase(0,'synthetic-mobile-2');
                        }""")
                        page.locator('.studio-task-status').wait_for(state='visible')
                        check("pending local work exposes a readable accessible task status", page.evaluate("""() => {
                          const task=document.querySelector('.studio-task-status');
                          return task.getAttribute('role')==='status'&&task.getAttribute('aria-busy')==='true'
                            &&task.querySelector('strong').textContent.length>5
                            &&task.querySelector('[data-role="task-detail"]').textContent.length>5
                            &&!!task.querySelector('progress');}"""))
                        page.screenshot(path=str(out / (name + '-task-running.png')))
                        page.evaluate("""async()=>{try{await window.__pendingCase;}
                          finally{Blob.prototype.text=window.__blobText;}}""")
                        check("successful work clears the task indicator", page.locator('.studio-task-status').is_hidden()
                              and page.locator('#app').get_attribute('aria-busy') == 'false')
                        if mobile:
                            check("tablet body fit stays useful beside large far-field sections", page.evaluate("""() => {
                              const v=CFDStudio.viewers[0];v._fit('isometric');
                              const body=v.camera.position.distanceTo(v.controls.target);
                              v._fit('isometric',true);const whole=v.camera.position.distanceTo(v.controls.target);
                              return body>0&&whole>body*100;}"""))
                        page.evaluate("CFDStudio.setViewCase(0,'synthetic-mobile-0')")

                        # More than two real X planes must never make all section
                        # arrays resident. Return to a retained cut to test a hit.
                        info["sectionWorkingSets"] = page.evaluate("""async () => {
                          await CFDStudio.setLink('section',false);const metrics=[];
                          for(const i of [0,1,2,1,3,4,5,6,7,8,9,10,11,12,0]){
                            await CFDStudio.viewers[0].setSection(i);metrics.push({...CFDStudio.lazyMetrics});}
                          return metrics;}""")
                        check("section cache stays bounded while scanning and revisiting real cuts",
                              all(m["residentSections"] <= 2 * m["residentCores"]
                                  for m in info["sectionWorkingSets"])
                              and info["sectionWorkingSets"][-1]["sectionLoads"] > after_export["sectionLoads"])
                        check("revisiting a retained section records a cache hit",
                              info["sectionWorkingSets"][3]["sectionCacheHits"]
                              > info["sectionWorkingSets"][2]["sectionCacheHits"])
                        page.evaluate("id => CFDStudio.setViewCase(0,id)", "synthetic-mobile-2")
                        switched = info["afterCaseSwitch"] = page.evaluate("CFDStudio.lazyMetrics")
                        check("switching cases releases former unreferenced core and cuts", page.evaluate("""limit => {
                          const old=CFDStudio.project.cases.find(c=>c.id==='synthetic-mobile-0'),m=CFDStudio.lazyMetrics;
                          return old.data.parts.every(p=>p.positions.length===0)
                          &&(old.data.layers||[]).every(l=>l.positions.length===0)
                          &&m.residentCores<=limit&&m.residentSections<=2*limit;}""", expected_views))
                        page.evaluate("CFDStudio.setViewCase(0,'synthetic-mobile-0')")
                        check("returning to an evicted case reloads its own core",
                              page.evaluate("CFDStudio.lazyMetrics.coreLoads") > switched["coreLoads"])
                        page.screenshot(path=str(out / (name + ".png")))

                        # An explicit desktop override restores both original saved
                        # views. A forced mobile override must not delete view B.
                        page.evaluate("CFDStudio.setMobileMode('on')")
                        check("forced mobile keeps one live viewer and two saved views", page.evaluate("""() =>
                          CFDStudio.viewers.length===1&&CFDStudio.project.views.length===2
                          &&CFDStudio.viewers[0].renderer.getPixelRatio()===1"""))
                        page.evaluate("CFDStudio.setMobileMode('off')")
                        check("desktop override restores both saved views", page.evaluate("""() =>
                          CFDStudio.viewers.length===2&&CFDStudio.project.views.length===2
                          &&document.documentElement.dataset.mobileReview==='false'"""))
                        materialized = page.evaluate("CFDStudio.materializeProject()")
                        compare(name + ": explicit full materialization preserves every source number",
                                fixture["cases"], materialized["cases"])
                        page.close()

                        # A mobile-saved automatic profile reopens in two desktop
                        # views, without losing the unvisited source or the note.
                        desktop_context = browser.new_context(offline=True, accept_downloads=True,
                            viewport={"width": 1440, "height": 1000})
                        try:
                            reopened = desktop_context.new_page()
                            observe(reopened)
                            reopened.goto(saved.as_uri())
                            reopened.wait_for_function("() => !!window.CFDStudio")
                            check("saved HTML reopens offline", reopened.evaluate("CFDStudio.ready"))
                            check("automatic desktop reopen restores both saved views", reopened.evaluate("""() =>
                              CFDStudio.viewers.length===2&&CFDStudio.project.views.length===2
                              &&document.documentElement.dataset.mobileReview==='false'"""))
                            reopened_data = reopened.evaluate("CFDStudio.materializeProject()")
                            compare(name + ": reopened report restores all scientific arrays exactly",
                                    fixture["cases"], reopened_data["cases"])
                            compare(name + ": reopened report restores complete note state",
                                    complete["notes"], reopened_data["notes"])
                        finally:
                            desktop_context.close()
                        check("no uncaught JavaScript errors for this profile",
                              not any(e["profile"] == name for e in receipt["errors"]))
                    finally:
                        context.close()
                record("all profiles run without online requests", not receipt["network"])
                record("all profiles run without uncaught JavaScript errors", not receipt["errors"])
                receipt["passed"] = True
            finally:
                browser.close()
    except Exception:
        receipt["exception"] = traceback.format_exc()
    finally:
        receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"passed": receipt["passed"], "checks": len(receipt["checks"]),
                      "receipt": str(receipt_path)}, ensure_ascii=True))
    if not receipt["passed"]:
        print(receipt.get("exception", ""))
    return 0 if receipt["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
