"""Validate editable offline layouts while retaining the shipped review engine."""
from __future__ import annotations

import base64
from html import escape
from html.parser import HTMLParser
from importlib import resources
import json
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit
import xml.etree.ElementTree as ET


ENGINE_HOOKS = ("STUDIO_CSS", "FIELD_VIEWER_CSS", "PROJECT_JSON", "THREE_JS",
                "ORBIT_CONTROLS_JS", "FIELD_VIEWER_JS", "STUDIO_JS")
# Eight embedded blocks include the optional presentation-only TEMPLATE_CSS;
# the seven mandatory blocks above are the existing renderer/data interface.
SCRIPT_HOOKS = ("PROJECT_JSON", "THREE_JS", "ORBIT_CONTROLS_JS", "FIELD_VIEWER_JS", "STUDIO_JS")
CSP = ("default-src 'none'; script-src 'unsafe-inline' blob:; style-src 'unsafe-inline'; "
       "img-src data: blob:; font-src data:; connect-src 'none'; object-src 'none'; "
       "base-uri 'none'; form-action 'none'")
_MIME = {".png":"image/png", ".jpg":"image/jpeg", ".jpeg":"image/jpeg", ".webp":"image/webp",
         ".gif":"image/gif", ".avif":"image/avif", ".ico":"image/x-icon", ".svg":"image/svg+xml",
         ".woff":"font/woff", ".woff2":"font/woff2", ".ttf":"font/ttf", ".otf":"font/otf"}
_URL = re.compile(r"url\(\s*(?:\"([^\"]*)\"|'([^']*)'|([^)]*))\s*\)", re.I)
_TOKENS = re.compile(r"\{\{([A-Z_]+)\}\}")


def _local(root, relative):
    if not isinstance(relative,str) or not relative.strip():
        raise ValueError("Template asset paths must be nonempty relative paths")
    decoded=unquote(relative)
    parsed=urlsplit(decoded)
    if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment or Path(decoded).is_absolute():
        raise ValueError("Template files must use plain paths inside the template folder")
    path=(root/decoded).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError("Template file is missing or escapes its folder: "+relative)
    return path


def _check_svg(raw):
    try:
        tree=ET.fromstring(raw)
    except ET.ParseError as error:
        raise ValueError("Invalid SVG template image") from error
    for node in tree.iter():
        tag=node.tag.rsplit("}",1)[-1].lower()
        if tag in {"script","foreignobject","iframe","object","embed","animate","animatetransform","set"}:
            raise ValueError("Template SVG must contain static image content")
        for key,value in node.attrib.items():
            attr=key.rsplit("}",1)[-1].lower()
            if attr.startswith("on") or (attr in {"href","src"} and not value.startswith("#")):
                raise ValueError("Template SVG must not load or execute external content")
            if "url(" in value.lower() and not re.fullmatch(r"url\(\s*#[\w.-]+\s*\)",value,re.I):
                raise ValueError("Template SVG resource references must be local fragments")
        if tag=="style" and node.text and re.search(r"@import|url\(|https?:|expression\(",node.text,re.I):
            raise ValueError("Template SVG styles must be self-contained")


def _asset(root, value, image_only=False):
    if not isinstance(value,str) or not value.strip():
        raise ValueError("Empty template asset URL")
    value=value.strip()
    if value.startswith("#"):
        return value
    if value.lower().startswith("data:"):
        match=re.fullmatch(r"data:([^;,]+);base64,([A-Za-z0-9+/=\s]+)",value,re.I)
        if not match or match[1].lower() not in _MIME.values():
            raise ValueError("Template data URLs must be base64 images or fonts")
        try:
            raw=base64.b64decode(re.sub(r"\s+","",match[2]),validate=True)
        except ValueError as error:
            raise ValueError("Invalid base64 template asset") from error
        mime=match[1].lower()
    else:
        path=_local(root,value)
        mime=_MIME.get(path.suffix.lower())
        if mime is None:
            raise ValueError("Unsupported template asset type: "+path.suffix)
        raw=path.read_bytes()
    if image_only and not mime.startswith("image/"):
        raise ValueError("HTML image assets must be images")
    if mime=="image/svg+xml":
        _check_svg(raw)
    return "data:"+mime+";base64,"+base64.b64encode(raw).decode("ascii")


