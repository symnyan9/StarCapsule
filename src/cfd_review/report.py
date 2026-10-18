"""Build a self-contained report without fetching any remote resources."""
from __future__ import annotations

import copy
import base64
import binascii
from contextlib import ExitStack, contextmanager
import gzip
import io
import json
import os
import re
import codecs
from html.parser import HTMLParser
from pathlib import Path
import tempfile
import zlib
from importlib.resources import files

from .schema import _identifier, _json_guard, _text, validate_case, validate_project
from .templates import CSP, validate_template


_MAX_REPORT_BYTES = 2 * 1024 * 1024 * 1024
_MAX_JSON_SLOT_BYTES = 500 * 1024 * 1024
_BUNDLE_THRESHOLD_BYTES = 64 * 1024 * 1024
_MAX_REPORT_CASES = 32
_READ_CHUNK_BYTES = 1024 * 1024
_MAX_COMPOSITION_RECIPE_BYTES = 1024 * 1024
_COMPRESSION_THRESHOLD_BYTES = 1024 * 1024
_BASE64_CHUNK_CHARS = 1024 * 1024
_BASE64_INPUT_BYTES = (_BASE64_CHUNK_CHARS // 4) * 3


def _composition_budget_case(recipe, sources):
    """Reference output-sized arrays for the guard without allocating geometry."""
    a, b = (source["data"]["sections"] for source in sources)
    pairs, common = [], {"cp", "cpt"}
    i = j = 0
    while i < len(a) and j < len(b):
        x, y = a[i]["x"], b[j]["x"]
        if abs(x - y) <= 1e-9 * max(1, abs(x), abs(y)):
            pairs.append((a[i], b[j]))
            common.intersection_update(a[i])
            common.intersection_update(b[j])
            i, j = i + 1, j + 1
        elif x < y:
            i += 1
        else:
            j += 1
    # Two referenced halves have exactly the numeric-array length of one merged
    # section. Metadata integers are not dense arrays and add no numeric cost.
    sections = [{key: cut[key] for key in ("positions", "indices", *sorted(common))}
                for pair in pairs for cut in pair] if common else []
    return {"schema": "cfd-review-case", "version": 1, "id": recipe["id"], "name": recipe["name"],
            "data": {"meta": recipe["meta"], "sections": sections,
                     **{kind: [mesh for source in sources for mesh in source["data"].get(kind, [])]
                        for kind in ("parts", "layers")}}}


def _assemble_cases(cases, project):
    """Resolve compact display compositions from retained original cases.

    A recipe only records presentation metadata and source references. Geometry
    is rebuilt by the same provenance-checked composition as an ordinary case;
    a recipe cannot reference another recipe or an already composed dataset.
    """
    originals = {}
    recipes = []
    identifiers = set()
    for case in cases:
        if case.get("schema") == "cfd-review-composition":
            _json_guard(case)
            if (set(case) != {"schema", "version", "id", "name", "meta"}
                    or type(case.get("version")) is not int or case["version"] != 1
                    or not isinstance(case.get("meta"), dict)):
                raise ValueError("Invalid cfd-review-composition version 1 recipe")
            _identifier(case["id"], "composition.id")
            _text(case["name"], "composition.name", 300)
            if (case["meta"].get("sourceKey") != "half-stitch:" + case["id"]
                    or "sourceSha256" in case["meta"]):
                raise ValueError("Composition recipe requires its own derived sourceKey and no sourceSha256")
            recipes.append(case)
        else:
            validate_case(case)
            if not case["data"]["meta"].get("comparison"):
                originals[case["id"]] = case
        if case["id"] in identifiers:
            raise ValueError("Report contains duplicate case IDs")
        identifiers.add(case["id"])
    pending = []
    for recipe in recipes:
        comparison = recipe["meta"].get("comparison")
        sources = comparison.get("sources") if isinstance(comparison, dict) else None
        if (not isinstance(comparison, dict) or comparison.get("kind") != "half-car-stitch"
                or type(comparison.get("version")) is not int or comparison["version"] != 1
                or not isinstance(sources, list) or len(sources) != 2
                or any(not isinstance(source, dict) or not isinstance(source.get("caseId"), str)
                       or not isinstance(source.get("sourceId"), str) for source in sources)
                or sources[0]["caseId"] == sources[1]["caseId"]):
            raise ValueError("Composition recipe requires two distinct original case sources")
        source_cases = []
        for source in sources:
            original = originals.get(source["caseId"])
            if original is None:
                raise ValueError("Composition recipe must retain both original non-comparison cases")
            meta = original["data"]["meta"]
            if source["sourceId"] != meta.get("sourceSha256", meta.get("sourceKey")):
                raise ValueError("Composition recipe source identity differs from its original case")
            if any(source.get(key) != meta.get(key) for key in ("sourceSha256", "sourceKey")):
                raise ValueError("Composition recipe source provenance differs from its original case")
            source_cases.append(original)
        pending.append((recipe, source_cases))
    shadows = {recipe["id"]: _composition_budget_case(recipe, sources) for recipe, sources in pending}
    # Count the complete expanded project before even the first recipe allocates
    # reflected/merged arrays; use the schema guard and its current budgets.
    _json_guard({**project, "cases": [shadows[case["id"]] if case.get("schema") == "cfd-review-composition"
                                     else case for case in cases]})
    resolved = {}
    for recipe, source_cases in pending:
        from .comparison import compose_half_comparison
        composed = compose_half_comparison(*source_cases, case_id=recipe["id"], name=recipe["name"])
        # Keep editable labels/ranges and all recorded scientific provenance.
        # Project validation below checks these references against the sources.
        composed["data"]["meta"] = copy.deepcopy(recipe["meta"])
        resolved[recipe["id"]] = validate_case(composed)
    return [resolved[case["id"]] if case.get("schema") == "cfd-review-composition" else case for case in cases]


def _case_slot(case):
    """Do not serialize copies of source arrays for a derived display case."""
    meta = case["data"]["meta"]
    if (meta.get("comparison") and meta.get("sourceKey") == "half-stitch:" + case["id"]
            and "sourceSha256" not in meta):
        return {"schema": "cfd-review-composition", "version": 1,
                "id": case["id"], "name": case["name"], "meta": meta}
    # Older full cases can have another derived identity; keep that supported
    # representation rather than silently rewriting its saved states/notes.
    return case


def _strict_json(stream):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"duplicate JSON object key: {key}")
            result[key] = value
        return result

    def constant(value):
        raise ValueError(f"non-finite JSON constant: {value}")

    return json.load(stream, object_pairs_hook=pairs, parse_constant=constant)


