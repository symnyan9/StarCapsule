"""Strict, dependency-free checks at the local file/browser trust boundary."""
from __future__ import annotations

import json
import math
import re
from datetime import datetime
from pathlib import Path


# JSON containers/metadata and dense CFD arrays have separate bounded costs.
# Keep these policies aligned with assets/studio.js; values are never reduced.
_JSON_STRUCTURE_LIMIT = 1_000_000
_JSON_NUMERIC_LIMIT = 160_000_000
_JSON_MAX_DEPTH = 40
_MESH_COORDINATE_LIMIT = 30_000_000
_MESH_INDEX_LIMIT = 90_000_000


def _fail(path, message):
    raise ValueError(f"{path}: {message}")


def _object(value, path):
    if not isinstance(value, dict):
        _fail(path, "expected an object")
    return value


def _text(value, path, maximum=2000):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        _fail(path, f"expected nonempty text (at most {maximum} characters)")
    return value


def _identifier(value, path):
    _text(value, path, 128)
    if value in {"__proto__", "prototype", "constructor"}:
        _fail(path, "unsafe identifier")
    return value


def _number(value, path):
    try:
        valid = not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)
    except OverflowError:
        valid = False
    if not valid:
        _fail(path, "expected a finite number")
    return value


def _json_guard(value):
    """Bound JSON structure and dense numeric data independently, without copying."""
    pending = [(iter((value,)), 0)]
    nodes = numeric_values = 0
    while pending:
        iterator, depth = pending[-1]
        try:
            item = next(iterator)
        except StopIteration:
            pending.pop()
            continue
        nodes += 1
        if nodes > _JSON_STRUCTURE_LIMIT:
            _fail("document", f"JSON structure limit exceeded ({nodes:,} > {_JSON_STRUCTURE_LIMIT:,} nodes); "
                  "reduce exported sections/layers or split cases")
        if depth > _JSON_MAX_DEPTH:
            _fail("document", f"JSON nesting depth limit exceeded ({depth} > {_JSON_MAX_DEPTH})")
        if isinstance(item, dict):
            if any(not isinstance(k, str) or k in {"__proto__", "prototype", "constructor"} for k in item):
                _fail("document", "unsafe/non-string object key")
            pending.append((iter(item.values()), depth + 1))
        elif isinstance(item, list):
            if item and all(type(v) in (int, float) for v in item):
                numeric_values += len(item)
                if numeric_values > _JSON_NUMERIC_LIMIT:
                    _fail("document", f"JSON numeric-data limit exceeded ({numeric_values:,} > "
                          f"{_JSON_NUMERIC_LIMIT:,} values); reduce export range/sections/layers or split cases")
                if depth + 1 > _JSON_MAX_DEPTH:
                    _fail("document", f"JSON nesting depth limit exceeded ({depth + 1} > {_JSON_MAX_DEPTH})")
                for v in item:
                    _number(v, "document")
            else:
                pending.append((iter(item), depth + 1))
        elif isinstance(item, (int, float)) and not isinstance(item, bool):
            _number(item, "document")
        elif item is not None and not isinstance(item, (str, bool)):
            _fail("document", "value is not JSON compatible")


def _range(value, path):
    if not isinstance(value, list) or len(value) != 2:
        _fail(path, "expected [minimum, maximum]")
    lo, hi = (_number(v, path) for v in value)
    if lo >= hi:
        _fail(path, "minimum must be less than maximum")


def _array(value, path):
    if not isinstance(value, list):
        _fail(path, "expected an array")
    return value


