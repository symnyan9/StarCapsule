"""Offline gzip fallback regression checks with synthetic mathematical data.

Chromium intentionally loses its native compression interfaces. This validates
the bundled compatibility path, not a physical iPad, Safari or memory capacity.
"""
from __future__ import annotations

import argparse
import base64
import gzip
import json
import math
from pathlib import Path
import re
import sys
import traceback
from unittest.mock import patch
import zlib

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from cfd_review import report
from check_compressed_report import LIMIT, TINY, compressed, raw_json, same_project, slot_script, synthetic_case


SLOTS = re.compile(r'(<script\b[^>]*\bid="(cfd-project-data|cfd-case-data-\d+|cfd-section-data-\d+-\d+|cfd-layer-data-\d+-\d+)"[^>]*>)([\s\S]*?)(</script\s*>)', re.I)
DISABLE_NATIVE = "window.DecompressionStream=undefined;window.CompressionStream=undefined;"
THROW_NATIVE = "window.gzipConstructorCalls=0;window.DecompressionStream=class{constructor(){window.gzipConstructorCalls++;throw new TypeError('Synthetic unsupported gzip constructor');}};window.CompressionStream=undefined;"
COUNT_NATIVE = "window.gzipConstructorCalls=0;const nativeGzip=window.DecompressionStream;window.DecompressionStream=new Proxy(nativeGzip,{construct(target,args){window.gzipConstructorCalls++;return Reflect.construct(target,args);}});"


def envelope_from_bytes(data, decoded_bytes, width=127):
    return {"schema": "cfd-review-compressed", "version": 1, "encoding": "gzip-base64",
            "decodedBytes": decoded_bytes,
            "chunks": [base64.b64encode(data[i:i + width]).decode("ascii")
                       for i in range(0, len(data), width)]}


