"""Offline lossless report-compression checks with synthetic meshes only.

Requires the optional Playwright development dependency. Timings describe this
bounded mathematical fixture, not real-model capacity or a browser speed claim.
"""
from __future__ import annotations

import argparse
import base64
import copy
import gzip
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
from cfd_review.demo import make_demo_case


SLOT = re.compile(r'(<script\b[^>]*\bid="(?:cfd-project-data|cfd-case-data-\d+)"[^>]*>)([\s\S]*?)(</script\s*>)', re.I)
LIMIT = 500 * 1024 * 1024
TINY = 1.2345678901234567e-27


def raw_json(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).replace("<", "\\u003c").encode("utf-8")


def compressed(value, *, raw=None):
    raw = raw_json(value) if raw is None else raw
    packed = gzip.compress(raw, mtime=0)
    # Each member is independently base64 encoded, not a split base64 string.
    return {"schema": "cfd-review-compressed", "version": 1, "encoding": "gzip-base64", "decodedBytes": len(raw),
            "chunks": [base64.b64encode(packed[i:i + 32768]).decode("ascii") for i in range(0, len(packed), 32768)]}


def slot_script(identifier, value):
    return '<script id="' + identifier + '" type="application/json">' + raw_json(value).decode("utf-8") + '</script>'


def synthetic_case(variant):
    case = make_demo_case(variant)
    case["data"]["meta"]["scalarMirror"] = False
    case["data"]["parts"][0]["cp"][:3] = [-0.0, TINY, -9.876543210987654e-19]
    case["data"]["sections"][0]["cpt"][:3] = [-0.0, TINY, -9.876543210987654e-19]
    tube = case["data"]["layers"][0]
    tube["values"][:3] = [-0.0, TINY, -9.876543210987654e-19]
    q = {"id": "synthetic-q", "name": "Procedural Q-like geometry; not CFD", "kind": "isosurface", "criterion": "Procedural repeated tube, not computed Q", "threshold": 1500,
         "positions": [], "indices": [], "visible": True, "opacity": .5}
    for repeat in range(20):
        offset = len(q["positions"]) // 3
        q["positions"].extend(v + repeat * .001 if i % 3 == 0 else v for i, v in enumerate(tube["positions"]))
        q["indices"].extend(v + offset for v in tube["indices"])
    case["data"]["layers"].append(q)
    return case


def differences(left, right, path="$"):
    if left == right:
        return []
    if isinstance(left, dict) and isinstance(right, dict):
        result = []
        for key in left.keys() | right.keys():
            result.extend(differences(left.get(key), right.get(key), path + "." + key))
            if len(result) >= 12:
                break
        return result[:12]
    if isinstance(left, list) and isinstance(right, list) and len(left) == len(right):
        result = []
        for i, (a, b) in enumerate(zip(left, right)):
            result.extend(differences(a, b, path + f"[{i}]"))
            if len(result) >= 12:
                break
        return result[:12]
    return [{"path": path, "left": left, "right": right}]