def _decompress_document(envelope):
    """Decode bounded gzip/base64 JSON without evaluating any page content."""
    _json_guard(envelope)
    if (set(envelope) != {"schema", "version", "encoding", "decodedBytes", "chunks"}
            or envelope.get("schema") != "cfd-review-compressed"
            or type(envelope.get("version")) is not int or envelope["version"] != 1
            or envelope.get("encoding") != "gzip-base64"
            or type(envelope.get("decodedBytes")) is not int
            or not 1 <= envelope["decodedBytes"] <= _MAX_JSON_SLOT_BYTES
            or not isinstance(envelope.get("chunks"), list) or not envelope["chunks"]):
        raise ValueError("Invalid cfd-review-compressed version 1 envelope")
    declared = envelope["decodedBytes"]
    with tempfile.TemporaryFile(mode="w+b") as packed, tempfile.TemporaryFile(mode="w+b") as decoded:
        for chunk in envelope["chunks"]:
            if not isinstance(chunk, str) or not 1 <= len(chunk) <= _BASE64_CHUNK_CHARS:
                raise ValueError("Compressed JSON base64 chunks must contain 1 to 1 MiB characters")
            try:
                raw = base64.b64decode(chunk, validate=True)
                if base64.b64encode(raw).decode("ascii") != chunk:
                    raise ValueError("Noncanonical base64 chunk")
            except (ValueError, binascii.Error) as error:
                raise ValueError("Compressed JSON contains an invalid strict base64 chunk") from error
            packed.write(raw)
        # These are parser-owned compressed strings, not scientific data. Drop
        # them before constructing the decoded project's numeric arrays.
        envelope["chunks"].clear()
        packed.seek(0)
        count = 0
        try:
            with gzip.GzipFile(fileobj=packed, mode="rb") as reader:
                while block := reader.read(min(_READ_CHUNK_BYTES, declared - count + 1)):
                    count += len(block)
                    if count > declared or count > _MAX_JSON_SLOT_BYTES:
                        raise ValueError("Compressed JSON exceeds its declared decodedBytes/input limit")
                    decoded.write(block)
        except (OSError, EOFError, zlib.error) as error:
            raise ValueError("Compressed JSON has corrupt or incomplete gzip data") from error
        if count != declared:
            raise ValueError("Compressed JSON decoded size differs from decodedBytes")
        decoded.seek(0)
        with io.TextIOWrapper(decoded, encoding="utf-8") as text:
            document = _strict_json(text)
        if isinstance(document, dict) and document.get("schema") == "cfd-review-compressed":
            raise ValueError("Nested compressed JSON envelopes are not allowed")
        return document, count