def _mesh(mesh, path, fields):
    _object(mesh, path)
    positions = _array(mesh.get("positions"), path + ".positions")
    indices = _array(mesh.get("indices"), path + ".indices")
    if len(positions) > _MESH_COORDINATE_LIMIT:
        _fail(path + ".positions", f"coordinate count {len(positions):,} exceeds {_MESH_COORDINATE_LIMIT:,}; "
              "reduce export range or split components")
    if len(indices) > _MESH_INDEX_LIMIT:
        _fail(path + ".indices", f"triangle-index count {len(indices):,} exceeds {_MESH_INDEX_LIMIT:,}; "
              "reduce export range or split components")
    if len(positions) < 9 or len(positions) % 3:
        _fail(path + ".positions", "expected flat XYZ coordinates for at least three vertices")
    vertices = len(positions) // 3
    if not indices or len(indices) % 3:
        _fail(path + ".indices", "expected triangle vertex indices")
    for v in positions:
        if abs(_number(v, path + ".positions")) > 3.402823466e38:
            _fail(path + ".positions", "outside Float32 display range")
    for v in indices:
        if isinstance(v, bool) or not isinstance(v, int) or not 0 <= v < vertices:
            _fail(path + ".indices", "index must be an integer within the vertex array")
    for i in range(0, len(indices), 3):
        if len(set(indices[i:i + 3])) != 3:
            _fail(path + ".indices", "triangle repeats a vertex index")
    for field in fields:
        values = _array(mesh.get(field), path + "." + field)
        if len(values) != vertices:
            _fail(path + "." + field, f"expected {vertices} per-vertex values")
        for v in values:
            if abs(_number(v, path + "." + field)) > 3.402823466e38:
                _fail(path + "." + field, "outside Float32 display range")
    return vertices


