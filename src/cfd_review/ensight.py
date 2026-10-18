"""Strict static EnSight Gold surface reader for native joint mesh/node exports.

Supports the exercised little-endian C Binary profile and ASCII equivalents,
off/assign IDs, tria3/quad4/nsided faces and explicitly omitted bar2 lines.
No coordinate matching, scalar filling, volume cells or transient interpolation.
"""
from __future__ import annotations

from array import array
import hashlib
import math
from pathlib import Path
import re
import sys


def _hash(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _local(root, name):
    if not name or "\\" in name or ":" in name or Path(name).is_absolute():
        raise ValueError("EnSight references must be relative local filenames")
    target = (root / name).resolve()
    if not target.is_relative_to(root) or not target.is_file():
        raise ValueError("EnSight reference is missing or escapes its case directory")
    return target


def _case(path):
    if path.stat().st_size > 1024 * 1024:
        raise ValueError("EnSight case header is unexpectedly large")
    sections, active = {}, None
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line in {"FORMAT", "GEOMETRY", "VARIABLE", "TIME"}:
            if line in sections:
                raise ValueError("Duplicate EnSight case section: " + line)
            sections[line], active = [], line
        elif active is None:
            raise ValueError("Unsupported EnSight case section")
        else:
            sections[active].append(line)
    if sections.get("FORMAT") != ["type: ensight gold"]:
        raise ValueError("Only EnSight Gold is supported")
    geometry = sections.get("GEOMETRY", [])
    if len(geometry) != 1 or not geometry[0].startswith("model:"):
        raise ValueError("One static EnSight geometry model is required")
    model = geometry[0].split(":", 1)[1].strip()
    if len(model.split()) != 1:
        raise ValueError("Time-set geometry references are unsupported")
    variables = sections.get("VARIABLE", [])
    if len(variables) > 1:
        raise ValueError("Only one per-node scalar variable is supported")
    variable = None
    if variables:
        match = re.fullmatch(r"scalar per node:\s+(.+?)\s+(\S+)", variables[0])
        if not match:
            raise ValueError("Only scalar per node association is supported")
        variable = (match[1], match[2])
    step, time_value = None, None
    if "TIME" in sections:
        values, time_lines = {}, []
        reading_times = False
        for line in sections["TIME"]:
            if reading_times:
                time_lines.extend(line.split())
            else:
                key, separator, value = line.partition(":")
                if not separator or key.strip() in values:
                    raise ValueError("Malformed/duplicate EnSight TIME property")
                key, value = key.strip(), value.strip()
                if key == "time values":
                    reading_times = True
                    time_lines.extend(value.split())
                else:
                    values[key] = value
        required = {"time set", "number of steps", "filename start number", "filename increment"}
        if set(values) != required or values["time set"] != "1" or values["number of steps"] != "1" or len(time_lines) != 1:
            raise ValueError("Only a single recorded EnSight time step is supported")
        try:
            step = int(values["filename start number"])
            increment = int(values["filename increment"])
            time_value = float(time_lines[0])
        except ValueError:
            raise ValueError("Invalid static EnSight TIME values") from None
        if step < 0 or increment <= 0 or not math.isfinite(time_value):
            raise ValueError("Invalid static EnSight TIME values")
    def resolve(name):
        groups = re.findall(r"\*+", name)
        if groups:
            if len(groups) != 1 or step is None:
                raise ValueError("A wildcard requires one explicit recorded step")
            token = groups[0]
            replacement = str(step).zfill(len(token))
            if len(replacement) != len(token):
                raise ValueError("EnSight step exceeds its filename wildcard width")
            name = name.replace(token, replacement)
        if "?" in name or "*" in name:
            raise ValueError("Unsupported EnSight filename pattern")
        return _local(path.parent, name)
    return resolve(model), ((variable[0], resolve(variable[1])) if variable else None), time_value


class _Reader:
    def __init__(self, path, binary=None):
        self.path = path
        self.stream = path.open("rb")
        if binary is None:
            binary = self.stream.read(80).startswith(b"C Binary")
            self.stream.seek(0)
        self.binary = binary
        self.tokens = []
        self.size = path.stat().st_size

    def close(self):
        self.stream.close()

    def label(self, optional=False):
        if self.tokens:
            raise ValueError("Unexpected extra EnSight numeric values")
        raw = self.stream.read(80) if self.binary else self.stream.readline()
        if not raw and optional:
            return None
        if not raw or (self.binary and len(raw) != 80):
            raise ValueError("Truncated EnSight label")
        try:
            return raw.decode("utf-8").strip(" \t\r\n\x00")
        except UnicodeDecodeError:
            raise ValueError("Invalid EnSight UTF-8/ASCII label") from None

    def numbers(self, count, kind):
        if type(count) is not int or not 0 <= count <= 100_000_000:
            raise ValueError("Invalid EnSight array count")
        if self.binary:
            size = count * 4
            if self.stream.tell() + size > self.size:
                raise ValueError("Truncated EnSight numeric array")
            result = array("i" if kind == "int" else "f")
            if result.itemsize != 4:
                raise ValueError("EnSight reader requires 32-bit array elements")
            result.frombytes(self.stream.read(size))
            if sys.byteorder != "little":
                result.byteswap()
        else:
            result = []
            convert = int if kind == "int" else float
            while len(result) < count:
                if not self.tokens:
                    raw = self.stream.readline()
                    if not raw:
                        raise ValueError("Truncated EnSight numeric array")
                    self.tokens = raw.split()
                    continue
                take = min(count - len(result), len(self.tokens))
                try:
                    result.extend(convert(v) for v in self.tokens[:take])
                except ValueError:
                    raise ValueError("Invalid EnSight numeric value") from None
                del self.tokens[:take]
        if kind != "int" and any(not math.isfinite(v) for v in result):
            raise ValueError("Non-finite EnSight value")
        return result

    def count(self, label, allow_zero=False):
        value = self.numbers(1, "int")[0]
        if value < (0 if allow_zero else 1) or value > 100_000_000:
            raise ValueError("Invalid EnSight " + label)
        return value


def _cross(a, b, c):
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _zero_triangle(a, b, c):
    u = [b[i] - a[i] for i in range(3)]
    v = [c[i] - a[i] for i in range(3)]
    return (u[1] * v[2] - u[2] * v[1] == 0 and u[2] * v[0] - u[0] * v[2] == 0
            and u[0] * v[1] - u[1] * v[0] == 0)


def _nonplanar_quad(points):
    from fractions import Fraction
    origin = [Fraction(value) for value in points[0]]
    a, b, c = [[Fraction(point[i]) - origin[i] for i in range(3)] for point in points[1:]]
    volume = (a[0] * (b[1] * c[2] - b[2] * c[1]) - a[1] * (b[0] * c[2] - b[2] * c[0])
              + a[2] * (b[0] * c[1] - b[1] * c[0]))
    return volume != 0


def _cross3(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def _dot3(a, b):
    return sum(x * y for x, y in zip(a, b))


def _verified_source_fan(face, points):
    """Find a source-order fan only if exact 3D intersections form a disk.

    Each triangle pair shares the pivot. Nonparallel planes intersect along a
    line: a common positive ray in both triangle cones is an extra intersection.
    Coplanar pairs are checked by their exact cone/edge orientations instead.
    """
    if not 3 <= len(face) <= 22 or len({tuple(p) for p in points}) != len(points):
        return None
    ratios = [[float(value).as_integer_ratio() for value in p] for p in points]
    denominator = max(d for p in ratios for _, d in p)
    # Float denominators are powers of two, so one common denominator maps
    # every input coordinate to an exact integer without rounding or scaling
    # the stored geometry. These integers are used only for predicates.
    exact = [tuple(num * (denominator // den) for num, den in p) for p in ratios]

    def in_cone(ray, a, b, normal):
        return _dot3(_cross3(ray, b), normal) >= 0 and _dot3(_cross3(a, ray), normal) >= 0

    for pivot in range(len(face)):
        order = list(range(pivot, len(face))) + list(range(pivot))
        origin = exact[pivot]
        vectors = [tuple(exact[i][j] - origin[j] for j in range(3)) for i in order]
        triangles = [(vectors[i], vectors[i + 1], _cross3(vectors[i], vectors[i + 1]))
                     for i in range(1, len(order) - 1)]
        if any(not any(normal) for _, _, normal in triangles):
            continue
        valid = True
        for i, (a, b, n1) in enumerate(triangles):
            for j in range(i + 1, len(triangles)):
                c, d, n2 = triangles[j]
                line = _cross3(n1, n2)
                if j == i + 1:
                    # Distinct planes share precisely their common edge.
                    # In the same plane, third corners must lie on opposite
                    # sides of that edge (consistent oriented normals).
                    overlap = not any(line) and _dot3(n1, n2) <= 0
                elif any(line):
                    overlap = any(in_cone(ray, a, b, n1) and in_cone(ray, c, d, n2)
                                  for ray in (line, tuple(-v for v in line)))
                else:
                    overlap = (in_cone(a, c, d, n2) or in_cone(b, c, d, n2)
                               or in_cone(c, a, b, n1) or in_cone(d, a, b, n1))
                if overlap:
                    valid = False
                    break
            if not valid:
                break
        if valid:
            indices = [face[k] for i in range(1, len(order) - 1)
                       for k in (order[0], order[i], order[i + 1])]
            return indices, pivot
    return None


def _oblique_projections(shifted, normal):
    """Bounded view directions; these never change polygon connectivity."""
    def cross(a, b):
        return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2],
                a[0] * b[1] - a[1] * b[0]]

    def project(direction):
        length = math.hypot(*direction)
        if length == 0:
            return None
        n = [v / length for v in direction]
        seed = [int(i == min(range(3), key=lambda j: abs(n[j]))) for i in range(3)]
        u = cross(n, seed)
        length = math.hypot(*u)
        u = [v / length for v in u]
        v = cross(n, u)
        return [(math.fsum(p[i] * u[i] for i in range(3)),
                 math.fsum(p[i] * v[i] for i in range(3))) for p in shifted]

    yield "oblique-newell", project(normal)
    # Source triangles only choose a view. Actual faces still undergo full
    # boundary validation and ear clipping; no fan tessellation is implied.
    for i in range(1, len(shifted) - 1):
        yield "oblique-source-triangle-" + str(i - 1), project(cross(shifted[i], shifted[i + 1]))
    for i in range(len(shifted)):
        a, b, c = shifted[i - 1], shifted[i], shifted[(i + 1) % len(shifted)]
        yield "oblique-corner-" + str(i), project(cross([b[j] - a[j] for j in range(3)],
                                                       [c[j] - b[j] for j in range(3)]))
    # Deterministic finite fallback, identified by index in the audit metadata.
    golden_angle = math.pi * (3 - math.sqrt(5))
    for i in range(512):
        z = 1 - 2 * (i + 0.5) / 512
        radius = math.sqrt(1 - z * z)
        direction = [radius * math.cos(i * golden_angle), radius * math.sin(i * golden_angle), z]
        yield "fixed-sphere-512-" + str(i), project(direction)


def _triangulate(face, positions, projection_counts=None, kind=None):
    """Ear-clip original polygon edges without new vertices or scalar samples."""
    points = [positions[3 * i:3 * i + 3] for i in face]
    if len(face) == 3:
        return ([], 1) if _zero_triangle(*points) else (list(face), 0)
    if len(face) > 2048:
        raise ValueError("EnSight polygon exceeds the bounded ear-clipping profile")
    # Remove only strictly coincident adjacent geometric corners. The full node
    # arrays remain intact; each removed corner corresponds to a zero-area ear.
    ring, duplicates = [], 0
    for index, point in enumerate(points):
        if ring and point == points[ring[-1]]:
            duplicates += 1
        else:
            ring.append(index)
    if len(ring) > 1 and points[ring[0]] == points[ring[-1]]:
        ring.pop()
        duplicates += 1
    if len(ring) < 3:
        return [], max(1, len(face) - 2)
    origin = points[ring[0]]
    shifted = [[points[i][j] - origin[j] for j in range(3)] for i in ring]
    normal = [math.fsum(a[(axis + 1) % 3] * b[(axis + 2) % 3] - a[(axis + 2) % 3] * b[(axis + 1) % 3]
                        for a, b in zip(shifted, shifted[1:] + shifted[:1])) for axis in range(3)]
    axis = max(range(3), key=lambda i: abs(normal[i]))
    if normal[axis] == 0:
        if all(_zero_triangle(points[ring[0]], points[ring[1]], points[i]) for i in ring[2:]):
            return [], len(face) - 2
        verified = _verified_source_fan([face[i] for i in ring], [points[i] for i in ring])
        if verified is None:
            raise ValueError("Cannot validate a nonzero-area EnSight polygon")
        indices, pivot = verified
        if projection_counts is not None:
            key = "verified-3d-source-order-fan-pivot-" + str(pivot)
            projection_counts[key] = projection_counts.get(key, 0) + 1
        return indices, duplicates
    def on(a, b, p):
        return _cross(a, b, p) == 0 and min(a[0], b[0]) <= p[0] <= max(a[0], b[0]) and min(a[1], b[1]) <= p[1] <= max(a[1], b[1])
    def intersects(a, b, c, d):
        ab_c, ab_d, cd_a, cd_b = _cross(a, b, c), _cross(a, b, d), _cross(c, d, a), _cross(c, d, b)
        return ((ab_c > 0 > ab_d or ab_d > 0 > ab_c) and (cd_a > 0 > cd_b or cd_b > 0 > cd_a)
                or on(a, b, c) or on(a, b, d) or on(c, d, a) or on(c, d, b))
    edges = list(zip(ring, ring[1:] + ring[:1]))
    def accepted(candidate):
        if candidate is None:
            return None
        candidate_area = math.fsum(candidate[a][0] * candidate[b][1] - candidate[b][0] * candidate[a][1]
                                   for a, b in edges)
        if candidate_area == 0:
            return None
        if any(intersects(candidate[a], candidate[b], candidate[c], candidate[d])
               for i, (a, b) in enumerate(edges) for c, d in edges[i + 1:]
               if len({a, b, c, d}) == 4):
            return None
        return candidate_area
    dominant = axis
    projection_key = None
    for axis in sorted(range(3), key=lambda i: abs(normal[i]), reverse=True):
        axes = [i for i in range(3) if i != axis]
        projected = {i: (points[i][axes[0]] - origin[axes[0]], points[i][axes[1]] - origin[axes[1]]) for i in ring}
        signed_area = accepted(projected)
        if signed_area is not None:
            projection_key = "xyz"[axis]
            break
    else:
        # Noncoplanar four-point boundaries cannot have intersecting opposite
        # edges. Their two triangle planes intersect only on the shared diagonal.
        # Exact rational arithmetic is restricted to this rare quad fallback.
        if kind == "quad4" and len(face) == 4 and _nonplanar_quad(points):
            if projection_counts is not None:
                key = "nonplanar-quad-diagonal-rule"
                projection_counts[key] = projection_counts.get(key, 0) + 1
            return [face[0], face[1], face[2], face[0], face[2], face[3]], 0
        for projection_key, candidate in _oblique_projections(shifted, normal):
            projected = None if candidate is None else dict(zip(ring, candidate))
            signed_area = accepted(projected)
            if signed_area is not None:
                break
        else:
            verified = _verified_source_fan([face[i] for i in ring], [points[i] for i in ring])
            if verified is None:
                raise ValueError("Cannot validate an EnSight polygon (bounded projections and exact 3D fans exhausted)")
            indices, pivot = verified
            if projection_counts is not None:
                key = "verified-3d-source-order-fan-pivot-" + str(pivot)
                projection_counts[key] = projection_counts.get(key, 0) + 1
            return indices, duplicates
    sign = 1 if signed_area > 0 else -1
    if projection_counts is not None:
        projection_counts[projection_key] = projection_counts.get(projection_key, 0) + 1
        if projection_key != "xyz"[dominant]:
            projection_counts["nonDominantFallback"] = projection_counts.get("nonDominantFallback", 0) + 1
    triangles = []
    while len(ring) > 3:
        for k, current in enumerate(ring):
            previous, following = ring[k - 1], ring[(k + 1) % len(ring)]
            a, b, c = projected[previous], projected[current], projected[following]
            if sign * _cross(a, b, c) <= 0:
                continue
            if any(sign * _cross(a, b, projected[v]) >= 0 and sign * _cross(b, c, projected[v]) >= 0
                   and sign * _cross(c, a, projected[v]) >= 0 for v in ring if v not in (previous, current, following)):
                continue
            triangles.extend((face[previous], face[current], face[following]))
            del ring[k]
            break
        else:
            raise ValueError("Cannot safely triangulate EnSight polygon")
    final = [face[i] for i in ring]
    if _zero_triangle(*(positions[3 * i:3 * i + 3] for i in final)):
        duplicates += 1
    else:
        triangles.extend(final)
    return triangles, duplicates


def _geometry(path):
    reader = _Reader(path)
    try:
        if reader.binary:
            if reader.label() != "C Binary":
                raise ValueError("Unsupported EnSight binary profile")
            reader.label()
        else:
            reader.label()
        reader.label()
        for label in ("node", "element"):
            if reader.label() not in (label + " id off", label + " id assign"):
                raise ValueError("Only off/assign EnSight node and element IDs are supported")
        parts, ids = [], set()
        tag = reader.label(optional=True)
        while tag is not None:
            if tag != "part":
                raise ValueError("Expected EnSight part, found " + tag)
            part_id = reader.count("part ID")
            if part_id in ids:
                raise ValueError("Duplicate EnSight part ID")
            ids.add(part_id)
            name = reader.label()
            if reader.label() != "coordinates":
                raise ValueError("Expected EnSight coordinates")
            count = reader.count("node count")
            coordinates = reader.numbers(count * 3, "float")
            positions = [float(coordinates[axis * count + i]) for i in range(count) for axis in range(3)]
            del coordinates
            indices, elements, omitted, zero, projections = [], {}, {}, 0, {}
            tag = reader.label(optional=True)
            while tag is not None and tag != "part":
                if tag not in {"bar2", "tria3", "quad4", "nsided"}:
                    raise ValueError("Unsupported EnSight surface element type: " + tag)
                number = reader.count("element count", allow_zero=True)
                elements[tag] = elements.get(tag, 0) + number
                sizes = reader.numbers(number, "int") if tag == "nsided" else None
                width = {"bar2": 2, "tria3": 3, "quad4": 4}.get(tag)
                if sizes is not None and any(n < 3 or n > 2048 for n in sizes):
                    raise ValueError("Invalid/beyond-profile EnSight polygon size")
                connectivity = reader.numbers(sum(sizes) if sizes is not None else number * width, "int")
                if any(v < 1 or v > count for v in connectivity):
                    raise ValueError("EnSight connectivity references a missing node")
                if tag == "bar2":
                    omitted[tag] = omitted.get(tag, 0) + number
                else:
                    cursor = 0
                    for face_index in range(number):
                        n = sizes[face_index] if sizes is not None else width
                        face = [int(v) - 1 for v in connectivity[cursor:cursor + n]]
                        try:
                            triangles, skipped = _triangulate(face, positions, projections, tag)
                        except ValueError as error:
                            points = [positions[3 * v:3 * v + 3] for v in face]
                            raise ValueError(f"{error}; nativePartId={part_id}, elementType={tag}, "
                                             f"faceOrdinal={face_index + 1}, nodeIds={[v + 1 for v in face]}, "
                                             f"points={points}") from error
                        indices.extend(triangles)
                        zero += skipped
                        cursor += n
                del connectivity
                tag = reader.label(optional=True)
            if not indices:
                raise ValueError("EnSight part contains no nonzero-area surface triangles")
            used = bytearray(count)
            for index in indices:
                used[index] = 1
            parts.append({"id": str(part_id), "name": name, "positions": positions, "indices": indices,
                          "_used": used, "provenance": {"nativePartId": part_id, "sourceNodeCount": count,
                          "surfaceNodeCount": sum(used), "unusedNodeCount": count - sum(used),
                          "sourceElementCounts": elements, "omittedNonSurfaceElements": omitted,
                          "omittedStrictZeroAreaTriangles": zero, "triangles": len(indices) // 3,
                          "projectionAxisCounts": projections,
                          "obliqueProjectionRule": "newell/source-triangle/corner-normals-then-512-fibonacci-sphere; full-original-boundary-validation",
                          "fixedSphereCandidateRule": "i=0..511; z=1-2*(i+0.5)/512; phi=i*pi*(3-sqrt(5)); x/y=sqrt(1-z*z)*cos/sin(phi)",
                          "threeDimensionalFallbackRule": "at-most-22-source-corners; exact-integer-plane-and-positive-cone-intersections-for-all-triangle-pairs; no-new-vertices",
                          "triangulationMethod": "native-face-connectivity-validated-projection-ear-clipping-or-exact-3d-verified-source-order-triangulation-no-new-vertices"}})
        if not parts:
            raise ValueError("Empty EnSight surface geometry")
        return parts, reader.binary
    finally:
        reader.close()


def _scalar(path, parts, binary):
    reader = _Reader(path, binary=binary)
    try:
        description = reader.label()
        if description == "C Binary":
            description = reader.label()
        by_id, seen = {int(p["id"]): p for p in parts}, set()
        tag = reader.label(optional=True)
        while tag is not None:
            if tag != "part":
                raise ValueError("Expected per-node EnSight scalar part")
            part_id = reader.count("scalar part ID")
            if part_id not in by_id or part_id in seen:
                raise ValueError("Missing/duplicate/mismatched EnSight scalar part ID")
            seen.add(part_id)
            part = by_id[part_id]
            if reader.label() != "coordinates":
                raise ValueError("Only per-node EnSight scalar coordinates are supported")
            part["values"] = list(reader.numbers(part["provenance"]["sourceNodeCount"], "float"))
            part["provenance"]["scalarDescription"] = description
            visible_values = (value for value, used in zip(part["values"], part["_used"]) if used)
            low = high = next(visible_values)
            for value in visible_values:
                low, high = min(low, value), max(high, value)
            part["provenance"]["surfaceValueRange"] = [low, high]
            tag = reader.label(optional=True)
        if seen != set(by_id):
            raise ValueError("EnSight scalar omits a geometry part")
    finally:
        reader.close()


def read_case(case_path):
    """Read one native snapshot; return meshes sharing original node association.

    Units are intentionally absent: the caller supplies actual native field units.
    All native nodes/values are retained, including unused line-only nodes. The
    provenance records unused counts and the scalar range on visible face nodes.
    """
    path = Path(case_path).expanduser().resolve()
    geometry, scalar, time_value = _case(path)
    parts, binary = _geometry(geometry)
    if scalar is not None:
        field, scalar_path = scalar
        _scalar(scalar_path, parts, binary)
    source = {"caseSha256": _hash(path), "geometrySha256": _hash(geometry),
              "method": "native-ensight-gold-joint-node-associated-surface-export",
              "format": "c-binary-little-endian" if binary else "ascii", "recordedTime": time_value,
              "coordinateStorage": "native-binary32" if binary else "native-ascii"}
    if scalar is not None:
        source["scalarSha256"] = _hash(scalar_path)
        source["scalarStorage"] = "native-binary32" if binary else "native-ascii"
    for part in parts:
        part.pop("_used")
        part["provenance"].update(source)
        if scalar is not None:
            part["field"] = field
    return parts