class _ProjectDataParser(HTMLParser):
    """Read only the fixed JSON slot; scripts/styles are never evaluated."""

    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.documents = {}
        self.seen = set()
        self.active = None
        self.spool = None
        self.slot_bytes = 0

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        identifier = attributes.get("id", "")
        if identifier != "cfd-project-data" and not identifier.startswith("cfd-case-data-"):
            return
        if identifier in self.seen:
            raise ValueError(f"Report contains duplicate {identifier} elements")
        if identifier != "cfd-project-data" and not re.fullmatch(r"cfd-case-data-(0|[1-9][0-9]*)", identifier):
            raise ValueError("Invalid report case-data element ID")
        if len(self.seen) >= _MAX_REPORT_CASES + 1:
            raise ValueError("Report exceeds the 32-case bundle limit")
        if (tag != "script" or attributes.get("type", "").strip().lower() != "application/json"
                or "src" in attributes or len(attrs) != len(attributes)):
            raise ValueError("Report data must be one inline application/json script with id cfd-project-data")
        self.seen.add(identifier)
        self.active = identifier
        self.slot_bytes = 0
        self.spool = tempfile.TemporaryFile(mode="w+", encoding="utf-8", newline="")

    def handle_startendtag(self, tag, attrs):
        identifier = dict(attrs).get("id", "")
        if identifier == "cfd-project-data" or identifier.startswith("cfd-case-data-"):
            raise ValueError("Report project-data script must have an explicit closing tag")

    def handle_data(self, data):
        if self.active:
            self.slot_bytes += len(data.encode("utf-8"))
            if self.slot_bytes > _MAX_JSON_SLOT_BYTES:
                raise ValueError("Report JSON slot exceeds the 500 MiB input limit")
            self.spool.write(data)

    def handle_endtag(self, tag):
        if tag == "script" and self.active:
            try:
                self.spool.seek(0)
                document = _strict_json(self.spool)
                decoded_bytes = self.slot_bytes
                if isinstance(document, dict) and document.get("schema") == "cfd-review-compressed":
                    document, decoded_bytes = _decompress_document(document)
                if (isinstance(document, dict) and document.get("schema") == "cfd-review-composition"
                        and decoded_bytes > _MAX_COMPOSITION_RECIPE_BYTES):
                    raise ValueError("Composition recipe exceeds the 1 MiB input limit")
                self.documents[self.active] = document
            finally:
                self.spool.close()
                self.spool = None
            self.active = None

    def flush_raw_text(self):
        """Bound HTMLParser's raw-text buffer instead of concatenating a case.

        HTMLParser waits for an entire script before delivering its data. Its
        rawdata buffer can safely release complete raw-text prefixes here; keep
        a possible closing-tag prefix for the next feed. Tested on Python 3.10+.
        """
        if not self.rawdata:
            return
        if not self.cdata_elem:
            if len(self.rawdata) > 65536:
                raise ValueError("HTML tag exceeds the 64 KiB parser limit")
            return
        start = self.rawdata.rfind("<")
        suffix = self.rawdata[start:].lower() if start >= 0 else ""
        closing = "</" + self.cdata_elem
        keep = start if suffix and (closing.startswith(suffix) or suffix.startswith(closing)) else len(self.rawdata)
        if len(self.rawdata) - keep > 65536:
            raise ValueError("HTML closing tag exceeds the 64 KiB parser limit")
        if keep:
            self.handle_data(self.rawdata[:keep])
            self.updatepos(0, keep)
            self.rawdata = self.rawdata[keep:]

    def finish_document(self):
        if self.active or "cfd-project-data" not in self.documents:
            raise ValueError("HTML must contain one complete cfd-project-data application/json script")
        root = self.documents["cfd-project-data"]
        if isinstance(root, dict) and root.get("schema") == "cfd-review-html-bundle":
            references = root.get("cases")
            project = root.get("project")
            if (set(root) != {"schema", "version", "project", "cases"} or type(root.get("version")) is not int
                    or root["version"] != 1 or not isinstance(project, dict) or "cases" in project
                    or not isinstance(references, list) or not 1 <= len(references) <= _MAX_REPORT_CASES):
                raise ValueError("Invalid cfd-review-html-bundle version 1 manifest")
            cases = []
            for index, reference in enumerate(references):
                expected_id = f"cfd-case-data-{index}"
                if (not isinstance(reference, dict) or set(reference) != {"id", "elementId"}
                        or reference.get("elementId") != expected_id):
                    raise ValueError("Invalid report case-data reference")
                case = self.documents.get(expected_id)
                if not isinstance(case, dict) or case.get("id") != reference.get("id"):
                    raise ValueError("Report case-data ID differs from its manifest or is missing")
                cases.append(case)
            if set(self.documents) != {"cfd-project-data", *(r["elementId"] for r in references)}:
                raise ValueError("Report contains unreferenced case-data slots")
            root = {**project, "cases": _assemble_cases(cases, project)}
        elif len(self.documents) != 1:
            raise ValueError("Legacy report contains unreferenced case-data slots")
        return validate_project(root)

    def release(self):
        if self.spool is not None:
            self.spool.close()
            self.spool = None


