"""Template contract checks use synthetic reports and local static fixtures."""
import copy
from html.parser import HTMLParser
import json
from pathlib import Path
import tempfile
import unittest

from cfd_review.demo import make_demo_project
from cfd_review.report import build_report,render_report
from cfd_review.templates import CSP,export_builtin_templates,validate_template


class _Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False);self.csp=[];self.images=[];self.data=[];self.active=False
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if tag=="meta" and attrs.get("http-equiv","").lower()=="content-security-policy":self.csp.append(attrs.get("content"))
        if tag=="img":self.images.append(attrs.get("src"))
        if tag=="script":self.active=attrs.get("id")=="cfd-project-data"
    def handle_endtag(self,tag):
        if tag=="script":self.active=False
    def handle_data(self,value):
        if self.active:self.data.append(value)


class TemplateChecks(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.pack=export_builtin_templates(self.root/"templates")[0]
        self.layout=self.pack/"layout.html"
        self.original=self.layout.read_text(encoding="utf-8")

    def test_builtin_pack_is_editable_and_preserves_existing_exports(self):
        info=validate_template(self.pack)
        self.assertEqual(info["name"],"Engineering Blue")
        self.assertIn("data:image/svg+xml;base64,",info["html"])
        self.assertIn("min-width:1200px",info["css"])
        with self.assertRaises(ValueError):export_builtin_templates(self.root/"templates")
        self.assertEqual(self.layout.read_text(encoding="utf-8"),self.original)

    def test_missing_duplicate_and_wrong_container_hooks_rejected(self):
        for changed in [self.original.replace("{{THREE_JS}}",""),
                        self.original.replace("{{THREE_JS}}","{{THREE_JS}}{{THREE_JS}}"),
                        self.original.replace("{{THREE_JS}}","alert(1);{{THREE_JS}}"),
                        self.original.replace('type="application/json"','type="text/javascript"'),
                        self.original.replace("{{STUDIO_JS}}","{{ORBIT_CONTROLS_JS}}")]:
            with self.subTest(changed=changed[-80:]):
                self.layout.write_text(changed,encoding="utf-8")
                with self.assertRaises(ValueError):validate_template(self.pack)

    def test_duplicate_app_and_hook_ids_rejected(self):
        for changed in [self.original.replace('<main class="review-template-main">','<main class="review-template-main"><div id="app"></div>'),
                        self.original.replace('id="orbit-runtime"','id="three-runtime"'),
                        self.original.replace('id="app"','id="application"')]:
            self.layout.write_text(changed,encoding="utf-8")
            with self.assertRaises(ValueError):validate_template(self.pack)

    def test_path_escape_absolute_and_symlink_escape_rejected(self):
        manifest_path=self.pack/"template.json";original=json.loads(manifest_path.read_text(encoding="utf-8"))
        outside=self.root/"outside.css";outside.write_text("body{}",encoding="utf-8")
        for value in ["../../outside.css",str(outside),"https://example.invalid/style.css","%2e%2e/%2e%2e/outside.css"]:
            manifest={**original,"css":value};manifest_path.write_text(json.dumps(manifest),encoding="utf-8")
            with self.assertRaises(ValueError):validate_template(self.pack)
        link=self.pack/"escaped.css"
        try:link.symlink_to(outside)
        except OSError:return
        manifest_path.write_text(json.dumps({**original,"css":"escaped.css"}),encoding="utf-8")
        with self.assertRaises(ValueError):validate_template(self.pack)

    def test_remote_resources_and_extra_javascript_rejected(self):
        samples=[self.original.replace('src="mark.svg"','src="https://example.invalid/image.png"'),
                 self.original.replace("</body>","<script>alert(1)</script></body>"),
                 self.original.replace('<body class="engineering-blue">','<body class="engineering-blue" onload="alert(1)">'),
                 self.original.replace("</body>",'<iframe src="https://example.invalid"></iframe></body>')]
        for changed in samples:
            self.layout.write_text(changed,encoding="utf-8")
            with self.assertRaises(ValueError):validate_template(self.pack)
        self.layout.write_text(self.original,encoding="utf-8")
        for css in ['@import "https://example.invalid/x.css";',r'body{background:u\72l(https://example.invalid/x.png)}',
                    r'.x{content:"\3c /style><script>alert(1)</script>"}',
                    'body{background:url(//example.invalid/x.png)}','body{background:image-set("https://example.invalid/x.png" 1x)}']:
            (self.pack/"theme.css").write_text(css,encoding="utf-8")
            with self.assertRaises(ValueError):validate_template(self.pack)

    def test_local_image_and_font_assets_embed_with_fixed_csp(self):
        (self.pack/"font.woff2").write_bytes(b"synthetic font fixture, not a real installed font")
        (self.pack/"theme.css").write_text('@font-face{font-family:Test;src:url("font.woff2")} .brand{background:url(mark.svg)}',encoding="utf-8")
        modified=self.original.replace("<head>",'<head class="template-head"><meta http-equiv="Content-Security-Policy" content="default-src *">')
        self.layout.write_text(modified,encoding="utf-8")
        page=render_report(make_demo_project(),template=self.pack)
        parser=_Page();parser.feed(page)
        self.assertEqual(parser.csp,[CSP]);self.assertIn("font-src data:",parser.csp[0])
        self.assertTrue(all(src.startswith("data:image/") for src in parser.images))
        self.assertIn("data:font/woff2;base64,",page)
        self.assertNotIn('content="default-src *"',page)

    def test_layout_preserves_engine_data_and_literal_tokens(self):
        project=make_demo_project();project["title"]='</script><script>evil()</script> {{STUDIO_JS}}'
        before=copy.deepcopy(project)
        (self.pack/"theme.css").write_text('.label:after{content:"{{STUDIO_JS}}"}',encoding="utf-8")
        out=build_report(project,self.root/"review.html",template=self.pack)
        page=out.read_text(encoding="utf-8");parser=_Page();parser.feed(page)
        self.assertEqual(json.loads("".join(parser.data)),before)
        self.assertEqual(project,before)
        self.assertIn('content:"{{STUDIO_JS}}"',page)
        self.assertNotIn('<script>evil()</script>',page)
        self.assertIn("review-template-heading",page)
        self.assertLess(page.index(".studio-stitch-section"),page.index('.label:after'))

    def test_css_only_pack_uses_existing_layout_and_invalid_template_writes_nothing(self):
        (self.pack/"template.json").write_text(json.dumps({"schema":"cfd-review-template","version":1,"name":"CSS only","css":"theme.css"}),encoding="utf-8")
        info=validate_template(self.pack);self.assertIsNone(info["html"])
        page=render_report(make_demo_project(),template=self.pack)
        self.assertIn('id="app"',page);self.assertIn('id="cfd-template-style"',page)
        (self.pack/"template.json").write_text('{}',encoding="utf-8")
        output=self.root/"missing.html"
        with self.assertRaises(ValueError):build_report(make_demo_project(),output,template=self.pack)
        self.assertFalse(output.exists())


if __name__=="__main__":unittest.main()