def validate_case(obj):
    """Validate and return a case unchanged; never repair/fill missing fields."""
    _json_guard(obj)
    _object(obj, "case")
    if obj.get("schema") != "cfd-review-case" or type(obj.get("version")) is not int or obj["version"] != 1:
        _fail("case", "expected cfd-review-case version 1")
    _identifier(obj.get("id"), "case.id")
    _text(obj.get("name"), "case.name", 300)
    data = _object(obj.get("data"), "case.data")
    meta = _object(data.get("meta"), "case.data.meta")
    _text(meta.get("title"), "meta.title", 300)
    _text(meta.get("source"), "meta.source", 12000)
    if "sourceSha256" in meta:
        if not isinstance(meta["sourceSha256"], str) or not re.fullmatch(r"[a-fA-F0-9]{64}", meta["sourceSha256"]):
            _fail("meta.sourceSha256", "expected a 64-digit SHA-256")
    elif "sourceKey" not in meta:
        _fail("meta", "sourceSha256 or sourceKey is required")
    if "sourceKey" in meta:
        _text(meta["sourceKey"], "meta.sourceKey", 300)
    if meta.get("units") != "m":
        _fail("meta.units", "viewer coordinates must use m; convert explicitly during packing")
    if _object(meta.get("axis"), "meta.axis").get("up") != "z":
        _fail("meta.axis.up", "version 1 requires z-up; convert explicitly during packing")
    for name in ("isDemo", "halfCar"):
        if type(meta.get(name)) is not bool:
            _fail("meta." + name, "expected true/false")
    if "mirrorAxis" in meta and meta["mirrorAxis"] not in ("x", "y", "z"):
        _fail("meta.mirrorAxis", "expected x, y or z")
    if "scalarMirror" in meta and type(meta["scalarMirror"]) is not bool:
        _fail("meta.scalarMirror", "expected true/false")
    if meta.get("scalarMirror") and (not meta["halfCar"] or meta.get("mirrorAxis") != "y"):
        _fail("meta.scalarMirror", "current viewer mirrors symmetric half-car data about y=0 only")
    ranges = _object(meta.get("ranges"), "meta.ranges")
    for field in ("Cp", "CpT"):
        _range(ranges.get(field), "meta.ranges." + field)
    _range(meta.get("surfaceRange"), "meta.surfaceRange")
    if "cptTransparentAbove" in meta:
        _number(meta["cptTransparentAbove"], "meta.cptTransparentAbove")
    if "symmetryDeclaration" in meta:
        declaration = _object(meta["symmetryDeclaration"], "meta.symmetryDeclaration")
        if (declaration.get("kind") != "user-confirmed-y0-half"
                or type(declaration.get("version")) is not int or declaration["version"] != 1
                or meta["halfCar"] is not True or meta.get("mirrorAxis") != "y"):
            _fail("meta.symmetryDeclaration", "expected an active user-confirmed Y=0 half-model declaration")
        _text(declaration.get("statement"), "meta.symmetryDeclaration.statement", 300)
        confirmed_at = _text(declaration.get("confirmedAt"), "meta.symmetryDeclaration.confirmedAt", 64)
        try:
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})", confirmed_at):
                raise ValueError("expected ISO timestamp with timezone")
            datetime.fromisoformat(confirmed_at.replace("Z", "+00:00"))
        except ValueError:
            _fail("meta.symmetryDeclaration.confirmedAt", "expected a valid ISO timestamp with timezone")
        original = _object(declaration.get("original"), "meta.symmetryDeclaration.original")
        if original.get("halfCar") is not False or type(original.get("mirrorAxisPresent")) is not bool:
            _fail("meta.symmetryDeclaration.original", "expected original non-half-model metadata and an axis-presence flag")
        if ("mirrorAxis" not in original
                or (original["mirrorAxisPresent"] and original["mirrorAxis"] not in ("x", "y", "z"))
                or (not original["mirrorAxisPresent"] and original["mirrorAxis"] is not None)):
            _fail("meta.symmetryDeclaration.original.mirrorAxis", "original axis must match its recorded presence")
    ids = set()
    parts = _array(data.get("parts"), "data.parts")
    if not parts and not data.get("layers"):
        _fail("data.parts", "at least one native surface or 3D layer is required")
    for i, part in enumerate(parts):
        path = f"data.parts[{i}]"
        _object(part, path)
        _identifier(part.get("id"), path + ".id")
        _text(part.get("name"), path + ".name", 300)
        if part["id"] in ids:
            _fail(path, "duplicate part/layer id")
        ids.add(part["id"])
        _mesh(part, path, [f for f in ("cp", "cpt") if f in part])
    previous = -math.inf
    common_fields = {"cp", "cpt"}
    for i, section in enumerate(_array(data.get("sections"), "data.sections")):
        path = f"data.sections[{i}]"
        _object(section, path)
        x = _number(section.get("x"), path + ".x")
        if x <= previous:
            _fail(path + ".x", "section X positions must be strictly increasing")
        previous = x
        fields = [f for f in ("cp", "cpt") if f in section]
        if not fields:
            _fail(path, "a section requires at least one of cp/cpt; missing values are never filled")
        _mesh(section, path, fields)
        common_fields.intersection_update(fields)
        # These are real X planes, not an arbitrary mesh assigned a frame label.
        if any(abs(section["positions"][j] - x) > max(1e-5, abs(x) * 1e-6)
               for j in range(0, len(section["positions"]), 3)):
            _fail(path + ".positions", "vertices do not lie on the declared X plane")
    if data["sections"] and not common_fields:
        _fail("data.sections", "all sections must share at least one Cp/CpT field for a continuous sweep")
    for i, layer in enumerate(_array(data.get("layers", []), "data.layers")):
        path = f"data.layers[{i}]"
        _object(layer, path)
        _identifier(layer.get("id"), path + ".id")
        _text(layer.get("name"), path + ".name", 300)
        if layer["id"] in ids:
            _fail(path, "duplicate part/layer id")
        ids.add(layer["id"])
        if layer.get("kind") not in ("isosurface", "section", "surface", "mesh"):
            _fail(path + ".kind", "expected an exported isosurface, section, surface or mesh layer")
        _mesh(layer, path, ["values"] if "values" in layer else [])
        if "values" in layer:
            _text(layer.get("field"), path + ".field", 128)
            _range(layer.get("colorRange"), path + ".colorRange")
        if "opacity" in layer and not 0 <= _number(layer["opacity"], path + ".opacity") <= 1:
            _fail(path + ".opacity", "expected a value between 0 and 1")
        if "visible" in layer and type(layer["visible"]) is not bool:
            _fail(path + ".visible", "expected true/false")
        if "threshold" in layer:
            _number(layer["threshold"], path + ".threshold")
    if "comparison" in meta:
        _validate_comparison(obj)
    return obj


