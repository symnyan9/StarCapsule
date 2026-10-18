"""Place two saved half-model datasets in one scene without changing source data.

This is a display composition of independent cases, never a new CFD solution.
Y reflection reverses triangle winding; scalar samples retain their source values.
"""
from __future__ import annotations

import copy
import math

from .schema import validate_case


def _identity(case):
    meta = case["data"]["meta"]
    return meta.get("sourceSha256", meta.get("sourceKey"))


def _side(case):
    meta, data = case["data"]["meta"], case["data"]
    if not meta["halfCar"] or meta.get("comparison") or meta.get("mirrorAxis", "y") != "y":
        raise ValueError("Half comparison requires two original Y=0 half-model cases")
    low, high = math.inf, -math.inf
    for mesh in data["parts"] + data.get("layers", []) + data["sections"]:
        for y in mesh["positions"][1::3]:
            low, high = min(low, y), max(high, y)
    tolerance = max(1e-7, max(abs(low), abs(high)) * 1e-6)
    if low < -tolerance and high > tolerance:
        raise ValueError("Half-model geometry crosses both Y sides; export its actual half geometry")
    if high > tolerance:
        return 1
    if low < -tolerance:
        return -1
    raise ValueError("Half-model geometry lies entirely on Y=0; its half side cannot be established")


def _reflect(mesh, sign):
    result = copy.deepcopy(mesh)
    result["positions"] = [v * sign if i % 3 == 1 else v for i, v in enumerate(mesh["positions"])]
    if sign < 0:
        result["indices"] = [v for i in range(0, len(mesh["indices"]), 3)
                             for v in (mesh["indices"][i], mesh["indices"][i + 2], mesh["indices"][i + 1])]
    return result


def compose_half_comparison(case_a, case_b, *, case_id=None, name=None):
    """Return an attributed A(-Y)/B(+Y) case; leave both inputs unchanged.

    Only floating-point-equivalent exported X planes and shared scalar fields
    form the sweep. Missing planes/fields are never interpolated or filled.
    Keep the two originals beside this derived case in a project document.
    """
    for case in (case_a, case_b):
        validate_case(case)
    if case_a["id"] == case_b["id"]:
        raise ValueError("Select two distinct source cases")
    for field in ("Cp", "CpT"):
        metas = [c["data"]["meta"] for c in (case_a, case_b)]
        labels = [m.get("fieldLabels", {}).get(field, field) for m in metas]
        units = [m.get("fieldUnits", {}).get(field, "") for m in metas]
        if labels[0] != labels[1] or units[0] != units[1]:
            raise ValueError(f"{field} display slots refer to different quantities or units")
    source_sides = [_side(case_a), _side(case_b)]
    cases = (case_a, case_b)
    sources = []
    parts, layers = [], []
    for index, case in enumerate(cases):
        letter, target = ("A", -1) if index == 0 else ("B", 1)
        sign = target * source_sides[index]
        source = {"side": letter, "caseId": case["id"], "caseName": case["name"],
                  "sourceId": _identity(case), "sourceYSide": source_sides[index],
                  "sourceYSign": sign, "displayYSign": target}
        for key in ("sourceSha256", "sourceKey"):
            if key in case["data"]["meta"]:
                source[key] = case["data"]["meta"][key]
        sources.append(source)
        for kind, output in (("parts", parts), ("layers", layers)):
            for number, mesh in enumerate(case["data"].get(kind, [])):
                result = _reflect(mesh, sign)
                result.update(id=f"{letter}-{'p' if kind == 'parts' else 'l'}-{number}",
                              name=(letter + " · " + mesh["name"])[:300],
                              sourceCaseId=case["id"], sourceSide=letter, sourceYSign=sign)
                result["sourcePartId" if kind == "parts" else "sourceLayerId"] = mesh["id"]
                output.append(result)
    a, b = case_a["data"]["sections"], case_b["data"]["sections"]
    pairs = []
    i = j = 0
    while i < len(a) and j < len(b):
        x, y = a[i]["x"], b[j]["x"]
        if abs(x - y) <= 1e-9 * max(1, abs(x), abs(y)):
            pairs.append((i, j))
            i, j = i + 1, j + 1
        elif x < y:
            i += 1
        else:
            j += 1
    common = {"cp", "cpt"}
    for i, j in pairs:
        common.intersection_update(a[i])
        common.intersection_update(b[j])
    sections = []
    if pairs and common:
        for i, j in pairs:
            section = {"x": a[i]["x"], "positions": [], "indices": [], "comparisonRanges": []}
            for field in sorted(common):
                section[field] = []
            for source, original, source_index in ((sources[0], a[i], i), (sources[1], b[j], j)):
                reflected = _reflect(original, source["sourceYSign"])
                start = len(section["positions"]) // 3
                count = len(reflected["positions"]) // 3
                section["positions"].extend(reflected["positions"])
                section["indices"].extend(v + start for v in reflected["indices"])
                for field in common:
                    section[field].extend(reflected[field])
                section["comparisonRanges"].append({"sourceCaseId": source["caseId"], "sourceSide": source["side"],
                    "sourceYSign": source["sourceYSign"], "sourceSectionIndex": source_index,
                    "sourceX": original["x"], "startVertex": start, "vertexCount": count})
            sections.append(section)
    state = "shared" if sections else "no-common-fields" if pairs else "no-common-x"
    case_id = case_id or f"half-stitch-{case_a['id'][:40]}-{case_b['id'][:40]}"
    name = name or (case_a["name"] + " ↔ " + case_b["name"])[:300]
    metas = [case["data"]["meta"] for case in cases]
    meta = {"title": name, "source": f"A: {case_a['name']} | B: {case_b['name']}",
            "sourceKey": "half-stitch:" + case_id, "units": "m", "axis": {"up": "z"},
            "isDemo": any(m["isDemo"] for m in metas), "halfCar": False, "scalarMirror": False,
            "ranges": {f: [min(m["ranges"][f][0] for m in metas), max(m["ranges"][f][1] for m in metas)]
                       for f in ("Cp", "CpT")},
            "surfaceRange": [min(m["surfaceRange"][0] for m in metas), max(m["surfaceRange"][1] for m in metas)],
            "comparison": {"kind": "half-car-stitch", "version": 1, "sources": sources,
                "sectionPolicy": "common-x-no-interpolation", "sectionsStatus": state,
                "sourceSectionXs": [[s["x"] for s in case["data"]["sections"]] for case in cases],
                "coefficientReferences": [copy.deepcopy(m.get("coefficientReference")) for m in metas]}}
    for key in ("fieldLabels", "fieldUnits"):
        if key in metas[0]:
            meta[key] = copy.deepcopy(metas[0][key])
    return validate_case({"schema": "cfd-review-case", "version": 1, "id": case_id, "name": name,
                          "data": {"meta": meta, "parts": parts, "sections": sections, "layers": layers}})