def fixture_case(variant):
    case = synthetic_case(variant)
    case["data"]["layers"] = case["data"]["layers"][:1]
    case["name"] += " · 压力与总压🙂"
    for cut in case["data"]["sections"]:
        cut["cp"][:3] = [-0.0, TINY, -9.876543210987654e-19]
        cut["cpt"][:3] = [-0.0, TINY, -9.876543210987654e-19]
    return case


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--browser-executable", type=Path)
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    receipt = {"fixture": "Synthetic mathematical meshes only; no native STAR or real CFD",
               "scope": "Offline Chromium with missing/throwing native gzip; not physical iPad validation",
               "checks": {}, "errors": [], "network": [], "profiles": {}, "passed": False}

    def check(label, condition):
        receipt["checks"][label] = bool(condition)
        if not condition:
            raise AssertionError(label)

    def sources_equal(label, expected, actual):
        check(label, expected["cases"] == actual["cases"] and
              math.copysign(1, actual["cases"][0]["data"]["parts"][0]["cp"][0]) < 0 and
              actual["cases"][0]["data"]["parts"][0]["cp"][1] == TINY)

    try:
        fixture = report.project_from_cases([fixture_case(0)], "Synthetic gzip compatibility · 压力🙂")
        fixture["ui"] = {"language": "en", "mobileMode": "auto"}
        incoming = report.project_from_cases([fixture_case(1)], "Synthetic incoming · 截面🙂")
        legacy = out / "fallback-legacy-synthetic.html"
        lazy = out / "fallback-v2-synthetic.html"
        with patch.object(report, "_SECTION_BUNDLE_THRESHOLD_BYTES", LIMIT + 1), \
                patch.object(report, "_COMPRESSION_THRESHOLD_BYTES", 1):
            report.build_report(fixture, legacy, overwrite=True)
        # Put the first non-ASCII sequence across a 64 KiB output boundary. Each
        # compressed fragment is independently Base64 encoded, including padding.
        raw = raw_json(fixture)
        first_unicode = next(i for i, value in enumerate(raw) if value >= 128)
        raw = b" " * ((65535 - first_unicode) % 65536) + raw
        packed = envelope_from_bytes(gzip.compress(raw, mtime=0), len(raw))
        check("UTF-8 sequence crosses a 64 KiB decoded boundary", raw[65535] >= 128 and raw[65536] & 192 == 128)
        legacy.write_text(SLOTS.sub(lambda m: slot_script(m[2], packed), legacy.read_text(encoding="utf-8")), encoding="utf-8")
        with patch.object(report, "_SECTION_BUNDLE_THRESHOLD_BYTES", 0), \
                patch.object(report, "_COMPRESSION_THRESHOLD_BYTES", 1), \
                patch.object(report, "_SECTION_COMPRESSION_THRESHOLD_BYTES", 1):
            report.build_report(fixture, lazy, overwrite=True)
        sources_equal("Python accepts legacy boundary fixture unchanged", fixture, report.load_report_document(legacy))
        sources_equal("Python accepts compressed v2 slots unchanged", fixture, report.load_report_document(lazy))
        incoming_html = slot_script("cfd-project-data", compressed(incoming))

        with sync_playwright() as playwright:
            launch = {"headless": True, "args": ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"]}
            if args.browser_executable:
                launch["executable_path"] = str(args.browser_executable.resolve(strict=True))
            browser = playwright.chromium.launch(**launch)
            try:
                for mode, init, paths in (
                    ("missing-native", DISABLE_NATIVE, [legacy, lazy]),
                    ("throwing-native", THROW_NATIVE, [legacy]),
                    ("native-preferred", COUNT_NATIVE, [legacy]),
                ):
                    info = receipt["profiles"][mode] = {}
                    context = browser.new_context(offline=True, accept_downloads=True,
                                                  viewport={"width": 1024, "height": 768},
                                                  has_touch=True, is_mobile=True, device_scale_factor=2)
                    context.add_init_script(init)
                    context.set_default_timeout(30000)

                    def open_page(path):
                        page = context.new_page()
                        page.on("pageerror", lambda error: receipt["errors"].append({"mode": mode, "error": str(error)}))
                        page.on("request", lambda request: receipt["network"].append(request.url)
                                if request.url.startswith(("http:", "https:")) else None)
                        page.goto(path.as_uri())
                        page.wait_for_function("() => !!window.CFDStudio")
                        check(f"{mode}: {path.stem} opens offline", page.evaluate("CFDStudio.ready"))
                        check(f"{mode}: opening task clears", page.evaluate("() => document.querySelector('.studio-task-status').hidden && document.querySelector('#app').getAttribute('aria-busy')==='false'"))
                        return page

                    try:
                        for source in paths:
                            page = open_page(source)
                            check(f"{mode}: source numbers and non-ASCII labels survive", page.evaluate("""() => {
                              const c=CFDStudio.project.cases[0],m=CFDStudio.viewers[0].data.parts[0];
                              return c.name.includes('压力与总压🙂') && Object.is(m.cp[0],-0)
                                && m.cp[1]===1.2345678901234567e-27 && m.cp[2]===-9.876543210987654e-19;
                            }"""))
                            if mode == "native-preferred":
                                result = page.evaluate("""async text => {
                                  let fallback=0;const original=pako.Inflate,before=window.gzipConstructorCalls;
                                  pako.Inflate=new Proxy(original,{construct(target,args){fallback++;return Reflect.construct(target,args);}});
                                  try{await CFDStudio.importFile(new File([text],'native-source.html',{type:'text/html'}));}
                                  finally{pako.Inflate=original;}
                                  return {native:window.gzipConstructorCalls-before,fallback};
                                }""", incoming_html)
                                check("native decode remains preferred over bundled fallback", result["native"] > 0 and result["fallback"] == 0)
                                damaged = bytearray(gzip.compress(raw_json(fixture), mtime=0))
                                damaged[-8] ^= 1
                                result = page.evaluate("""async envelope => {
                                  const old=CFDStudio.project,original=pako.Inflate;
                                  let fallback=0,rejected=false;
                                  pako.Inflate=new Proxy(original,{construct(target,args){fallback++;return Reflect.construct(target,args);}});
                                  const html='<script id="cfd-project-data" type="application/json">'+JSON.stringify(envelope)+'<'+ '/script>';
                                  try{await CFDStudio.importFile(new File([html],'native-corrupt.html',{type:'text/html'}));}
                                  catch(error){rejected=true;}
                                  finally{pako.Inflate=original;}
                                  return rejected && CFDStudio.project===old && fallback===0;
                                }""", envelope_from_bytes(damaged, len(raw_json(fixture))))
                                check("native corruption is rejected without fallback retry", result)
                                page.close()
                                continue
                            if mode == "throwing-native":
                                check("unsupported native gzip constructor uses bundled fallback", page.evaluate("window.gzipConstructorCalls") > 0)
                                page.close()
                                continue
                            check("native compression and decompression really are absent", page.evaluate("typeof DecompressionStream==='undefined' && typeof CompressionStream==='undefined'"))
                            if source == lazy:
                                before = info["lazyBeforeSave"] = page.evaluate("CFDStudio.lazyMetrics")
                                check("fallback v2 initially leaves sections and layers compressed", before["sectionLoads"] == 1 and before["layerLoads"] == 0)
                            page.evaluate("CFDStudio.addNote('离线解压审阅🙂')")
                            with page.expect_download() as download:
                                page.evaluate("CFDStudio.downloadHTML()")
                            saved = out / (source.stem + "-saved.html")
                            download.value.save_as(saved)
                            loaded = report.load_report_document(saved)
                            sources_equal(f"{source.stem}: saving preserves complete source arrays", fixture, loaded)
                            check(f"{source.stem}: saving preserves non-ASCII notes", loaded["notes"][-1]["text"] == "离线解压审阅🙂")
                            if source == lazy:
                                after = info["lazyAfterSave"] = page.evaluate("CFDStudio.lazyMetrics")
                                check("fallback save does not decode unvisited v2 slots", all(after[key] == before[key] for key in ("coreLoads", "sectionLoads", "layerLoads")))
                                documents = {m[2]: json.loads(m[3]) for m in SLOTS.finditer(saved.read_text(encoding="utf-8"))}
                                check("untouched v2 section and layer slots remain gzip encoded", all(value.get("schema") == "cfd-review-compressed" for key, value in documents.items() if key.startswith(("cfd-section-data-", "cfd-layer-data-"))))
                            check(f"{source.stem}: save task clears", page.locator('.studio-task-status').is_hidden())
                            page.close()
                            page = open_page(saved)
                            actual = page.evaluate("CFDStudio.exportProject()")
                            check(f"{source.stem}: saved report reopens with exact project", same_project(loaded, actual))
                            check(f"{source.stem}: reopened negative zero remains negative", page.evaluate("() => Object.is(CFDStudio.project.cases[0].data.parts[0].cp[0],-0)"))

                            if source == legacy:
                                base = compressed(incoming)
                                raw_incoming = raw_json(incoming)
                                data = b"".join(base64.b64decode(chunk) for chunk in base["chunks"])
                                crc, length = bytearray(data), bytearray(data)
                                crc[-8] ^= 1
                                length[-4] ^= 1
                                mutations = {
                                    "bad CRC": envelope_from_bytes(crc, len(raw_incoming)),
                                    "bad ISIZE": envelope_from_bytes(length, len(raw_incoming)),
                                    "truncated trailer": envelope_from_bytes(data[:-1], len(raw_incoming)),
                                    "missing trailer": envelope_from_bytes(data[:-8], len(raw_incoming)),
                                    "truncated deflate": envelope_from_bytes(data[:len(data)//2], len(raw_incoming)),
                                    "zlib wrapper": envelope_from_bytes(zlib.compress(raw_incoming), len(raw_incoming)),
                                    "raw deflate": envelope_from_bytes(zlib.compress(raw_incoming, wbits=-15), len(raw_incoming)),
                                    "trailing junk": envelope_from_bytes(data + b"garbage", len(raw_incoming)),
                                    "trailing zeros": envelope_from_bytes(data + b"\0\0", len(raw_incoming)),
                                    "second gzip member": envelope_from_bytes(data + gzip.compress(b" ", mtime=0), len(raw_incoming)+1),
                                    "empty first gzip member": envelope_from_bytes(gzip.compress(b"", mtime=0) + data, len(raw_incoming)),
                                    "bad UTF8": compressed(None, raw=b'"\xff"'),
                                    "nested envelope": compressed(base),
                                    "invalid base64": {**base, "chunks": ["!!!!"]},
                                    "noncanonical padding": {**base, "chunks": ["Zh=="]},
                                    "oversize base64": {**base, "chunks": ["A" * (1024*1024+4)]},
                                    "unknown key": {**base, "extra": True},
                                    "wrong encoding": {**base, "encoding": "zlib-base64"},
                                    "oversize declaration": {**base, "decodedBytes": LIMIT+1},
                                    "wrong short declaration": {**base, "decodedBytes": len(raw_incoming)-1},
                                    "wrong long declaration": {**base, "decodedBytes": len(raw_incoming)+1},
                                    "output amplification": {**compressed(None, raw=b" " * 400000), "decodedBytes": 8},
                                    "duplicate JSON keys": compressed(None, raw=b'{"a":1,"a":2}'),
                                }
                                for label, envelope in mutations.items():
                                    result = page.evaluate("""async envelope => {
                                      const old=CFDStudio.project,n=old.cases.length,notes=JSON.stringify(old.notes),state=CFDStudio.viewers[0].getState();
                                      const html='<script id="cfd-project-data" type="application/json">'+JSON.stringify(envelope)+'<'+ '/script>';
                                      const original=pako.Inflate;let rejected=false,reason='',decoders=0;
                                      pako.Inflate=new Proxy(original,{construct(target,args){decoders++;return Reflect.construct(target,args);}});
                                      try{await CFDStudio.importFile(new File([html],'invalid-gzip.html',{type:'text/html'}));}
                                      catch(error){rejected=true;reason=error.message;}
                                      finally{pako.Inflate=original;}
                                      const after=CFDStudio.viewers[0].getState(),camera=['position','target'].every(k=>after.camera[k].every((x,i)=>Math.abs(x-state.camera[k][i])<1e-9));
                                      delete after.camera;delete state.camera;
                                      return {unchanged:rejected&&CFDStudio.project===old&&old.cases.length===n&&JSON.stringify(old.notes)===notes&&camera&&JSON.stringify(after)===JSON.stringify(state),
                                        idle:document.querySelector('.studio-task-status').hidden&&document.querySelector('#app').getAttribute('aria-busy')==='false',reason,decoders};
                                    }""", envelope)
                                    info.setdefault("rejections", {})[label] = result
                                    check(label + " rejects and preserves live project", result["unchanged"])
                                    check(label + " clears task state", result["idle"])
                                    if label in {"invalid base64", "noncanonical padding", "oversize base64",
                                                 "unknown key", "wrong encoding", "oversize declaration"}:
                                        check(label + " rejects before starting decompression", result["decoders"] == 0)
                                    if label == "output amplification":
                                        check("amplified output stops at the decoded-byte guard", "500 MiB" in result["reason"])
                            page.close()
                    finally:
                        context.close()
            finally:
                browser.close()
        check("no uncaught JavaScript errors", not receipt["errors"])
        check("no network requests", not receipt["network"])
        receipt["passed"] = True
    except Exception:
        receipt["exception"] = traceback.format_exc()
    target = out / "gzip-fallback-checks.json"
    target.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"passed": receipt["passed"], "checks": len(receipt["checks"]), "receipt": str(target)}, ensure_ascii=False))
    if not receipt["passed"]:
        print(receipt.get("exception", ""))
    return 0 if receipt["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
