"""Synthetic browser regression for low-copy stitching and portable recipes.

Requires the optional Playwright development dependency. No STAR or real CFD
files are opened; array identity checks target the allocation regression rather
than pretending this small fixture establishes a machine's memory capacity.
"""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
import sys
import traceback

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from cfd_review.demo import make_demo_case
from cfd_review.report import build_report, project_from_cases


CLONE_GUARD = """()=>{
 const native=window.structuredClone;
 window.__cloneStats={dense:0,small:0,blocked:0,allow:false};
 const dense=v=>{
  if(!v||typeof v!=='object')return false;
  if(Array.isArray(v.positions)&&Array.isArray(v.indices))return true;
  if(Array.isArray(v))return v.length>256&&v.every(x=>typeof x==='number')||v.some(dense);
  return Object.values(v).some(dense);
 };
 window.structuredClone=function(v,...rest){const s=window.__cloneStats;
  if(dense(v)){s.dense++;if(!s.allow){s.blocked++;throw Error('TEST: dense scientific clone');}}
  else s.small++;return native.call(this,v,...rest);
 };
 window.__arrays=()=>JSON.stringify(CFDStudio.project.cases.filter(c=>!c.data.meta.comparison).map(c=>{
  const out={id:c.id};for(const k of ['parts','sections','layers'])out[k]=c.data[k].map(m=>Object.fromEntries(
   ['positions','indices','cp','cpt','values'].filter(f=>f in m).map(f=>[f,m[f]])));return out;}));
}"""