def _validate_comparison(case):
    data, meta = case["data"], case["data"]["meta"]
    comparison = _object(meta["comparison"], "meta.comparison")
    if comparison.get("kind") != "half-car-stitch" or comparison.get("version") != 1:
        _fail("meta.comparison", "unknown comparison composition")
    if meta["halfCar"] or meta.get("scalarMirror"):
        _fail("meta.comparison", "a composed comparison must not be mirrored as a half model")
    sources = _array(comparison.get("sources"), "comparison.sources")
    if len(sources) != 2:
        _fail("comparison.sources", "exactly two original half-model sources are required")
    for i, source in enumerate(sources):
        _object(source, "comparison.source")
        _identifier(source.get("caseId"), "comparison.source.caseId")
        _text(source.get("sourceId"), "comparison.source.sourceId", 300)
        if (source.get("side") != ("A", "B")[i] or source.get("displayYSign") != (-1, 1)[i] or
                type(source.get("sourceYSide")) is not int or source["sourceYSide"] not in (-1, 1) or
                type(source.get("sourceYSign")) is not int or source["sourceYSign"] not in (-1, 1) or
                source["sourceYSide"] * source["sourceYSign"] != source["displayYSign"]):
            _fail("comparison.source", "invalid source side or Y reflection mapping")
    if sources[0]["caseId"] == sources[1]["caseId"] or case["id"] in [s["caseId"] for s in sources]:
        _fail("comparison.sources", "comparison sources must be two distinct original cases")
    lookup = {s["caseId"]: s for s in sources}
    def attributed(mesh):
        source = lookup.get(mesh.get("sourceCaseId"))
        if source is None or mesh.get("sourceSide") != source["side"] or mesh.get("sourceYSign") != source["sourceYSign"]:
            _fail("comparison.geometry", "geometry attribution differs from its source mapping")
        return source
    for kind, source_key in (("parts", "sourcePartId"), ("layers", "sourceLayerId")):
        for mesh in data.get(kind, []):
            attributed(mesh)
            _identifier(mesh.get(source_key), "comparison.geometry." + source_key)
    if comparison.get("sectionPolicy") != "common-x-no-interpolation":
        _fail("comparison.sectionPolicy", "only matching real X planes are supported")
    xs = _array(comparison.get("sourceSectionXs"), "comparison.sourceSectionXs")
    if len(xs) != 2 or any(not isinstance(row, list) or any(type(x) not in (float, int) or not math.isfinite(x) for x in row) for row in xs):
        _fail("comparison.sourceSectionXs", "expected two original X-coordinate sequences")
    state = comparison.get("sectionsStatus")
    if state not in ("shared", "no-common-x", "no-common-fields") or bool(data["sections"]) != (state == "shared"):
        _fail("comparison.sectionsStatus", "section availability differs from the composition status")
    for section in data["sections"]:
        spans = _array(section.get("comparisonRanges"), "comparison.section.comparisonRanges")
        cursor = 0
        if len(spans) != 2:
            _fail("comparison.section", "each common section requires both source halves")
        for side, span in enumerate(spans):
            source = attributed(span)
            count, start, index = span.get("vertexCount"), span.get("startVertex"), span.get("sourceSectionIndex")
            if (source != sources[side] or type(count) is not int or count < 3 or type(start) is not int or start != cursor or
                    type(index) is not int or not 0 <= index < len(xs[side]) or span.get("sourceX") != xs[side][index] or
                    abs(span["sourceX"] - section["x"]) > 1e-9 * max(1, abs(section["x"]), abs(span["sourceX"]))):
                _fail("comparison.section", "invalid vertex source range or unmatched original X plane")
            cursor += count
        if cursor != len(section["positions"]) // 3:
            _fail("comparison.section", "source vertex ranges must cover the complete section")
        split = spans[1]["startVertex"]
        for offset in range(0, len(section["indices"]), 3):
            if len({v < split for v in section["indices"][offset:offset + 3]}) != 1:
                _fail("comparison.section", "a triangle cannot connect different source cases")


