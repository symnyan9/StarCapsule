"""Verify offline English/Chinese switching with synthetic source data only.

Requires the optional Playwright development dependency; never starts STAR.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from cfd_review.demo import make_demo_project
from cfd_review.report import build_report, load_report_document


def reveal(locator):
    """Language selection lives in the native More menu."""
    locator.evaluate("node=>{for(let p=node.parentElement;p;p=p.parentElement)if(p.tagName==='DETAILS')p.open=true;}")
    return locator


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--template", type=Path)
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    project = make_demo_project()
    project.setdefault("ui", {}).pop("language", None)  # legacy defaults to English
    case = project["cases"][0]
    case["name"] = "工况"
    case["data"]["meta"]["title"] = "工程名称"
    case["data"]["meta"]["source"] = "色标"
    case["data"]["meta"]["fieldLabels"] = {"Cp": "复位", "CpT": "应用"}
    case["data"]["parts"][0]["name"] = "复位"
    case["data"]["layers"][0]["name"] = "色标"
    report = out / "language-demo.html"
    build_report(project, report, overwrite=True, template=args.template)
    receipt = {"fixture": "Synthetic data only; no STAR or real-case validation", "checks": {}, "errors": [], "network": []}

    def check(name, passed):
        receipt["checks"][name] = bool(passed)
        assert passed, name

    def open_page(context, path):
        page = context.new_page()
        page.on("pageerror", lambda error: receipt["errors"].append(str(error)))
        page.on("request", lambda request: receipt["network"].append(request.url)
                if request.url.startswith(("http:", "https:")) else None)
        page.goto(path.as_uri())
        check("viewer initialized", page.evaluate("CFDStudio.ready"))
        page.evaluate("CFDStudio.viewers.forEach(v => v.controls.enableDamping=false)")
        return page

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, args=["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"])
            context = browser.new_context(offline=True, accept_downloads=True, viewport={"width": 1440, "height": 1000})
            page = open_page(context, report)
            check("legacy project defaults to English", page.locator('[data-action="export-html"]').inner_text() == "Export HTML" and page.locator("html").get_attribute("lang") == "en")
            page.evaluate("""async () => {
              const v=CFDStudio.viewers[0];await v.setField('Cp');await v.setSection(3);
              v.setColorRange('section',-1.2,.8,'Cp');v.setMirrorDisplay(false,{fit:false});
              v.setLayerSettings(v.layers[0].id,{visible:true,opacity:.35,colorRange:[-.2,1.4]});
              v._showPick({kind:'surface',field:'Cp',value:.123,name:'复位',displayPoint:[0,0,0],sourcePoint:[0,0,0]},true);
              CFDStudio.addNote('复位',0);document.querySelector('[data-action="view-note"]').click();
              document.querySelector('[data-control="note-text"]').value='Pending user text / 用户文字';
              window.qaSignature=value=>JSON.stringify(value,(key,item)=>typeof item==='number'?Number(item.toFixed(10)):item);
              window.qaData=JSON.stringify(CFDStudio.project.cases);window.qaStates=qaSignature(CFDStudio.viewers.map(v=>v.getState()));
              window.qaViewers=[...CFDStudio.viewers];window.qaArrays=CFDStudio.project.cases.map(c=>c.data.parts[0].positions);
              window.qaGeometry=CFDStudio.viewers.map(v=>v.meshes[0].geometry);window.qaClone=structuredClone;window.qaClones=0;
              window.structuredClone=(...args)=>{window.qaClones++;return window.qaClone(...args);};
            }""")
            reveal(page.locator('[data-control="language"]')).select_option("zh-CN")
            check("Chinese selector updates controls and dynamic labels", page.locator('[data-action="export-html"]').inner_text() == "导出 HTML" and page.locator('[data-fv="section-range-label"]').first.inner_text() == "截面 复位色标")
            check("language switch preserves views and scientific array identity", page.evaluate("""()=>qaViewers.every((v,i)=>v===CFDStudio.viewers[i]&&v.meshes[0].geometry===qaGeometry[i])&&qaArrays.every((a,i)=>a===CFDStudio.project.cases[i].data.parts[0].positions)&&qaSignature(CFDStudio.viewers.map(v=>v.getState()))===qaStates&&JSON.stringify(CFDStudio.project.cases)===qaData&&qaClones===0"""))
            check("user text, source labels and names stay literal", page.evaluate("""()=>document.querySelector('.studio-note>p').textContent==='复位'&&document.querySelector('[data-control="note-text"]').value==='Pending user text / 用户文字'&&document.querySelector('[data-control="case"] option').textContent==='工况'&&document.querySelector('[data-fv="parts"] span').textContent==='复位'&&document.querySelector('[data-fv="layers"] .fv-inline span').textContent==='色标'&&document.querySelector('[data-fv="variable"] option[value="Cp"]').textContent==='复位'&&document.querySelector('[data-fv="source"]').textContent.startsWith('来源：色标。')&&document.querySelector('.fv-pick-name').textContent==='批注保存读数 · 复位'"""))
            if args.template:
                check("Engineering Blue outer shell switches to Chinese", page.locator('.review-template-heading h1').inner_text() == "三维仿真审阅" and page.locator('.review-template-caption').inner_text() == "表面与真实截面 · 工况对比 · 离线报告")
            reveal(page.locator('[data-control="language"]')).select_option("en")
            if args.template:
                check("Engineering Blue outer shell returns to English", page.locator('.review-template-heading h1').inner_text() == "3D Simulation Review" and page.locator('.review-template-footer').inner_text() == "Source data and display settings stay separate · Color limits preserve source values")
            check("English switch restores static and dynamic labels", page.locator('[data-action="export-html"]').inner_text() == "Export HTML" and page.locator('[data-fv="section-range-label"]').first.inner_text() == "Section 复位 color scale")
            check("English switch preserves scientific state and avoids cloning", page.evaluate("qaSignature(CFDStudio.viewers.map(v=>v.getState()))===qaStates&&JSON.stringify(CFDStudio.project.cases)===qaData&&qaClones===0"))
            check("English error text", page.evaluate("""()=>{try{CFDStudio.setLanguage('invalid')}catch(e){return e.message==='Project language must be en or zh-CN'}}"""))
            reveal(page.locator('[data-control="language"]')).select_option("zh-CN")
            check("Chinese error text", page.evaluate("""()=>{try{CFDStudio.setLanguage('invalid')}catch(e){return e.message==='工程语言须为 en 或 zh-CN'}}"""))
            page.evaluate("window.structuredClone=window.qaClone")
            with page.expect_download() as download:
                page.evaluate("CFDStudio.downloadHTML()")
            saved = out / "saved-language.html"
            download.value.save_as(saved)
            loaded = load_report_document(saved)
            check("saved HTML carries Chinese language", loaded.get("ui", {}).get("language") == "zh-CN")
            check("saved HTML retains source case data", loaded["cases"] == project["cases"])
            page.close()
            page = open_page(context, saved)
            check("reopened report restores Chinese", page.locator('[data-action="export-html"]').inner_text() == "导出 HTML" and page.locator('[data-control="language"]').input_value() == "zh-CN")
            check("reopened report retains camera, color, mirror and note", page.evaluate("""()=>{const s=CFDStudio.viewers[0].getState();return s.variable==='Cp'&&s.sectionIndex===3&&s.mirrorDisplay===false&&s.colorRanges.section.Cp[0]===-1.2&&s.layerSettings[CFDStudio.viewers[0].layers[0].id].opacity===.35&&CFDStudio.project.notes[0].text==='复位'}"""))
            reveal(page.locator('[data-control="language"]')).select_option("en")
            check("reopened report can switch to English", page.locator('[data-action="export-html"]').inner_text() == "Export HTML")
            check("no browser errors or network requests", not receipt["errors"] and not receipt["network"])
            browser.close()
    finally:
        (out / "checks.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"PASS: {len(receipt['checks'])} language checks")


if __name__ == "__main__":
    main()