def _css(value,root):
    if "</style" in value.lower():
        raise ValueError("Template CSS must not close its style container")
    # Normalize escapes before examining resource syntax, including escaped url/@import.
    value=re.sub(r"\\([0-9a-fA-F]{1,6})(?:\s)?|\\([^\r\n])",
                 lambda m:chr(int(m[1],16)) if m[1] else m[2],value)
    if "</style" in value.lower():
        raise ValueError("Escaped template CSS must not close its style container")
    visible=re.sub(r"/\*.*?\*/","",value,flags=re.S)
    if re.search(r"@import\b|expression\s*\(|(?:-moz-binding|behavior)\s*:|image-set\s*\(",visible,re.I):
        raise ValueError("Template CSS imports, executable rules and image-set are unsupported; use local url(...) assets")
    def replace(match):
        return 'url("'+_asset(root,next(x for x in match.groups() if x is not None).strip())+'")'
    result=_URL.sub(replace,value)
    # All loadable resources now use local fragments or embedded base64 data.
    check=_URL.sub("",re.sub(r"/\*.*?\*/","",result,flags=re.S))
    if re.search(r"url\s*\(|(?:https?|ftp|file|javascript)\s*:|//",check,re.I):
        raise ValueError("Template CSS contains an unsupported or external resource")
    return result


class _Layout(HTMLParser):
    allowed=set("html head body meta title style script div section main article header footer nav aside p h1 h2 h3 h4 h5 h6 br hr span strong em b i small code pre blockquote ul ol li dl dt dd table thead tbody tfoot tr th td figure figcaption img a button svg g path circle rect line polyline polygon text defs lineargradient radialgradient stop symbol use".split())
    void={"meta","img","br","hr"}
    def __init__(self,root):
        super().__init__(convert_charrefs=False)
        self.root=root;self.out=[];self.stack=[];self.ids=set();self.blocks=[];self.raw=None;self.raw_data=[]
        self.heads=0;self.bodies=0;self.apps=0;self.app_position=None;self.project_position=None

    def handle_decl(self,decl):
        if decl.lower()!="doctype html":raise ValueError("Template only supports the HTML doctype")
        self.out.append("<!doctype html>")

    def handle_comment(self,value):
        self.out.append("<!--"+value+"-->")

    def handle_starttag(self,tag,attrs):
        if tag not in self.allowed:raise ValueError("Unsupported template tag: "+tag)
        if len({k for k,v in attrs})!=len(attrs):raise ValueError("Duplicate template HTML attribute")
        values=dict(attrs)
        if tag=="meta" and "http-equiv" in values:
            if (values["http-equiv"] or "").lower()=="content-security-policy":return
            raise ValueError("Template http-equiv directives are controlled by the application")
        if tag=="head":self.heads+=1
        if tag=="body":self.bodies+=1
        if values.get("id"):
            if values["id"] in self.ids:raise ValueError("Duplicate template HTML id")
            self.ids.add(values["id"])
        if values.get("id")=="app":
            if tag!="div" or "body" not in self.stack:raise ValueError("The app slot must be a div inside body")
            self.apps+=1;self.app_position=len(self.out)
        if tag in {"script","style"}:
            if self.raw is not None:raise ValueError("Nested template runtime container")
            if tag=="script" and set(values)-{"id","type"}:raise ValueError("Template scripts may only contain shipped engine hooks")
            self.raw=(tag,values,"head" in self.stack);self.raw_data=[]
        clean=[]
        for key,value in attrs:
            if key.startswith("on") or key in {"srcdoc","srcset","formaction","action","xmlns:xlink"}:
                raise ValueError("Executable or external template attributes are unsupported")
            if value is None:
                clean.append(key);continue
            if "{{" in value:raise ValueError("Engine hooks must not appear in HTML attributes")
            if key=="style":value=_css(value,self.root)
            elif key=="src":
                if tag!="img":raise ValueError("Only static images may use template src")
                value=_asset(self.root,value,True)
            elif key in {"href","xlink:href"}:
                if not value.startswith("#"):raise ValueError("Template links must be document fragments")
            clean.append(key+'="'+escape(value,quote=True)+'"')
        self.out.append("<"+tag+(" "+" ".join(clean) if clean else "")+">")
        if tag not in self.void:self.stack.append(tag)

    def handle_startendtag(self,tag,attrs):
        self.handle_starttag(tag,attrs)
        if tag not in self.void:self.handle_endtag(tag)

    def handle_endtag(self,tag):
        if tag in self.void:return
        if not self.stack or self.stack[-1]!=tag:raise ValueError("Template HTML tags must be explicitly balanced: "+tag)
        if self.raw is not None and self.raw[0]==tag:
            kind,attrs,in_head=self.raw;content="".join(self.raw_data);token=_TOKENS.fullmatch(content.strip())
            hook=token[1] if token else None
            if kind=="script":
                if hook not in SCRIPT_HOOKS:raise ValueError("Extra template JavaScript is not supported")
                if len(self.stack)<2 or self.stack[-2]!="body":
                    raise ValueError("Runtime scripts must follow the app slot directly in body")
                if hook=="PROJECT_JSON" and (attrs.get("id")!="cfd-project-data" or attrs.get("type")!="application/json"):
                    raise ValueError("Project data requires id=cfd-project-data and type=application/json")
                if hook=="PROJECT_JSON":self.project_position=len(self.out)
                if hook!="PROJECT_JSON" and attrs.get("type", "text/javascript") not in {"text/javascript","application/javascript"}:
                    raise ValueError("Engine scripts must use classic JavaScript")
            elif hook in {"STUDIO_CSS","FIELD_VIEWER_CSS","TEMPLATE_CSS"}:
                if not in_head:raise ValueError("Engine and template CSS hooks must appear in head")
            else:
                content=_css(content,self.root)
            if hook:self.blocks.append(hook)
            self.out.append(content);self.raw=None;self.raw_data=[]
        self.stack.pop();self.out.append("</"+tag+">")

    def handle_data(self,value):
        if self.raw is not None:self.raw_data.append(value)
        else:self.out.append(value)

    def handle_entityref(self,name):self.handle_data("&"+name+";")
    def handle_charref(self,name):self.handle_data("&#"+name+";")