def _vector3(value, path):
    if not isinstance(value, list) or len(value) != 3:
        _fail(path, "expected three finite coordinates")
    for v in value:
        if abs(_number(v, path)) > 3.402823466e38:
            _fail(path, "coordinate is outside the finite display range")


def validate_state(state, case, path="state"):
    """Check persisted viewer state before changing any report/viewer state."""
    _object(state, path)
    data = case["data"]
    meta, sections = data["meta"], data["sections"]
    source_id = meta.get("sourceSha256", meta.get("sourceKey"))
    if state.get("sourceId") != source_id:
        _fail(path + ".sourceId", "state source identity differs from its case")
    if "schema" in state and state["schema"] != "defense-field-viewer-state":
        _fail(path + ".schema", "unknown viewer state schema")
    if "version" in state and (type(state["version"]) is not int or state["version"] != 1):
        _fail(path + ".version", "expected viewer state version 1")
    if "camera" in state and state["camera"] is not None:
        camera = _object(state["camera"], path + ".camera")
        for key in ("position", "target"):
            _vector3(camera.get(key), path + ".camera." + key)
        if sum((a - b) ** 2 for a, b in zip(camera["position"], camera["target"])) < 1e-18:
            _fail(path + ".camera", "camera and target must differ")
    index = state.get("sectionIndex", 0)
    if "sectionIndex" in state:
        if type(index) is not int or (sections and not 0 <= index < len(sections)) or (not sections and index != 0):
            _fail(path + ".sectionIndex", "invalid real-section index")
    if "variable" in state:
        if state["variable"] not in ("Cp", "CpT"):
            _fail(path + ".variable", "expected Cp or CpT")
        if sections and not all(state["variable"].lower() in section for section in sections):
            _fail(path + ".variable", "field must be present throughout the real-section sequence")
    if "bodyMode" in state and state["bodyMode"] not in ("cp", "context", "hidden"):
        _fail(path + ".bodyMode", "unknown body display mode")
    if state.get("bodyMode") == "cp" and not any("cp" in p for p in data["parts"]):
        _fail(path + ".bodyMode", "surface Cp display needs at least one actual Cp field")
    part_ids = {p["id"] for p in data["parts"]}
    if "partSelection" in state:
        selected = _array(state["partSelection"], path + ".partSelection")
        if any(not isinstance(p, str) or p not in part_ids for p in selected) or len(selected) != len(set(selected)):
            _fail(path + ".partSelection", "unknown/duplicate selected part")
    for key in ("bodyOpacity", "sectionOpacity"):
        if key in state and not .05 <= _number(state[key], path + "." + key) <= 1:
            _fail(path + "." + key, "expected opacity between 0.05 and 1")
    for key in ("sectionVisible", "hideNearOne", "playing"):
        if key in state and type(state[key]) is not bool:
            _fail(path + "." + key, "expected true/false")
    if "cptTransparentAbove" in state:
        _number(state["cptTransparentAbove"], path + ".cptTransparentAbove")
    if "mirrorDisplay" in state:
        if type(state["mirrorDisplay"]) is not bool:
            _fail(path + ".mirrorDisplay", "expected true/false")
        if state["mirrorDisplay"]:
            # Reuse the same declared-half and one-sided geometry rule as composition.
            from .comparison import _side
            try:
                _side(case)
            except ValueError as error:
                _fail(path + ".mirrorDisplay", str(error))
    mirror_enabled = state.get("mirrorDisplay", bool(meta.get("halfCar")
        and meta.get("mirrorAxis") == "y" and meta.get("scalarMirror")))
    if "colorRanges" in state:
        ranges = _object(state["colorRanges"], path + ".colorRanges")
        _range(ranges.get("surfaceCp"), path + ".colorRanges.surfaceCp")
        section = _object(ranges.get("section"), path + ".colorRanges.section")
        for field in ("Cp", "CpT"):
            _range(section.get(field), path + ".colorRanges.section." + field)
    layers = {layer["id"]: layer for layer in data.get("layers", [])}
    if "layerSettings" in state:
        settings = _object(state["layerSettings"], path + ".layerSettings")
        for layer_id, setting in settings.items():
            if layer_id not in layers:
                _fail(path + ".layerSettings", "unknown layer id")
            _object(setting, path + ".layerSettings." + layer_id)
            if type(setting.get("visible")) is not bool:
                _fail(path + ".layerSettings", "layer visibility must be true/false")
            if not 0 <= _number(setting.get("opacity"), path + ".layerSettings.opacity") <= 1:
                _fail(path + ".layerSettings", "layer opacity must be between 0 and 1")
            if "colorRange" in setting:
                _range(setting["colorRange"], path + ".layerSettings.colorRange")
    selection = state.get("selection")
    if selection is not None:
        _object(selection, path + ".selection")
        if selection.get("kind") not in ("surface", "section", "layer"):
            _fail(path + ".selection.kind", "unknown picked geometry kind")
        if selection.get("method") != "native-triangle-barycentric-interpolation":
            _fail(path + ".selection.method", "unknown field interpolation method")
        if selection.get("value") is not None:
            _number(selection["value"], path + ".selection.value")
        for key in ("displayPoint", "sourcePoint"):
            _vector3(selection.get(key), path + ".selection." + key)
        if "mirrored" in selection and type(selection["mirrored"]) is not bool:
            _fail(path + ".selection.mirrored", "expected true/false")
        if selection.get("mirrored"):
            if not mirror_enabled:
                _fail(path + ".selection.mirrored", "mirrored picks require mirror display")
            expected = list(selection["displayPoint"])
            expected[1] *= -1
            if any(abs(a - b) > 1e-6 * max(1, abs(a), abs(b))
                   for a, b in zip(expected, selection["sourcePoint"])):
                _fail(path + ".selection", "mirrored source coordinates do not invert displayed Y")
        if selection["kind"] == "surface":
            part = next((p for p in data["parts"] if p["id"] == selection.get("partId")), None)
            if part is None or selection.get("field") != "Cp":
                _fail(path + ".selection", "unknown picked surface/field")
            if selection.get("value") is not None and selection["field"].lower() not in part:
                _fail(path + ".selection", "picked field is absent from the surface")
        elif selection["kind"] == "section":
            if not sections or selection.get("sectionIndex") != index or selection.get("field") != state.get("variable", "CpT"):
                _fail(path + ".selection", "picked section/field differs from saved view")
        else:
            layer = layers.get(selection.get("layerId"))
            expected_field = layer.get("field") if layer is not None and "values" in layer else None
            if layer is None or selection.get("field") != expected_field:
                _fail(path + ".selection", "unknown picked layer/field")
            if "values" not in layer and selection.get("value") is not None:
                _fail(path + ".selection", "geometry-only layer cannot have a scalar reading")
        if meta.get("comparison"):
            if selection["kind"] == "surface":
                owner = next(p for p in data["parts"] if p["id"] == selection["partId"])
            elif selection["kind"] == "layer":
                owner = layers[selection["layerId"]]
            else:
                owner = next((r for r in sections[index]["comparisonRanges"] if r["sourceCaseId"] == selection.get("sourceCaseId")), None)
            if owner is None or any(selection.get(k) != owner.get(k) for k in ("sourceCaseId", "sourceSide", "sourceYSign")):
                _fail(path + ".selection", "picked comparison source differs from its geometry")
            source = next(s for s in meta["comparison"]["sources"] if s["caseId"] == owner["sourceCaseId"])
            if selection.get("sourceDataId") != source["sourceId"]:
                _fail(path + ".selection", "picked original data identity differs from its source")
            for key in ("sourcePartId", "sourceLayerId", "sourceSectionIndex"):
                if key in owner and selection.get(key) != owner[key]:
                    _fail(path + ".selection", "picked original object differs from its geometry")
            expected = list(selection["displayPoint"])
            expected[1] *= owner["sourceYSign"]
            if any(abs(a - b) > 1e-6 * max(1, abs(a), abs(b)) for a, b in zip(expected, selection["sourcePoint"])):
                _fail(path + ".selection", "picked source coordinates do not invert the display Y mapping")
    return state