def load_report_document(path: str | Path) -> dict:
    """Load a saved report's strict project JSON without executing its HTML.

    The page is streamed with a 2 GiB total / 500 MiB JSON-slot bound. Each case
    is decoded separately; no giant combined HTML/project string is needed.
    Only scientific data and state are reused; old CSS/JS is discarded.
    """
    source = Path(path).expanduser().resolve()
    if source.suffix.lower() not in (".html", ".htm"):
        raise ValueError("Saved report input must have an .html or .htm extension")
    if source.stat().st_size > _MAX_REPORT_BYTES:
        raise ValueError("Saved HTML exceeds the 2 GiB report input limit")
    parser = _ProjectDataParser()
    decoder = codecs.getincrementaldecoder("utf-8-sig")()
    try:
        total = 0
        with source.open("rb") as stream:
            while chunk := stream.read(_READ_CHUNK_BYTES):
                total += len(chunk)
                if total > _MAX_REPORT_BYTES:
                    raise ValueError("Saved HTML exceeds the 2 GiB report input limit")
                parser.feed(decoder.decode(chunk))
                parser.flush_raw_text()
        parser.feed(decoder.decode(b"", final=True))
        parser.close()
        return parser.finish_document()
    finally:
        parser.release()


def upgrade_report(source: str | Path, output: str | Path, *, overwrite: bool = False, template=None, language=None) -> Path:
    """Rebuild a saved HTML with current assets and its unchanged data/state.

    No STAR session is needed. The output uses the current built-in layout or
    an explicitly selected local template pack, rather than executing old HTML.
    Existing files, including the source itself, require explicit overwrite.
    """
    target = Path(output).expanduser().resolve()
    if target.exists() and not overwrite:
        raise FileExistsError(f"output exists: {target}; choose a new path or use --force")
    return build_report(load_report_document(source), target, overwrite=overwrite, template=template, language=language)


