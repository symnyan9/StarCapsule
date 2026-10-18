"""Bounded desktop layout and data-only HTML comparison checks (synthetic only)."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import traceback

from playwright.sync_api import sync_playwright


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--html", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    receipt = {"fixture": "Explicit synthetic DEMO only; no native STAR process", "checks": {}, "errors": [], "network": []}

    def check(label, passed):
        receipt["checks"][label] = bool(passed)
        if not passed:
            raise AssertionError(label)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, args=["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"])
        context = browser.new_context(viewport={"width": 1440, "height": 900}, offline=True, accept_downloads=True)

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
            check("file picker accepts offline HTML and JSON", ".html" in page.locator('[data-control="import-file"]').get_attribute("accept"))
            for width, height in [(1440, 900), (1920, 1080)]:
                page.set_viewport_size({"width": width, "height": height})
                for count in (1, 2):
                    page.locator(f'[data-action="layout-{ "single" if count == 1 else "compare" }"]').click()
                    page.wait_for_function("n=>CFDStudio.viewers.length===n&&CFDStudio.viewers.every(v=>v.renderer)", arg=count)
                    page.wait_for_timeout(100)
                    bounds = page.evaluate("""()=>({overflow:document.documentElement.scrollWidth>innerWidth+1,statusTop:document.querySelector('.studio-main-status').getBoundingClientRect().top,statusBottom:document.querySelector('.studio-main-status').getBoundingClientRect().bottom,views:[...document.querySelectorAll('.studio-view')].map(panel=>{
                     const stage=panel.querySelector('.fv-stage').getBoundingClientRect(),settings=panel.querySelector('.fv-settings'),r=settings.getBoundingClientRect(),head=panel.querySelector('.fv-header');
                     return {top:stage.top,height:stage.height,bottom:stage.bottom,settingsBottom:r.bottom,independent:getComputedStyle(settings).overflowY==='auto'&&settings.scrollHeight>settings.clientHeight,duplicateHidden:getComputedStyle(head).display==='none',panel:panel.getBoundingClientRect().width,canvas:stage.width};})})""")
                    receipt.setdefault("layoutBounds", {})[f"{width}x{height}-{count}"] = bounds
                    # The creator credit shares the viewer's status row. Check
                    # actual row boundaries rather than reserving an obsolete
                    # fixed 30 px footer (the compact status now uses 28 px).
                    check(f"{width}x{height} {count} viewport core starts near top and fills remaining height", not bounds["overflow"] and bounds["statusBottom"] <= height + 1 and all(v["top"] < 250 and v["height"] > height * .48 and v["bottom"] <= bounds["statusTop"] + 1 and v["settingsBottom"] <= bounds["statusTop"] + 1 and v["independent"] and v["duplicateHidden"] and v["canvas"] > 290 for v in bounds["views"]))

            check("overview omits triangle counts while retaining source mesh arrays", page.evaluate("()=>!document.querySelector('[data-role=project-summary]').textContent.includes('三角')&&CFDStudio.project.cases.every(c=>c.data.parts[0].indices.length>0)"))
            check("sidebar is narrow and leaves room for scientific canvases", page.evaluate("()=>document.querySelector('.studio-sidebar').getBoundingClientRect().width<=185"))

            # Simulate a second exporter file with deliberately untrusted outer markup.
            # Only its embedded project data may enter the existing editor.
            result = page.evaluate("""async()=>{
             const original=CFDStudio.project.cases[0],c=JSON.parse(JSON.stringify(original));c.id='html-import-source';c.name='Imported synthetic half';c.data.meta.title=c.name;c.data.meta.sourceKey='synthetic-html-import';c.data.meta.halfCar=false;c.data.meta.scalarMirror=false;
             c.data.sections=c.data.sections.filter((_,i)=>i%2===0);
             const p={schema:'cfd-review-project',version:1,title:'Incoming report',cases:[c],views:[{caseId:c.id,state:null}],links:{camera:true,section:true,field:true,color:true},notes:[]};
             window.__htmlFixture=p;window.__beforeCount=CFDStudio.project.cases.length;
             const raw='<html><img src="https://invalid.example/never-load"><script>window.__foreignExecuted=true;fetch("https://invalid.example/never-run")<'+ '/script><script id="cfd-project-data" type="application/json">'+JSON.stringify(p).replace(/</g,'\\u003c')+'<'+ '/script><style>body{display:none}</style></html>';
             await CFDStudio.importFile(new File([raw],'second-review.html',{type:'text/html'}));
             const out=CFDStudio.project.cases.find(x=>x.id===c.id);
             return CFDStudio.project.cases.length===window.__beforeCount+1&&CFDStudio.project.views[1].caseId===c.id&&JSON.stringify(out.data)===JSON.stringify(c.data)&&!window.__foreignExecuted&&getComputedStyle(document.body).display!=='none';
            }""")
            check("HTML import adds source arrays and A/B view without executing foreign page content", result)
            check("half-car action explains missing symmetry declaration", page.evaluate("""()=>{const p=CFDStudio.exportProject();for(const c of p.cases)if(c.id!==p.views[0].caseId){c.data.meta.halfCar=false;c.data.meta.scalarMirror=false;}return CFDStudio.importProject(p).then(()=>document.querySelector('[data-action="stitch-half"]').disabled&&document.querySelector('[data-role="stitch-status"]').textContent.includes('对称半模型'));}"""))
            check("unequal cut counts support ordinary physical-X linked views", page.evaluate("""async()=>{const [a,b]=CFDStudio.viewers;await CFDStudio.setLink('section',true);await a.setSection(2);await new Promise(r=>setTimeout(r,80));const x=a.sections[a.sectionIndex].x,expected=b.sections.reduce((best,s,i)=>Math.abs(s.x-x)<Math.abs(b.sections[best].x-x)?i:best,0);return a.sections.length!==b.sections.length&&b.sectionIndex===expected;}"""))
            page.evaluate("""async()=>{const v=CFDStudio.viewers[1];await v.setState({...v.getState(),cptTransparentAbove:1.01});CFDStudio.addNote('Synthetic declaration preserves note',1);window.__beforeDeclaration=v.getState();window.__rawImported=JSON.stringify(CFDStudio.project.cases.find(c=>c.id==='html-import-source').data.parts);}""")
            page.locator('[data-half-declaration="html-import-source"]').check()
            page.wait_for_function("()=>CFDStudio.project.cases.find(c=>c.id==='html-import-source').data.meta.halfCar&&CFDStudio.viewers.every(v=>v.renderer)&&CFDStudio.viewers[1].cptTransparentAbove===1.01")
            proof = page.evaluate("""()=>{const c=CFDStudio.project.cases.find(c=>c.id==='html-import-source'),s=CFDStudio.viewers[1].getState();return {original:c.data.meta.symmetryDeclaration.original.halfCar===false,axis:c.data.meta.mirrorAxis==='y',mirror:c.data.meta.scalarMirror===false,parts:JSON.stringify(c.data.parts)===window.__rawImported,camera:['position','target'].every(k=>s.camera[k].every((v,i)=>Math.abs(v-window.__beforeDeclaration.camera[k][i])<1e-9)),threshold:s.cptTransparentAbove===1.01,notes:CFDStudio.project.notes.length>0,before:window.__beforeDeclaration.camera,after:s.camera};}""")
            receipt['declarationProof'] = proof
            check("explicit half declaration validates one-sided geometry and preserves scientific values and view state", all(proof[k] for k in ['original','axis','mirror','parts','camera','threshold','notes']))
            page.locator('[data-half-declaration="html-import-source"]').uncheck()
            page.wait_for_function("()=>!CFDStudio.project.cases.find(c=>c.id==='html-import-source').data.meta.halfCar&&CFDStudio.viewers.every(v=>v.renderer)&&CFDStudio.viewers[1].cptTransparentAbove===1.01")
            check("declaration can restore original symmetry metadata before composition", page.evaluate("""()=>{const c=CFDStudio.project.cases.find(c=>c.id==='html-import-source');return !('symmetryDeclaration'in c.data.meta)&&JSON.stringify(c.data.parts)===window.__rawImported&&CFDStudio.viewers[1].getState().cptTransparentAbove===1.01;}"""))
            check("crossing Y=0 geometry is rejected before recording confirmation", page.evaluate("""async()=>{const c=CFDStudio.project.cases.find(c=>c.id==='html-import-source'),p=c.data.parts[0].positions,old=p[1];p[1]=-5;try{await CFDStudio.declareHalfCar(c.id,true);return false;}catch(e){return !c.data.meta.halfCar&&e.message.includes('跨越');}finally{p[1]=old;}}"""))
            page.locator('[data-half-declaration="html-import-source"]').check()
            page.wait_for_function("()=>CFDStudio.project.cases.find(c=>c.id==='html-import-source').data.meta.halfCar&&CFDStudio.viewers.every(v=>v.renderer)&&CFDStudio.viewers[1].cptTransparentAbove===1.01")
            page.locator('[data-control="stitch-b"]').select_option("html-import-source")
            page.locator('[data-action="stitch-half"]').click()
            page.wait_for_function("()=>CFDStudio.viewers.length===1&&CFDStudio.viewers[0].meta.comparison&&CFDStudio.viewers[0].renderer")
            check("active composition disables declaration undo to retain derived views and notes", page.locator('[data-half-declaration="html-import-source"]').is_disabled() and page.evaluate("""async()=>{try{await CFDStudio.declareHalfCar('html-import-source',false);return false;}catch(e){return e.message.includes('拼接')&&CFDStudio.project.cases.find(c=>c.id==='html-import-source').data.meta.halfCar;}}"""))
            check("half composition uses actual common coordinates, not equal cut counts", page.evaluate("""()=>{const v=CFDStudio.viewers[0],[a,b]=v.meta.comparison.sources.map(s=>CFDStudio.project.cases.find(c=>c.id===s.caseId));return a.data.sections.length!==b.data.sections.length&&v.sections.every(s=>a.data.sections.some(x=>x.x===s.x)&&b.data.sections.some(x=>x.x===s.x));}"""))
            check("HTML importer rejects duplicate data scripts and non-JSON engine payload", page.evaluate("""async()=>{for(const raw of ['<script id="cfd-project-data" type="application/json">{}<'+ '/script><script id="cfd-project-data" type="application/json">{}<'+ '/script>','<script id="cfd-project-data" type="text/javascript">{}<'+ '/script>']){try{await CFDStudio.importFile(new File([raw],'bad.htm'));return false;}catch(e){if(!e.message.includes('HTML'))return false;}}return true;}"""))
            check("threshold state and metadata reject nonfinite values", page.evaluate("""()=>{const c=CFDStudio.project.cases[0],s=CFDStudio.viewers[0].getState();for(const value of [NaN,Infinity,'1']){try{CFDStudio.validateState({...s,sourceId:c.data.meta.sourceSha256||c.data.meta.sourceKey,cptTransparentAbove:value},c);return false;}catch(e){}const bad={...c,data:{...c.data,meta:{...c.data.meta,cptTransparentAbove:value}}};try{CFDStudio.validateCase(bad);return false;}catch(e){}}return true;}"""))
            check("streaming HTML import handles split tags and UTF-8 without whole-file text", page.evaluate("""async()=>{
             const p=JSON.parse(JSON.stringify(window.__htmlFixture));p.cases[0].name='流场对照 α';const raw=' '.repeat(65530)+'<script id="cfd-project-data" type="application/json">'+JSON.stringify(p)+'<'+ '/script>',bytes=new TextEncoder().encode(raw);
             const file={name:'streamed.htm',type:'text/html',size:bytes.length,text(){throw Error('whole-file text must not be called');},stream(){return new ReadableStream({start(c){for(let i=0;i<bytes.length;i+=997)c.enqueue(bytes.slice(i,i+997));c.close();}});}};
             try{await CFDStudio.importFile(file);return false;}catch(e){return e.message.includes('已在工程中');}
            }"""))
            check("bundle import rejects missing, mismatched or unreferenced case slots", page.evaluate("""async()=>{
             const c=window.__htmlFixture.cases[0],base={schema:'cfd-review-html-bundle',version:1,project:{...window.__htmlFixture},cases:[{id:c.id,elementId:'cfd-case-data-0'}]};delete base.project.cases;
             for(const [manifest,tail] of [[base,''],[{...base,cases:[{id:'wrong',elementId:'cfd-case-data-0'}]},'<script id="cfd-case-data-0" type="application/json">'+JSON.stringify(c)+'<'+ '/script>'],[base,'<script id="cfd-case-data-0" type="application/json">'+JSON.stringify(c)+'<'+ '/script><script id="cfd-case-data-1" type="application/json">'+JSON.stringify(c)+'<'+ '/script>']]){
              const raw='<script id="cfd-project-data" type="application/json">'+JSON.stringify(manifest)+'<'+ '/script>'+tail;try{await CFDStudio.importFile(new File([raw],'bad-bundle.html'));return false;}catch(e){if(!e.message.includes('HTML'))return false;}
             }return true;
            }"""))
            check("oversize HTML and JSON fail before reading or allocating data", page.evaluate("""async()=>{for(const [name,size] of [['huge.html',2*1024**3+1],['huge.json',500*1024**2+1]]){try{await CFDStudio.importFile({name,size,text(){throw Error('read unexpectedly');},stream(){throw Error('read unexpectedly');}});return false;}catch(e){if(!/上限/.test(e.message))return false;}}return true;}"""))
            page.evaluate("window.__beforeCollapse=CFDStudio.viewers[0].getState();window.__beforeCollapseWidth=CFDStudio.viewers[0].el('stage').getBoundingClientRect().width")
            toggle = page.locator('[data-action="toggle-sidebar"]')
            toggle.focus()
            toggle.press("Enter")
            page.wait_for_function("()=>CFDStudio.project.ui?.sidebarCollapsed&&document.querySelector('.studio-sidebar').getBoundingClientRect().width===36")
            check("keyboard sidebar collapse preserves camera threshold source choice and notes", page.evaluate("""()=>{const v=CFDStudio.viewers[0],s=v.getState(),old=window.__beforeCollapse;return v.el('stage').getBoundingClientRect().width>window.__beforeCollapseWidth+100&&document.querySelector('[data-action="toggle-sidebar"]').getAttribute('aria-expanded')==='false'&&['position','target'].every(k=>s.camera[k].every((x,i)=>Math.abs(x-old.camera[k][i])<1e-9))&&s.cptTransparentAbove===old.cptTransparentAbove&&s.sourceId===old.sourceId&&CFDStudio.project.notes.length>0;}"""))
            with page.expect_download() as download:
                page.evaluate("CFDStudio.downloadHTML()")
            portable = args.output / "portable-layout-import.html"
            download.value.save_as(portable)
            page.locator('[data-control="import-file"]').set_input_files(portable)
            page.wait_for_function("()=>document.querySelector('#studio-message').textContent.includes('已在工程中')")
            check("streaming importer reads its own multi-case bundle without replacing current sources", page.evaluate("()=>CFDStudio.project.cases.length===4&&CFDStudio.project.views.length===1"))
            other = open_page(portable)
            check("saved HTML restores all three sources plus composition and one fixed credit offline", other.evaluate("""()=>CFDStudio.viewers.length===1&&CFDStudio.viewers[0].meta.comparison&&CFDStudio.project.cases.length===4&&CFDStudio.project.cases.some(c=>c.data.meta.symmetryDeclaration)&&document.querySelectorAll('#cfd-creator-credit').length===1"""))
            check("HTML bundle restores collapsed sidebar preference", other.evaluate("()=>CFDStudio.project.ui.sidebarCollapsed===true&&document.querySelector('[data-action=toggle-sidebar]').getAttribute('aria-expanded')==='false'&&document.querySelector('.studio-sidebar').getBoundingClientRect().width===36"))
            other.locator('[data-action="toggle-sidebar"]').click()
            check("expanding sidebar restores case library and annotation actions", other.locator('.studio-case-section').is_visible() and other.locator('[data-action="add-note"]').is_visible())
            other.locator('[data-action="layout-compare"]').click()
            other.wait_for_function("()=>CFDStudio.viewers.length===2&&CFDStudio.viewers.every(v=>v.renderer)")
            other.locator('.studio-view[data-view="0"] [data-control="case"]').select_option("html-import-source")
            other.wait_for_function("()=>CFDStudio.project.views[0].caseId==='html-import-source'&&CFDStudio.viewers.every(v=>v.renderer)")
            check("reopened project can freely select third source in A/B", other.evaluate("()=>CFDStudio.project.cases.length===4&&CFDStudio.project.views[0].caseId==='html-import-source'&&CFDStudio.project.views[1].caseId==='html-import-source'"))
            check("no JavaScript errors", not receipt["errors"])
            check("no external requests including imported foreign markup", not receipt["network"])
        except Exception:
            receipt["failure"] = traceback.format_exc()
            raise
        finally:
            browser.close()
            (args.output / "layout-import-checks.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"checks": len(receipt["checks"]), "passed": sum(receipt["checks"].values()), "output": str(args.output)}))


if __name__ == "__main__":
    main()