def validate_project(obj):
    _json_guard(obj)
    _object(obj, "project")
    if obj.get("schema") != "cfd-review-project" or type(obj.get("version")) is not int or obj["version"] != 1:
        _fail("project", "expected cfd-review-project version 1")
    _text(obj.get("title"), "project.title", 300)
    if "ui" in obj:
        ui = _object(obj["ui"], "project.ui")
        if "sidebarCollapsed" in ui and type(ui["sidebarCollapsed"]) is not bool:
            _fail("project.ui.sidebarCollapsed", "expected true/false")
        if "language" in ui and ui["language"] not in ("en", "zh-CN"):
            _fail("project.ui.language", "expected en or zh-CN")
    cases = _array(obj.get("cases"), "project.cases")
    if not 1 <= len(cases) <= 32:
        _fail("project.cases", "expected 1 to 32 cases")
    ids = set()
    for case in cases:
        validate_case(case)
        if case["id"] in ids:
            _fail("project.cases", "duplicate case id")
        ids.add(case["id"])
    by_id = {case["id"]: case for case in cases}
    for case in cases:
        if "comparison" in case["data"]["meta"]:
            _comparison_sources(case, by_id)
    views = _array(obj.get("views"), "project.views")
    if not 1 <= len(views) <= 2:
        _fail("project.views", "one or two views are required")
    for i, view in enumerate(views):
        _object(view, f"views[{i}]")
        if view.get("caseId") not in ids:
            _fail(f"views[{i}].caseId", "unknown case id")
        if view.get("state") is not None:
            validate_state(view["state"], next(c for c in cases if c["id"] == view["caseId"]), f"views[{i}].state")
    links = _object(obj.get("links"), "project.links")
    for key in ("camera", "section", "field", "color"):
        if type(links.get(key)) is not bool:
            _fail("project.links." + key, "expected true/false")
    note_ids = set()
    for i, note in enumerate(_array(obj.get("notes", []), "project.notes")):
        path = f"notes[{i}]"
        _object(note, path)
        _identifier(note.get("id"), path + ".id")
        _text(note.get("text"), path + ".text", 12000)
        if note["id"] in note_ids:
            _fail(path, "duplicate note id")
        note_ids.add(note["id"])
        if note.get("caseId") not in ids:
            _fail(path + ".caseId", "unknown case id")
        if type(note.get("view")) is not int or not 0 <= note["view"] < len(views):
            _fail(path + ".view", "unknown view index")
        validate_state(note.get("state"), next(c for c in cases if c["id"] == note["caseId"]), path + ".state")
    return obj


