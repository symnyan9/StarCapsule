"""Pack native joint mesh/fields or explicitly mapped CSV/STL, without guessing."""
from __future__ import annotations

import csv
import hashlib
import itertools
import json
import math
from pathlib import Path
import struct

from .schema import validate_case


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _finite(value, label):
    if isinstance(value, bool):
        raise ValueError(f"{label}: booleans are not physical numbers")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label}: not a number") from exc
    if not math.isfinite(number):
        raise ValueError(f"{label}: non-finite number")
    return number


def read_stl(path):
    """Return (flat XYZ, triangle indices); preserve every native triangle."""
    raw = Path(path).read_bytes()
    positions = []
    if len(raw) >= 84 and len(raw) == 84 + 50 * struct.unpack_from("<I", raw, 80)[0]:
        count = struct.unpack_from("<I", raw, 80)[0]
        for i in range(count):
            xyz = struct.unpack_from("<9f", raw, 84 + 50 * i + 12)
            positions.extend(xyz)
    else:
        try:
            lines = raw.decode("ascii").splitlines()
        except UnicodeDecodeError as exc:
            raise ValueError(f"{path}: malformed binary/ASCII STL") from exc
        facets = 0
        in_facet = False
        vertices = []
        for line in lines:
            tokens = line.strip().split()
            if not tokens:
                continue
            if tokens[0].lower() == "facet":
                if in_facet:
                    raise ValueError(f"{path}: nested STL facet")
                in_facet, vertices = True, []
            elif tokens[0].lower() == "vertex":
                if not in_facet or len(tokens) != 4:
                    raise ValueError(f"{path}: malformed STL vertex")
                vertices.extend(_finite(v, str(path)) for v in tokens[1:])
            elif tokens[0].lower() == "endfacet":
                if not in_facet or len(vertices) != 9:
                    raise ValueError(f"{path}: STL facet must contain three vertices")
                positions.extend(vertices)
                facets += 1
                in_facet = False
        if in_facet or not facets:
            raise ValueError(f"{path}: empty or incomplete STL")
    if not positions or any(not math.isfinite(v) for v in positions):
        raise ValueError(f"{path}: empty/non-finite STL geometry")
    return positions, list(range(len(positions) // 3))


def _transform(point, transform):
    config = transform or {}
    scale = _finite(config.get("scale", 1), "transform.scale")
    axes = config.get("axes", [0, 1, 2])
    signs = config.get("signs", [1, 1, 1])
    offset = config.get("offset", [0, 0, 0])
    if scale <= 0 or not isinstance(axes, list) or any(type(v) is not int for v in axes) or sorted(axes) != [0, 1, 2]:
        raise ValueError("transform: positive scale and axes permutation [0,1,2] required")
    if not isinstance(signs, list) or len(signs) != 3 or any(type(v) is not int or v not in (-1, 1) for v in signs):
        raise ValueError("transform.signs: expected three values in [-1,1]")
    if not isinstance(offset, list) or len(offset) != 3:
        raise ValueError("transform.offset: expected three offsets in destination m")
    return tuple(point[axes[i]] * scale * signs[i] + _finite(offset[i], "transform.offset") for i in range(3))


def _omit_zero_area(positions):
    """Omit only strictly zero-area source triangles; no tolerance/simplification."""
    kept, omitted = [], 0
    for i in range(0, len(positions), 9):
        a, b, c = positions[i:i+3], positions[i+3:i+6], positions[i+6:i+9]
        u, v = [b[j]-a[j] for j in range(3)], [c[j]-a[j] for j in range(3)]
        cross = [u[1]*v[2]-u[2]*v[1], u[2]*v[0]-u[0]*v[2], u[0]*v[1]-u[1]*v[0]]
        if all(x == 0 for x in cross):
            omitted += 1
        else:
            kept.extend(positions[i:i+9])
    if not kept:
        raise ValueError("STL has no nonzero-area triangles")
    return kept, omitted


def _field_value(row, definition, label):
    if isinstance(definition, str):
        column, definition = definition, {}
    elif isinstance(definition, dict) and isinstance(definition.get("column"), str):
        column = definition["column"]
    else:
        raise ValueError(f"{label}: field requires a column name or explicit coefficient conversion")
    if column not in row:
        raise ValueError(f"{label}: missing CSV column {column!r}; available: {list(row)}")
    value = _finite(row[column], label)
    convert = "referencePressure" in definition or "dynamicPressure" in definition
    if convert:
        if "referencePressure" not in definition or "dynamicPressure" not in definition:
            raise ValueError(f"{label}: coefficient conversion needs referencePressure and dynamicPressure")
        pref = _finite(definition["referencePressure"], label + ".referencePressure")
        qref = _finite(definition["dynamicPressure"], label + ".dynamicPressure")
        if qref <= 0:
            raise ValueError(f"{label}: dynamicPressure must be positive")
        value = (value - pref) / qref
    return value


def match_csv_to_stl(csv_path, stl_path, fields, transform=None,
                     coordinate_columns=None, tolerance=1e-6):
    """Nearest-coordinate match; ambiguous coincident scalar tuples are errors.

    No triangulation, averaging, nearest extrapolation or missing-value fill occurs.
    Tolerance is an explicit destination-coordinate distance in m.
    """
    tolerance = _finite(tolerance, "tolerance")
    if tolerance <= 0:
        raise ValueError("tolerance must be positive")
    coordinates = coordinate_columns or ["X (m)", "Y (m)", "Z (m)"]
    if not isinstance(coordinates, list) or len(coordinates) != 3 or len(set(coordinates)) != 3:
        raise ValueError("coordinateColumns requires three distinct column names")
    if not isinstance(fields, dict):
        raise ValueError("explicit scalar field mapping is required")
    if any(key not in {"Cp", "CpT", "values"} for key in fields):
        raise ValueError("supported packed scalar keys are Cp, CpT and values")
    # Spatial bins keep native million-point exports linear on normal meshes.
    bins = {}
    with Path(csv_path).open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames or len(set(reader.fieldnames)) != len(reader.fieldnames):
            raise ValueError(f"{csv_path}: empty or duplicate CSV header")
        reader.fieldnames = [header.strip() for header in reader.fieldnames]
        if len(set(reader.fieldnames)) != len(reader.fieldnames):
            raise ValueError(f"{csv_path}: duplicate CSV header after whitespace normalization")
        for line, row in enumerate(reader, 2):
            if None in row or any(v is None for v in row.values()):
                raise ValueError(f"{csv_path}:{line}: column count mismatch")
            if any(name not in row for name in coordinates):
                raise ValueError(f"{csv_path}: coordinate columns {coordinates!r} not found")
            point = _transform(tuple(_finite(row[c], f"{csv_path}:{line}:{c}") for c in coordinates), transform)
            values = tuple(_field_value(row, fields[key], f"{csv_path}:{line}:{key}") for key in fields)
            key = tuple(math.floor(v / tolerance) for v in point)
            bins.setdefault(key, []).append((point, values))
    if not bins:
        raise ValueError(f"{csv_path}: no data rows")
    raw_positions, raw_indices = read_stl(stl_path)
    raw_positions, omitted = _omit_zero_area(raw_positions)
    result = {"positions": [], "indices": [], **{key.lower() if key != "values" else key: [] for key in fields}}
    mapping = {}
    offsets = list(itertools.product((-1, 0, 1), repeat=3))
    for offset in range(0, len(raw_positions), 3):
        point = _transform(tuple(raw_positions[offset:offset + 3]), transform)
        key = tuple(math.floor(v / tolerance) for v in point)
        candidates = []
        for shift in offsets:
            for candidate, values in bins.get(tuple(key[i] + shift[i] for i in range(3)), ()):
                distance = sum((point[i] - candidate[i]) ** 2 for i in range(3))
                if distance <= tolerance ** 2:
                    candidates.append((distance, values))
        if not candidates:
            raise ValueError(f"{stl_path}: unmatched STL vertex {point}; tolerance={tolerance} m")
        minimum = min(item[0] for item in candidates)
        closest = [values for distance, values in candidates if abs(distance - minimum) <= max(1e-30, minimum * 1e-9)]
        if len(set(closest)) != 1:
            raise ValueError(f"{stl_path}: ambiguous coincident CSV values at {point}; export unambiguous vertex-associated data")
        values = closest[0]
        vertex_key = (point, values)
        if vertex_key not in mapping:
            mapping[vertex_key] = len(result["positions"]) // 3
            result["positions"].extend(point)
            for scalar, value in zip(fields, values):
                result[scalar.lower() if scalar != "values" else scalar].append(value)
        result["indices"].append(mapping[vertex_key])
    for i in range(0, len(result["indices"]), 3):
        if len(set(result["indices"][i:i + 3])) != 3:
            raise ValueError(f"{stl_path}: degenerate triangle after coordinate/field matching")
    result["provenance"] = {
        "csvSha256": sha256(csv_path), "stlSha256": sha256(stl_path),
        "coordinateColumns": coordinates, "fields": fields, "transform": transform or {},
        "matchingToleranceM": tolerance, "method": "native-stl-nearest-coordinate-no-averaging",
        "triangles": len(raw_indices) // 3,
        "omittedStrictZeroAreaTriangles": omitted,
    }
    return result


def pack_case(config, base_dir=None):
    """Read a cfd-review-pack config; all file paths are relative to its folder."""
    if isinstance(config, (str, Path)):
        path = Path(config).resolve()
        base_dir = path.parent
        config = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(config, dict) or config.get("schema") != "cfd-review-pack" or config.get("version") != 1:
        raise ValueError("expected cfd-review-pack version 1")
    base_dir = Path(base_dir or ".").resolve()
    def mesh(entry, field_mapping=None):
        if not isinstance(entry,dict):
            raise ValueError("each mesh requires an explicit native source")
        if entry.get("ensight"):
            from .ensight import read_case
            native=read_case(base_dir/entry["ensight"])
            if not native:
                raise ValueError("Joint EnSight export contains no supported surface parts")
            has_values=["values" in part for part in native]
            if any(has_values) and not all(has_values):
                raise ValueError("Joint EnSight parts do not share one complete per-node scalar")
            if entry.get("sourceFieldFunction") and not all(has_values):
                raise ValueError("Configured joint layer scalar is missing from a native part")
            variables={part.get("field") for part in native if "values" in part}
            if len(variables)>1:
                raise ValueError("Joint EnSight layer has multiple scalar identities")
            result={"positions":[],"indices":[]}
            if all(has_values):
                result["values"]=[]
                result["field"]=entry.get("field") or next(iter(variables))
            for part in native:
                offset=len(result["positions"])//3
                result["positions"].extend(part["positions"])
                result["indices"].extend(index+offset for index in part["indices"])
                if all(has_values):result["values"].extend(part["values"])
            transform=entry.get("transform",config.get("transform"))
            if transform:
                result["positions"]=[value for i in range(0,len(result["positions"]),3)
                    for value in _transform(result["positions"][i:i+3],transform)]
            result["provenance"]={"method":"native-ensight-gold-joint-surface-per-node-no-coordinate-matching",
                "transform":transform or {},"parts":[{"id":part.get("id"),"name":part.get("name"),
                "provenance":part.get("provenance",{})} for part in native]}
            visible_ranges=[part.get("provenance",{}).get("surfaceValueRange") for part in native]
            if all(visible_ranges):
                result["provenance"]["surfaceValueRange"]=[min(pair[0] for pair in visible_ranges),
                    max(pair[1] for pair in visible_ranges)]
            return result
        if not entry.get("stl"):
            raise ValueError("each mesh requires an stl file path")
        mapping = field_mapping if field_mapping is not None else entry.get("fields", config.get("fields"))
        if not entry.get("csv"):
            if mapping:
                raise ValueError("scalar mappings require a CSV; pure STL geometry must use fields: {}")
            source = base_dir / entry["stl"]
            positions, source_indices = read_stl(source)
            source_corner_count = len(source_indices)
            del source_indices
            positions, omitted = _omit_zero_area(positions)
            transform = entry.get("transform", config.get("transform"))
            converted, indices, vertices = [], [], {}
            for i in range(0, len(positions), 3):
                point = (_transform(positions[i:i+3], transform) if transform
                         else tuple(positions[i:i+3]))
                # Exact display-coordinate indexing, including signed zero. This
                # preserves triangle corners, not an inferred native shared topology.
                key = struct.pack("!3d", *point)
                index = vertices.get(key)
                if index is None:
                    index = len(converted) // 3
                    vertices[key] = index
                    converted.extend(point)
                indices.append(index)
            return {"positions": converted, "indices": indices,
                    "provenance": {"stlSha256": sha256(source), "transform": transform or {},
                                   "method": "native-stl-geometry-only", "triangles": source_corner_count//3,
                                   "sourceCornerCount": source_corner_count,
                                   "displayVertexCount": len(converted)//3,
                                   "displayTriangleCount": len(indices)//3,
                                   "indexingMethod": "exact-display-xyz-float64-bits-no-tolerance",
                                   "omittedStrictZeroAreaTriangles": omitted}}
        return match_csv_to_stl(
            base_dir / entry["csv"], base_dir / entry["stl"],
            mapping,
            entry.get("transform", config.get("transform")),
            entry.get("coordinateColumns", config.get("coordinateColumns")),
            entry.get("tolerance", config.get("tolerance", 1e-6)),
        )
    parts = []
    for entry in config.get("parts", []):
        parts.append({"id": entry["id"], "name": entry["name"], **mesh(entry)})
    sections = []
    for entry in config.get("sections", []):
        if not {"Cp", "CpT"}.intersection(entry.get("fields", config.get("fields", {}))):
            raise ValueError("sections require at least one explicit Cp/CpT mapping")
        sections.append({"x": entry["x"], **mesh(entry)})
    layers = []
    for entry in config.get("layers", []):
        keep = {k: v for k, v in entry.items() if k not in {"csv", "stl", "ensight", "nativeMeta", "fields", "coordinateColumns", "transform", "tolerance"}}
        layer={**keep, **mesh(entry)}
        if "values" in layer and "colorRange" not in layer:
            visible_range=layer["provenance"].get("surfaceValueRange")
            low,high=visible_range if visible_range else (min(layer["values"]),max(layer["values"]))
            padding=max(abs(low)*.01,1e-9) if low==high else 0
            layer["colorRange"]=[low-padding,high+padding]
            layer["provenance"]["displayRange"]={"method":"native-surface-node-values-min-max" if visible_range else
                "exported-values-min-max","constantFieldPadding":padding}
        layers.append(layer)
    # Metadata stays explicit: packing does not guess symmetry, axes or reference q.
    case = {"schema": "cfd-review-case", "version": 1, "id": config.get("id"),
            "name": config.get("name"), "data": {"meta": config.get("meta"),
            "parts": parts, "sections": sections, "layers": layers}}
    return validate_case(case)