SNAPSHOT = """()=>{
 const p=CFDStudio.project;
 return {title:p.title,notes:p.notes,links:p.links,ui:p.ui,
  cases:p.cases.map(c=>[c.id,c.name,c.data.meta]),views:p.views.map((v,i)=>({caseId:v.caseId,state:CFDStudio.viewers[i].getState()})),
  controls:{title:document.querySelector('[data-control="project-title"]').value,
   links:['camera','section','field','color'].map(k=>document.querySelector('[data-control="link-'+k+'"]').checked),
   sidebar:document.querySelector('.studio-workspace').dataset.sidebarCollapsed,
   names:[...document.querySelectorAll('[data-control="case-name"]')].map(n=>n.value),
   selected:[...document.querySelectorAll('[data-control="case"]')].map(n=>n.value),
   halves:[...document.querySelectorAll('[data-half-declaration]')].map(n=>[n.dataset.halfDeclaration,n.checked,n.disabled])}};
}"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    receipt = {"fixture": "Synthetic mathematical data only; no native STAR or real CFD validation", "checks": {}, "errors": [], "network": []}

    def check(label, passed):
        receipt["checks"][label] = bool(passed)
        if not passed:
            raise AssertionError(label)

    cases = [make_demo_case(i) for i in (0, 1)]
    cases[1]["name"] += " · </script><script>window.__untrusted=1</script> \u2028 \u2029"
    for case in cases:
        q = copy.deepcopy(case["data"]["layers"][0])
        q.update(id="synthetic-q-geometry", name="Synthetic Q-like geometry", criterion="Procedural tube; not computed Q", threshold=1500)
        for key in ("values", "field", "units", "colorRange"):
            q.pop(key, None)
        case["data"]["layers"].append(q)
        case["data"]["meta"]["scalarMirror"] = False
    cases[0]["data"]["meta"]["halfCar"] = False
    cases[0]["data"]["meta"].pop("mirrorAxis")
    initial = build_report(project_from_cases([cases[0]], "Synthetic low-copy regression"), out / "initial.html", overwrite=True)
    incoming = build_report(project_from_cases([cases[1]], "Synthetic HTML import"), out / "incoming.html", overwrite=True)
    json_case = copy.deepcopy(cases[1])
    json_case.update(id="synthetic-json", name="Synthetic JSON import")
    json_case["data"]["meta"]["sourceKey"] = "synthetic-json-v1"
    (out / "incoming.case.json").write_text(json.dumps(json_case), encoding="utf-8")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, args=["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"])
        context = browser.new_context(offline=True, accept_downloads=True, viewport={"width": 1440, "height": 1000})

        def open_page(path):
            page = context.new_page()
            page.on("pageerror", lambda error: receipt["errors"].append(str(error)))
            page.on("request", lambda request: receipt["network"].append(request.url) if request.url.startswith(("http:", "https:")) else None)
            page.goto(path.as_uri())
            page.wait_for_function("()=>window.CFDStudio")
            check("opened " + path.name, page.evaluate("CFDStudio.ready"))
            return page

        try:
            page = open_page(initial)
            page.evaluate(CLONE_GUARD)
            page.evaluate("window.__initialArray=CFDStudio.project.cases[0].data.parts[0].cp")
            page.evaluate("CFDStudio.declareHalfCar('synthetic-a',true)")
            page.locator('[data-control="import-file"]').set_input_files(incoming)
            page.wait_for_function("()=>CFDStudio.project.cases.length===2&&CFDStudio.viewers.length===2&&CFDStudio.viewers.every(v=>v.renderer)")
            page.evaluate("Promise.all(CFDStudio.viewers.map(v=>v.ready))")
            check("HTML import shares retained scientific arrays without cloning", page.evaluate("()=>CFDStudio.project.cases[0].data.parts[0].cp===window.__initialArray&&__cloneStats.dense===0"))
            page.locator('[data-control="import-file"]').set_input_files(out / "incoming.case.json")
            page.wait_for_function("()=>CFDStudio.project.cases.length===3&&CFDStudio.project.views[1].caseId==='synthetic-json'")
            check("case JSON import avoids scientific clones", page.evaluate("__cloneStats.dense===0"))
            page.evaluate("window.__beforeArrays=__arrays()")

            check("public export and compose retain deep isolation", page.evaluate("""()=>{
             __cloneStats.allow=true;try{const p=CFDStudio.exportProject(),[a,b]=CFDStudio.project.cases;
              p.cases[0].data.parts[0].cp[0]+=99;p.cases[0].data.meta.title='external mutation';p.links.camera=false;
              const c=CFDStudio.composeHalfComparison(a,b);c.data.parts[0].cp[0]+=99;c.data.layers[0].positions[0]+=99;
              return __beforeArrays===__arrays()&&a.data.meta.title!=='external mutation'&&CFDStudio.project.links.camera;
             }finally{__cloneStats.allow=false;}
            }"""))
            check("public project import isolates caller-owned arrays and metadata", page.evaluate("""async()=>{
             __cloneStats.allow=true;try{const p=CFDStudio.exportProject();await CFDStudio.importProject(p);
              p.cases[0].data.parts[0].cp[0]+=50;p.cases[0].name='external renamed';p.notes.push({text:'external'});
              return __arrays()===__beforeArrays&&CFDStudio.project.cases[0].name!=='external renamed'&&CFDStudio.project.notes.length===0;
             }finally{__cloneStats.allow=false;}
            }"""))
            page.evaluate("__cloneStats.dense=0;window.__retained=CFDStudio.project.cases[0].data.parts[0].cp")
            derived_id = page.evaluate("CFDStudio.stitchHalfCases('synthetic-a','synthetic-b')")
            check("internal stitch never deep-clones scientific data", page.evaluate("__cloneStats.dense===0&&__cloneStats.blocked===0"))
            check("derived meshes share scalar arrays and unreflected coordinates only", page.evaluate("""()=>{
             const [a,b]=CFDStudio.project.cases,d=CFDStudio.project.cases.find(c=>c.data.meta.comparison),l=d.data.parts.filter(m=>m.sourceSide==='A'),r=d.data.parts.filter(m=>m.sourceSide==='B');
             return l[0].cp===a.data.parts[0].cp&&a.data.parts[0].cp===__retained&&r[0].cp===b.data.parts[0].cp&&
              l[0].positions!==a.data.parts[0].positions&&l[0].indices!==a.data.parts[0].indices&&r[0].positions===b.data.parts[0].positions&&r[0].indices===b.data.parts[0].indices&&
              l[0]!==a.data.parts[0]&&r[0]!==b.data.parts[0]&&d.data.meta!==a.data.meta;
            }"""))
            check("reflection preserves exact scalars, winding, all Q-like layers and source arrays", page.evaluate("""()=>{
             const [a,b]=CFDStudio.project.cases,d=CFDStudio.project.cases.find(c=>c.data.meta.comparison),p=d.data.parts[0],s=a.data.parts[0];
             return __arrays()===__beforeArrays&&p.positions.every((v,i)=>v===(i%3===1?-s.positions[i]:s.positions[i]))&&
              p.indices.every((v,i)=>v===s.indices[i%3===1?i+1:i%3===2?i-1:i])&&
              d.data.layers.length===4&&d.data.layers.filter(l=>l.sourceLayerId==='synthetic-q-geometry').every(l=>!('values'in l)&&l.threshold===1500)&&
              CFDStudio.viewers[0].layerMeshes.length===4;
            }"""))
            check("repeat stitch reuses existing derived arrays", page.evaluate("""async()=>{
             const d=CFDStudio.project.cases.find(c=>c.data.meta.comparison),positions=d.data.parts[0].positions,n=CFDStudio.project.cases.length;
             const id=await CFDStudio.stitchHalfCases('synthetic-a','synthetic-b');return id===d.id&&CFDStudio.project.cases.length===n&&CFDStudio.project.cases.find(c=>c.id===id).data.parts[0].positions===positions&&__cloneStats.dense===0;
            }"""))

            page.evaluate("""async()=>{const v=CFDStudio.viewers[0];v.controls.enableDamping=false;v._fit('top');await v.setColorRange('surface',-1.25,.6);CFDStudio.addNote('Synthetic retained evidence');await CFDStudio.setLink('camera',false);}""")
            page.locator('[data-action="toggle-sidebar"]').click()
            before = page.evaluate(SNAPSHOT)
            rollback = page.evaluate("""async()=>{
             const original=DefenseFieldViewer.mount;let calls=0;DefenseFieldViewer.mount=function(...args){if(calls++===0)throw Error('Synthetic forced mount failure');return original.apply(this,args);};
             try{await CFDStudio.stitchHalfCases('synthetic-b','synthetic-a');return false;}
             catch(e){return e.message.includes('Synthetic forced mount failure');}
             finally{DefenseFieldViewer.mount=original;}
            }""")
            check("failed renderer transaction restores project, notes, declaration, controls and camera", rollback and page.evaluate(SNAPSHOT) == before)
            check("rollback retains original arrays without scientific clones", page.evaluate("__arrays()===__beforeArrays&&__cloneStats.dense===0&&__cloneStats.blocked===0"))

            page.evaluate("window.__canonical=JSON.stringify(CFDStudio.project.cases.find(c=>c.data.meta.comparison))")
            page.evaluate("""()=>{
             const native=JSON.stringify;window.__serialization={wholeScientific:0,largeArray:0};
             const containsMesh=v=>!!v&&typeof v==='object'&&(Array.isArray(v.positions)&&Array.isArray(v.indices)||
              (Array.isArray(v)?v.some(x=>typeof x==='object'&&containsMesh(x)):Object.values(v).some(containsMesh)));
             JSON.stringify=function(v,...rest){if(containsMesh(v)){__serialization.wholeScientific++;throw Error('TEST: whole scientific JSON string');}
              if(Array.isArray(v)&&v.length>8192){__serialization.largeArray++;throw Error('TEST: unbounded numeric JSON string');}
              return native.call(this,v,...rest);};window.__restoreStringify=()=>{JSON.stringify=native;};
            }""")
            with page.expect_download() as download:
                page.evaluate("CFDStudio.downloadHTML()")
            portable = out / "portable-comparison.html"
            download.value.save_as(portable)
            raw = portable.read_text(encoding="utf-8")
            check("HTML stores compact composition recipe without duplicate derived arrays", '"schema":"cfd-review-composition"' in raw and raw.count('"schema":"cfd-review-case"') == 3)
            check("saving uses bounded numeric serialization without structured clones", page.evaluate("__cloneStats.dense===0&&__cloneStats.blocked===0"))
            check("saving never stringifies a complete scientific case or unbounded numeric array", page.evaluate("__serialization.wholeScientific===0&&__serialization.largeArray===0"))
            page.evaluate("__restoreStringify()")
            expected = page.evaluate("JSON.parse(window.__canonical)")
            expected_state = page.evaluate(SNAPSHOT)
            page.close()
            page = open_page(portable)
            check("embedded scientific text escapes HTML and Unicode line separators safely", page.evaluate("typeof window.__untrusted==='undefined'") and "</script><script>window.__untrusted=1</script>" not in raw)
            check("portable recipe reconstructs exact geometry, scalars and provenance", page.evaluate("CFDStudio.project.cases.find(c=>c.data.meta.comparison)") == expected)
            check("portable recipe restores notes, declaration, links and selected view", page.evaluate(SNAPSHOT) == expected_state)
            page.evaluate(CLONE_GUARD)

            check("invalid recipes are rejected without replacing the live project", page.evaluate("""async()=>{
             const before=JSON.stringify(CFDStudio.project),native=structuredClone;__cloneStats.allow=true;
             const p=CFDStudio.exportProject();__cloneStats.allow=false;const d=p.cases.find(c=>c.data.meta.comparison),recipe={schema:'cfd-review-composition',version:1,id:d.id,name:d.name,meta:d.data.meta};
             const changes=[r=>r.meta.comparison.sources[0].sourceId='forged',r=>r.meta.comparison.sources[0].caseId='missing',r=>r.meta.comparison.sources[0].caseId=r.id,r=>r.meta.comparison.sources[1]=r.meta.comparison.sources[0],r=>r.id='wrong-derived-id',r=>r.extra=true];let count=0;
             for(const change of changes){__cloneStats.allow=true;const r=native(recipe);__cloneStats.allow=false;change(r);
              const cases=p.cases.filter(c=>!c.data.meta.comparison),manifest={schema:'cfd-review-html-bundle',version:1,project:Object.fromEntries(Object.entries(p).filter(([k])=>k!=='cases')),cases:[...cases,r].map((c,i)=>({id:c.id,elementId:'cfd-case-data-'+i}))};
              const script=(id,data)=>'<script id="'+id+'" type="application/json">'+JSON.stringify(data)+'<'+ '/script>',html=script('cfd-project-data',manifest)+[...cases,r].map((c,i)=>script('cfd-case-data-'+i,c)).join('');
              try{await CFDStudio.importFile(new File([html],'invalid.html',{type:'text/html'}));}catch(e){count++;}
             }
             return count===changes.length&&JSON.stringify(CFDStudio.project)===before&&__cloneStats.blocked===0;
            }"""))
            check("no external requests", not receipt["network"])
            check("no uncaught browser errors", not receipt["errors"])
            receipt["passed"] = True
        except Exception:
            receipt["passed"] = False
            receipt["exception"] = traceback.format_exc()
        finally:
            context.close()
            browser.close()
    path = out / "stitch-memory-checks.json"
    path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"passed": receipt["passed"], "checks": len(receipt["checks"]), "receipt": str(path)}, ensure_ascii=False))
    if not receipt["passed"]:
        print(receipt.get("exception", ""))
    return 0 if receipt["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