def same_project(left, right):
    """Scientific arrays stay exact; OrbitControls cameras allow roundoff."""
    if len(left["views"]) != len(right["views"]):
        return False
    for a, b in zip(left["views"], right["views"]):
        ca, cb = (v.get("state", {}).get("camera") for v in (a, b))
        if ca != cb:
            if not isinstance(ca, dict) or not isinstance(cb, dict) or ca.keys() != cb.keys():
                return False
            if any(len(ca[k]) != len(cb[k]) or any(not math.isclose(x, y, rel_tol=0, abs_tol=1e-9) for x, y in zip(ca[k], cb[k])) for k in ca):
                return False
    def without_view_cameras(project):
        return {**project, "views": [{**v, "state": {k: item for k, item in v["state"].items() if k != "camera"}} for v in project["views"]]}
    return without_view_cameras(left) == without_view_cameras(right)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    receipt = {"fixture": "Synthetic mathematical meshes only; no native STAR, real CFD or vehicle geometry", "checks": {}, "errors": [], "network": [], "metrics": {}}

    def check(name, passed):
        receipt["checks"][name] = bool(passed)
        if not passed:
            raise AssertionError(name)

    a, b = (synthetic_case(i) for i in (0, 1))
    initial_project = report.project_from_cases([a], "Synthetic compressed scientific arrays")
    incoming_project = report.project_from_cases([b], "Synthetic incoming compressed source")
    with patch.object(report, "_COMPRESSION_THRESHOLD_BYTES", 1):
        initial = report.build_report(initial_project, out / "python-compressed.html", overwrite=True)
    with patch.object(report, "_COMPRESSION_THRESHOLD_BYTES", LIMIT + 1):
        plain = report.build_report(initial_project, out / "legacy-plain.html", overwrite=True)
    initial_text, plain_text = initial.read_text(encoding="utf-8"), plain.read_text(encoding="utf-8")
    check("Python writer emits compressed scientific data", any(json.loads(m[2]).get("schema") == "cfd-review-compressed" for m in SLOT.finditer(initial_text)))
    check("Python compressed loader exactly restores source arrays including signed zero", report.load_report_document(initial) == initial_project and math.copysign(1, report.load_report_document(initial)["cases"][0]["data"]["parts"][0]["cp"][0]) < 0)
    # A compressed bundle manifest plus independently compressed case exercises
    # every supported slot rather than only the legacy whole-project slot.
    manifest = {"schema": "cfd-review-html-bundle", "version": 1, "project": {k: v for k, v in incoming_project.items() if k != "cases"},
                "cases": [{"id": b["id"], "elementId": "cfd-case-data-0"}]}
    incoming_text = SLOT.sub(lambda m: slot_script("cfd-project-data", compressed(manifest)) + slot_script("cfd-case-data-0", compressed(b)) if 'id="cfd-project-data"' in m[1] else "", plain_text)
    incoming = out / "compressed-bundle.html"
    incoming.write_text(incoming_text, encoding="utf-8")
    check("Python accepts compressed primary manifest and case slots", report.load_report_document(incoming) == incoming_project)
    receipt["metrics"].update(rawCaseBytes=[len(raw_json(c)) for c in (a, b)], plainHTMLBytes=plain.stat().st_size, pythonCompressedHTMLBytes=initial.stat().st_size)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, args=["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"])
        context = browser.new_context(offline=True, accept_downloads=True, viewport={"width": 1440, "height": 1000})

        def open_page(path, metric):
            page = context.new_page()
            page.on("pageerror", lambda error: receipt["errors"].append(str(error)))
            page.on("request", lambda request: receipt["network"].append(request.url) if request.url.startswith(("http:", "https:")) else None)
            started = time.perf_counter()
            page.goto(path.as_uri())
            page.wait_for_function("()=>window.CFDStudio")
            check(metric + " opens offline", page.evaluate("CFDStudio.ready"))
            receipt["metrics"][metric] = {"readyWallMs": round((time.perf_counter() - started) * 1000, 2), **page.evaluate("()=>({pageReadyMs:performance.now(),engine:CFDStudio.loadMetrics||null,dataDOMChars:[...document.querySelectorAll('[id=\"cfd-project-data\"],[id^=\"cfd-case-data-\"]')].reduce((n,s)=>n+s.textContent.length,0),heap:performance.memory?performance.memory.usedJSHeapSize:null})")}
            return page

        try:
            page = open_page(plain, "legacyPlain")
            check("legacy plain HTML remains supported with unchanged source values", page.evaluate("CFDStudio.project.cases[0]") == a)
            page.close()
            page = open_page(initial, "pythonCompressed")
            check("Python gzip reaches browser without source precision loss", page.evaluate("CFDStudio.project.cases[0]") == a and page.evaluate("()=>Object.is(CFDStudio.project.cases[0].data.parts[0].cp[0],-0)&&CFDStudio.project.cases[0].data.parts[0].cp[1]===1.2345678901234567e-27"))
            check("successful startup releases encoded and decoded data DOM text", page.evaluate("()=>[...document.querySelectorAll('[id=\"cfd-project-data\"],[id^=\"cfd-case-data-\"]')].every(n=>n.textContent.length===0)"))
            page.evaluate("window.__originals=JSON.stringify(CFDStudio.project.cases.map(c=>c.data))")
            page.evaluate("""async()=>{const v=CFDStudio.viewers[0];await v.setState({...v.getState(),mirrorDisplay:true});await v.setColorRange('surface',-1.25,.6);CFDStudio.addNote('Synthetic source mirror and colors');}""")
            page.locator('[data-control="import-file"]').set_input_files(incoming)
            page.wait_for_function("()=>CFDStudio.project.cases.length===2&&CFDStudio.project.views.length===2&&CFDStudio.viewers.every(v=>v.renderer)")
            page.evaluate("Promise.all(CFDStudio.viewers.map(v=>v.ready))")
            check("compressed bundle import keeps both exact source arrays and mirrored state", page.evaluate("CFDStudio.project.cases[1]") == b and page.evaluate("()=>__originals===JSON.stringify([CFDStudio.project.cases[0].data])&&CFDStudio.viewers[0].getState().mirrorDisplay&&CFDStudio.viewers[0].colorRanges.surfaceCp[0]===-1.25"))
            page.evaluate("CFDStudio.stitchHalfCases('synthetic-a','synthetic-b')")
            check("compressed sources stitch with both Q-like meshes and tiny scalars", page.evaluate("""()=>{const c=CFDStudio.project.cases.find(c=>c.data.meta.comparison),a=CFDStudio.project.cases[0];return c.data.layers.filter(l=>l.sourceLayerId==='synthetic-q').length===2&&c.data.parts[0].cp[1]===a.data.parts[0].cp[1]&&c.data.parts[0].cp[1]===1.2345678901234567e-27&&CFDStudio.viewers[0].layerMeshes.length===4;}"""))
            page.evaluate("""async()=>{const v=CFDStudio.viewers[0];await v.setColorRange('section',-.7,1.1,'CpT');CFDStudio.addNote('Synthetic stitched evidence');await CFDStudio.setLink('color',false);}""")
            saved = page.evaluate("CFDStudio.exportProject()")
            with page.expect_download() as download:
                page.evaluate("CFDStudio.downloadHTML()")
            portable = out / "browser-compressed-portable.html"
            download.value.save_as(portable)
            loaded = report.load_report_document(portable)
            if not same_project(loaded, saved):
                receipt["roundtripDifferences"] = differences(loaded, saved)
            check("browser gzip and recipe preserve exact arrays and scientific state in Python", same_project(loaded, saved))
            stored = [json.loads(m[2]) for m in SLOT.finditer(portable.read_text(encoding="utf-8"))]
            check("browser saves large source cases compressed and derived geometry once by recipe", sum(v.get("schema") == "cfd-review-compressed" for v in stored) >= 2 and any(v.get("schema") == "cfd-review-composition" for v in stored))
            receipt["metrics"]["browserCompressedHTMLBytes"] = portable.stat().st_size
            page.close()
            page = open_page(portable, "browserCompressedReopened")
            check("reopened compressed report restores arrays, notes, colors and recipe", same_project(page.evaluate("CFDStudio.exportProject()"), saved))
            page.evaluate("CFDStudio.restoreNote(CFDStudio.project.notes[0].id)")
            check("source note restores mirror display and scalar color limits", page.evaluate("()=>CFDStudio.viewers[0].getState().mirrorDisplay&&CFDStudio.viewers[0].colorRanges.surfaceCp[0]===-1.25"))
            check("reopened compressed data DOM remains released", page.evaluate("()=>[...document.querySelectorAll('[id=\"cfd-project-data\"],[id^=\"cfd-case-data-\"]')].every(n=>n.textContent.length===0)"))

            base = compressed(incoming_project)
            packed = b"".join(base64.b64decode(chunk) for chunk in base["chunks"])
            damaged = bytearray(packed)
            damaged[-8] ^= 1
            cases = {
                "corrupt gzip": {**base, "chunks": [base64.b64encode(damaged).decode("ascii")]},
                "truncated gzip": {**base, "chunks": [base64.b64encode(packed[:-8]).decode("ascii")]},
                "unknown encoding": {**base, "encoding": "deflate-base64"},
                "wrong decoded count": {**base, "decodedBytes": base["decodedBytes"] - 1},
                "invalid base64": {**base, "chunks": ["!!!!"]},
                "oversize declaration": {**base, "decodedBytes": LIMIT + 1},
                "oversize base64 chunk": {**base, "chunks": ["A" * (1024 * 1024 + 1)]},
                "unknown envelope key": {**base, "extra": True},
                "nested compression": compressed(base),
                "decoded-byte amplification": {**compressed(None, raw=b" " * (2 * 1024 * 1024)), "decodedBytes": 128},
            }
            for label, envelope in cases.items():
                result = page.evaluate("""async envelope=>{const old=CFDStudio.project,n=old.cases.length,notes=JSON.stringify(old.notes),state=CFDStudio.viewers[0].getState();
                 const raw='<script id="cfd-project-data" type="application/json">'+JSON.stringify(envelope)+'<'+ '/script>',native=DecompressionStream;let rejected=false,calls=0;
                 window.DecompressionStream=new Proxy(native,{construct(target,args){calls++;return Reflect.construct(target,args);}});
                 try{await CFDStudio.importFile(new File([raw],'invalid-compressed.html',{type:'text/html'}));}catch(e){rejected=true;}finally{window.DecompressionStream=native;}
                 const after=CFDStudio.viewers[0].getState(),camera=['position','target'].every(k=>after.camera[k].every((x,i)=>Math.abs(x-state.camera[k][i])<1e-9));delete after.camera;delete state.camera;
                 return {unchanged:rejected&&CFDStudio.project===old&&old.cases.length===n&&JSON.stringify(old.notes)===notes&&camera&&JSON.stringify(after)===JSON.stringify(state),calls};
                }""", envelope)
                receipt.setdefault("rejectedPayloads", {})[label] = result
                reject_before_decode = label in {"unknown encoding", "invalid base64", "oversize declaration", "oversize base64 chunk", "unknown envelope key"}
                check(label + " rejected without changing live project", result["unchanged"] and (not reject_before_decode or result["calls"] == 0))
            check("no uncaught JavaScript errors", not receipt["errors"])
            check("no network requests", not receipt["network"])
            receipt["passed"] = True
        except Exception:
            receipt["passed"] = False
            receipt["exception"] = traceback.format_exc()
        finally:
            context.close()
            browser.close()
    path = out / "compressed-report-checks.json"
    path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"passed": receipt["passed"], "checks": len(receipt["checks"]), "receipt": str(path)}, ensure_ascii=False))
    if not receipt["passed"]:
        print(receipt.get("exception", ""))
    return 0 if receipt["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