def _comparison_sources(case, by_id):
    """Verify display copies against retained originals, not just their labels."""
    data, comparison = case["data"], case["data"]["meta"]["comparison"]
    originals = {}
    for source in comparison["sources"]:
        original = by_id.get(source["caseId"])
        if original is None or original["data"]["meta"].get("comparison"):
            _fail("comparison.sources", "retain both original cases in the project")
        meta = original["data"]["meta"]
        if not meta["halfCar"] or source["sourceId"] != meta.get("sourceSha256", meta.get("sourceKey")):
            _fail("comparison.sources", "original case identity differs from the composition")
        for key in ("sourceSha256", "sourceKey"):
            if source.get(key) != meta.get(key):
                _fail("comparison.sources", "source provenance differs from the original case")
        from .comparison import _side
        if _side(original) != source["sourceYSide"]:
            _fail("comparison.sources", "recorded half side differs from the original geometry")
        originals[source["caseId"]] = original["data"]
    expected_references = [originals[s["caseId"]]["meta"].get("coefficientReference")
                           for s in comparison["sources"]]
    if comparison.get("coefficientReferences") != expected_references:
        _fail("comparison.sources", "coefficient reference records differ from the originals")
    def identical(mesh, original, sign, vertex_start=0, index_start=0):
        values = mesh["positions"]
        for j, value in enumerate(original["positions"]):
            if values[vertex_start * 3 + j] != (value * sign if j % 3 == 1 else value):
                _fail("comparison.geometry", "display vertices differ from their original Y reflection")
        expected = [v + vertex_start for i in range(0, len(original["indices"]), 3)
                    for v in (original["indices"][i], original["indices"][i + (2 if sign < 0 else 1)],
                              original["indices"][i + (1 if sign < 0 else 2)])]
        if mesh["indices"][index_start:index_start + len(expected)] != expected:
            _fail("comparison.geometry", "triangle topology differs from its original source")
    for kind, key in (("parts", "sourcePartId"), ("layers", "sourceLayerId")):
        expected_ids = {(case_id, mesh["id"]) for case_id, original in originals.items()
                        for mesh in original.get(kind, [])}
        actual_ids = [(mesh["sourceCaseId"], mesh[key]) for mesh in data.get(kind, [])]
        if set(actual_ids) != expected_ids or len(actual_ids) != len(expected_ids):
            _fail("comparison.geometry", "each original mesh must appear exactly once")
        for mesh in data.get(kind, []):
            original = next((m for m in originals[mesh["sourceCaseId"]].get(kind, []) if m["id"] == mesh[key]), None)
            if original is None or len(mesh["positions"]) != len(original["positions"]) or len(mesh["indices"]) != len(original["indices"]):
                _fail("comparison.geometry", "source mesh is absent or its dimensions differ")
            identical(mesh, original, mesh["sourceYSign"])
            for field in ("cp", "cpt", "values", "field", "units", "criterion", "threshold"):
                if mesh.get(field) != original.get(field):
                    _fail("comparison.geometry", "stored source scalar values or definitions were altered")
    for side, source in enumerate(comparison["sources"]):
        if comparison["sourceSectionXs"][side] != [s["x"] for s in originals[source["caseId"]]["sections"]]:
            _fail("comparison.sourceSectionXs", "original real X-plane sequence differs")
    for section in data["sections"]:
        offset = 0
        for span in section["comparisonRanges"]:
            original = originals[span["sourceCaseId"]]["sections"][span["sourceSectionIndex"]]
            start, count = span["startVertex"], span["vertexCount"]
            if count != len(original["positions"]) // 3:
                _fail("comparison.section", "source section vertex count differs")
            identical(section, original, span["sourceYSign"], start, offset)
            offset += len(original["indices"])
            for field in ("cp", "cpt"):
                if field in section and section[field][start:start + count] != original.get(field):
                    _fail("comparison.section", "source section scalars were altered or filled")
        if offset != len(section["indices"]):
            _fail("comparison.section", "unexpected triangle topology outside the source sections")


def load_document(path):
    """Load UTF-8 JSON and fail on duplicate object keys and NaN/Infinity."""
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"duplicate JSON object key: {key}")
            result[key] = value
        return result
    def constant(value):
        raise ValueError(f"non-finite JSON constant: {value}")
    with Path(path).open("r", encoding="utf-8-sig") as stream:
        obj = json.load(stream, object_pairs_hook=pairs, parse_constant=constant)
    if isinstance(obj, dict) and obj.get("schema") == "cfd-review-case":
        return validate_case(obj)
    return validate_project(obj)