def validate_template(folder):
    """Return validated, locally embedded layout/CSS and template identification."""
    root=Path(folder).expanduser().resolve()
    manifest_path=_local(root,"template.json")
    def unique(items):
        result={}
        for key,value in items:
            if key in result:raise ValueError("Duplicate template manifest key")
            result[key]=value
        return result
    manifest=json.loads(manifest_path.read_text(encoding="utf-8-sig"),object_pairs_hook=unique)
    if not isinstance(manifest,dict) or manifest.get("schema")!="cfd-review-template" or type(manifest.get("version")) is not int or manifest["version"]!=1:
        raise ValueError("Expected cfd-review-template version 1")
    name=manifest.get("name")
    if not isinstance(name,str) or not name.strip() or len(name)>200:raise ValueError("Template requires a name of 1-200 characters")
    if not manifest.get("html") and not manifest.get("css"):raise ValueError("Template requires html or css")
    html=None
    if manifest.get("html"):
        source=_local(root,manifest["html"]).read_text(encoding="utf-8-sig")
        for hook in ENGINE_HOOKS:
            if source.count("{{"+hook+"}}")!=1:raise ValueError("Template requires exactly one {{"+hook+"}} hook")
        if source.count("{{TEMPLATE_CSS}}")>1:raise ValueError("Duplicate TEMPLATE_CSS hook")
        if any(token not in (*ENGINE_HOOKS,"TEMPLATE_CSS") for token in _TOKENS.findall(source)):
            raise ValueError("Unknown template engine hook")
        parser=_Layout(root);parser.feed(source);parser.close()
        if parser.stack or parser.raw is not None or parser.heads!=1 or parser.bodies!=1 or parser.apps!=1:
            raise ValueError("Template requires one balanced head/body and one div id=app")
        mandatory=[block for block in parser.blocks if block!="TEMPLATE_CSS"]
        if tuple(mandatory)!=ENGINE_HOOKS:raise ValueError("Template engine hooks must retain CSS/data/runtime order")
        if "TEMPLATE_CSS" in parser.blocks and parser.blocks.index("TEMPLATE_CSS")!=2:
            raise ValueError("TEMPLATE_CSS must follow the two built-in CSS hooks before runtime scripts")
        html="".join(parser.out)
        if parser.app_position>parser.project_position:
            raise ValueError("Project/runtime hooks must follow the app slot")
    css=_css(_local(root,manifest["css"]).read_text(encoding="utf-8-sig"),root) if manifest.get("css") else ""
    css+='\n#app{min-width:1200px!important;min-height:760px!important}\n'
    return {"name":name.strip(),"path":str(root),"manifest":manifest,"html":html,"css":css}


def export_builtin_templates(output):
    """Copy editable, fully local examples into a new or empty directory."""
    target=Path(output).expanduser().resolve()
    if target.exists() and (not target.is_dir() or any(target.iterdir())):
        raise ValueError("Template export requires a new or empty directory")
    target.mkdir(parents=True,exist_ok=True)
    origin=resources.files("cfd_review").joinpath("assets","templates")
    copied=[]
    def copy_tree(source,destination):
        destination.mkdir(exist_ok=True)
        for item in source.iterdir():
            if item.is_dir():copy_tree(item,destination/item.name)
            else:(destination/item.name).write_bytes(item.read_bytes())
    for item in origin.iterdir():
        if item.is_dir():
            copy_tree(item,target/item.name);copied.append(target/item.name)
    return copied