def project_from_cases(cases: list[dict], title: str = "StarCapsule Studio") -> dict:
    """Keep each case's identity intact when assembling a comparison."""
    if not cases:
        raise ValueError("At least one case is required")
    for case in cases:
        validate_case(case)
    project = {
        "schema": "cfd-review-project", "version": 1, "title": title,
        "cases": copy.deepcopy(cases),
        "views": [{"caseId": case["id"], "state": None} for case in cases[:2]],
        "links": {"camera": True, "section": True, "field": True, "color": True},
        "notes": [],
    }
    return validate_project(project)


def _script(text: str) -> str:
    # HTML ends a script element even inside a JS string or comment.
    return re.sub(r"</script", lambda m: "<\\/" + m.group(0)[2:], text, flags=re.IGNORECASE)


def _json_payload(document):
    payload = json.dumps(document, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    payload = payload.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    return payload.replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")


def _utf8_size(text):
    # Bound temporary encoding buffers even for a near-limit scientific array.
    return sum(len(text[i:i + _READ_CHUNK_BYTES].encode("utf-8")) for i in range(0, len(text), _READ_CHUNK_BYTES))


def _json_fragments(document):
    """Stream JSON with the same numbers/escaping as the legacy text writer."""
    encoder = json.JSONEncoder(ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    pieces, count = [], 0
    for piece in encoder.iterencode(document):
        piece = (piece.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
                 .replace("\u2028", "\\u2028").replace("\u2029", "\\u2029"))
        pieces.append(piece)
        count += len(piece)
        if count >= _READ_CHUNK_BYTES:
            yield "".join(pieces)
            pieces, count = [], 0
    if pieces:
        yield "".join(pieces)


def _prepare_json_slot(document, *, compress=True, directory=None):
    """Spool a bounded plain/enveloped JSON slot without one giant string."""
    raw = tempfile.TemporaryFile(mode="w+b", dir=directory)
    raw_bytes = 0
    try:
        for fragment in _json_fragments(document):
            data = fragment.encode("utf-8")
            raw_bytes += len(data)
            if raw_bytes > _MAX_JSON_SLOT_BYTES:
                raise ValueError("Report JSON exceeds the 500 MiB output limit")
            raw.write(data)
        raw.seek(0)
        if not compress or raw_bytes < _COMPRESSION_THRESHOLD_BYTES:
            return raw, raw_bytes
        with tempfile.TemporaryFile(mode="w+b", dir=directory) as packed:
            with gzip.GzipFile(filename="", fileobj=packed, mode="wb", compresslevel=6, mtime=0) as writer:
                while block := raw.read(_READ_CHUNK_BYTES):
                    writer.write(block)
            raw.close()
            packed.seek(0)
            output = tempfile.TemporaryFile(mode="w+b", dir=directory)
            try:
                output.write((f'{{"schema":"cfd-review-compressed","version":1,"encoding":"gzip-base64",'
                              f'"decodedBytes":{raw_bytes},"chunks":[').encode("ascii"))
                first = True
                while block := packed.read(_BASE64_INPUT_BYTES):
                    if not first:
                        output.write(b",")
                    first = False
                    output.write(b'"' + base64.b64encode(block) + b'"')
                    if output.tell() + 2 > _MAX_JSON_SLOT_BYTES:
                        raise ValueError("Compressed report JSON exceeds the 500 MiB output limit")
                output.write(b"]}")
                output.seek(0)
                return output, raw_bytes
            except BaseException:
                output.close()
                raise
    except BaseException:
        raw.close()
        raise


def _slot_fragments(stream):
    stream.seek(0)
    decoder = codecs.getincrementaldecoder("utf-8")()
    while block := stream.read(_READ_CHUNK_BYTES):
        yield decoder.decode(block)
    tail = decoder.decode(b"", final=True)
    if tail:
        yield tail


@contextmanager
def _report_slots(document, *, directory=None):
    with ExitStack() as resources:
        case_slots = []
        bundle = any(case["data"]["meta"].get("comparison") for case in document["cases"])
        if len(document["cases"]) > 1:
            total = 0
            for case in document["cases"]:
                slot = _case_slot(case)
                recipe = slot.get("schema") == "cfd-review-composition"
                stream, size = _prepare_json_slot(slot, compress=not recipe, directory=directory)
                resources.enter_context(stream)
                if recipe and size > _MAX_COMPOSITION_RECIPE_BYTES:
                    raise ValueError("Composition recipe exceeds the 1 MiB output limit")
                total += size
                if total > _MAX_REPORT_BYTES:
                    raise ValueError("Report exceeds the 2 GiB output limit")
                case_slots.append(stream)
            bundle = bundle or total > _BUNDLE_THRESHOLD_BYTES
        if bundle:
            project = {"schema": "cfd-review-html-bundle", "version": 1,
                       "project": {key: value for key, value in document.items() if key != "cases"},
                       "cases": [{"id": case["id"], "elementId": f"cfd-case-data-{index}"}
                                 for index, case in enumerate(document["cases"])]}
        else:
            for stream in case_slots:
                stream.close()
            case_slots.clear()
            project = document
        primary, _ = _prepare_json_slot(project, directory=directory)
        resources.enter_context(primary)
        yield primary, case_slots


def _report_parts(document: dict, template=None, *, directory=None, language=None):
    """Yield the original template and separately bounded case data blocks."""
    if not isinstance(document, dict):
        raise ValueError("A report document must be a JSON object")
    if document.get("schema") == "cfd-review-case":
        document = project_from_cases([document], document.get("name", "CFD review"))
    validate_project(document)
    requested_language = language
    language = language if language is not None else document.get("ui", {}).get("language", "en")
    if language not in ("en", "zh-CN"):
        raise ValueError("Language must be en or zh-CN")
    # UI preferences own metadata only; no scientific mesh or field is copied.
    if requested_language is not None:
        document = {**document, "ui": {**document.get("ui", {}), "language": language}}
    if len(document["cases"]) > _MAX_REPORT_CASES:
        raise ValueError("Report exceeds the 32-case limit")
    assets = files("cfd_review").joinpath("assets")
    read = lambda name: assets.joinpath(name).read_text(encoding="utf-8")
    replacements = {
        "{{STUDIO_CSS}}": read("studio.css"),
        "{{FIELD_VIEWER_CSS}}": read("field-viewer.css"),
        "{{THREE_JS}}": _script("/*\n" + read("vendor/THREE_LICENSE.txt") + "\n*/\n" + read("vendor/three.min.js")),
        "{{ORBIT_CONTROLS_JS}}": _script(read("vendor/OrbitControls.js")),
        "{{FIELD_VIEWER_JS}}": _script(read("field-viewer.js")),
        "{{STUDIO_JS}}": _script(read("studio.js")),
    }
    custom=validate_template(template) if template is not None else None
    html = custom["html"] if custom and custom["html"] is not None else read("studio.html")
    def html_language(match):
        tag = re.sub(r'\s+lang\s*=\s*(["\']).*?\1', "", match[0], flags=re.I)
        return tag[:-1] + ' lang="' + language + '">'
    html = re.sub(r"<html\b[^>]*>", html_language, html, count=1, flags=re.I)
    boot = "正在打开离线三维工程…" if language == "zh-CN" else "Opening offline 3D workspace…"
    html = re.sub(r'(<p\b[^>]*class=["\']studio-boot["\'][^>]*>).*?(</p>)',
                  lambda match: match[1] + boot + match[2], html, count=1, flags=re.S)
    if custom:
        replacements["{{TEMPLATE_CSS}}"] = custom["css"]
        if "{{TEMPLATE_CSS}}" not in html:
            html=html.replace("</head>",'<style id="cfd-template-style">{{TEMPLATE_CSS}}</style></head>',1)
    # A template can style the shell, but cannot loosen the offline policy.
    html=re.sub(r'<meta\b[^>]*http-equiv\s*=\s*["\']content-security-policy["\'][^>]*>',"",html,flags=re.I)
    html=re.sub(r"<head\b[^>]*>",lambda m:m[0]+'\n<meta http-equiv="Content-Security-Policy" content="'+CSP+'">',html,count=1,flags=re.I)
    for key in (*replacements, "{{PROJECT_JSON}}"):
        if key not in html:
            raise ValueError(f"Report template is missing {key}")
    if html.count("{{PROJECT_JSON}}") != 1:
        raise ValueError("Report template must contain one project JSON hook")
    before, after = html.split("{{PROJECT_JSON}}")
    close = re.match(r"\s*</script\s*>", after, flags=re.I)
    if close is None:
        raise ValueError("Report project JSON hook must end inside its fixed script element")
    # Substitute only original template fragments. User text containing a hook
    # remains literal data. Case blocks are inserted after the fixed script end.
    substitute = lambda text: re.sub(r"\{\{[A-Z_]+\}\}", lambda match: replacements[match.group(0)], text)
    with _report_slots(document, directory=directory) as (primary, case_slots):
        yield substitute(before)
        yield from _slot_fragments(primary)
        yield after[:close.end()]
        for index, stream in enumerate(case_slots):
            yield f'\n<script id="cfd-case-data-{index}" type="application/json">'
            yield from _slot_fragments(stream)
            yield "</script>"
        yield substitute(after[close.end():])


def render_report(document: dict, template=None, *, language=None) -> str:
    """Return HTML as text; build_report streams large case blocks to disk."""
    return "".join(_report_parts(document, template=template, language=language))


def _write_parts(stream, parts):
    total = 0
    try:
        for part in parts:
            for index in range(0, len(part), _READ_CHUNK_BYTES):
                chunk = part[index:index + _READ_CHUNK_BYTES]
                total += len(chunk.encode("utf-8"))
                if total > _MAX_REPORT_BYTES:
                    raise ValueError("Report exceeds the 2 GiB output limit")
                stream.write(chunk)
    finally:
        close = getattr(parts, "close", None)
        if close is not None:
            close()


def build_report(document: dict, output: str | Path, *, overwrite: bool = False, template=None, language=None) -> Path:
    """Write one portable HTML file; never silently overwrite an existing file."""
    target = Path(output).expanduser().resolve()
    if target.suffix.lower() not in (".html", ".htm"):
        raise ValueError("Report output must have an .html or .htm extension")
    if target.exists() and not overwrite:
        raise FileExistsError(f"output exists: {target}; choose a new path or use --force")
    parts = _report_parts(document, template=template, directory=target.parent, language=language)
    target.parent.mkdir(parents=True, exist_ok=True)
    if not overwrite:
        created = False
        try:
            with target.open("x", encoding="utf-8", newline="\n") as stream:
                created = True
                _write_parts(stream, parts)
        except BaseException:
            if created:
                target.unlink(missing_ok=True)
            raise
    else:
        descriptor, temporary = tempfile.mkstemp(prefix=".cfd-report-", suffix=".tmp", dir=target.parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
                _write_parts(stream, parts)
            os.replace(temporary, target)
        finally:
            Path(temporary).unlink(missing_ok=True)
    return target
