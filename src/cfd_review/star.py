"""Local STAR adapter preparation, compilation and owned read/export processes.

The proprietary SIM format is read only by STAR, never by this Python module.
Compiled API support is not evidence of a successful real-SIM export.
"""
from __future__ import annotations

import copy
import csv
from importlib import resources
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import tempfile
import time

from .mesh_io import pack_case, sha256


class CancelledError(ValueError):
    """The caller cancelled an owned read/export operation."""


def _check_cancelled(cancel_event):
    if cancel_event is not None and cancel_event.is_set():
        raise CancelledError("Operation cancelled")


def _write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def _java(value):
    # JSON's quoted text is valid Java text except raw non-ASCII; ASCII escaping
    # also makes templates portable across Windows compiler encodings.
    return json.dumps(str(value), ensure_ascii=True).replace("\\u2028", "\\u2028")


def find_star(explicit=None):
    candidate = explicit or os.environ.get("CFD_REVIEW_STAR") or shutil.which("starccm+")
    if candidate:
        path = Path(candidate).expanduser().resolve()
        if not path.is_file():
            raise ValueError("STAR executable not found; pass --star or CFD_REVIEW_STAR")
        return path
    # Fixed installation roots only; never scan user model libraries or drives.
    roots = [Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Siemens",
             Path("D:/Program Files/Siemens"), Path("C:/Program Files/CD-adapco")]
    for folder in roots:
        if folder.is_dir():
            for pattern in ("*/STAR-CCM+*/star/bin/starccm+.exe", "*/STAR-CCM+*/star/lib/*/*/lib/starccm+.exe", "*/STAR-CCM+*/star/bin/starccm+"):
                found = sorted(folder.glob(pattern), reverse=True)
                if found:
                    return found[0].resolve()
    return None


def _install_root(executable):
    for folder in Path(executable).resolve().parents:
        if (folder / "star/lib/java/platform").is_dir():
            return folder
    return None


def doctor(star=None):
    executable = find_star(star)
    install = _install_root(executable) if executable else None
    javac = None
    if install:
        # Some STAR bundles retain an older client JRE alongside the matching JDK.
        bundled_jdk = install.parent / "jdk"
        candidates = sorted(bundled_jdk.glob("**/bin/javac.exe"), reverse=True) if bundled_jdk.is_dir() else []
        candidates += [install / "jre/bin/javac.exe", install / "jre/bin/javac"]
        javac = next((p for p in candidates if p.is_file()), None)
    if not javac and shutil.which("javac"):
        javac = Path(shutil.which("javac"))
    return {"starExecutable": str(executable) if executable else None,
            "installRoot": str(install) if install else None,
            "javac": str(javac) if javac else None,
            "licenseChecked": False, "realSimRuntimeTested": False,
            "message": "Installation discovery only; no STAR process or license request was started."}


def _validate_config(config):
    if not isinstance(config, dict) or config.get("schema") != "cfd-review-star-config" or config.get("version") != 1:
        raise ValueError("expected cfd-review-star-config version 1")
    for key in ("id", "name", "representation"):
        if not isinstance(config.get(key), str) or not config[key].strip():
            raise ValueError(f"STAR config requires {key}")
    if not isinstance(config.get("meta"), dict):
        raise ValueError("STAR config requires explicit meta: units, axes, symmetry and coefficient references")
    surfaces, layers = config.get("surfaces", []), config.get("layers", [])
    if not isinstance(surfaces, list) or not isinstance(layers, list) or not (surfaces or layers):
        raise ValueError("STAR config requires at least one surface or existing derived-part layer")
    ids = set()
    for surface in surfaces:
        if not isinstance(surface, dict) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", surface.get("id", "")):
            raise ValueError("surface id must be a filename-safe identifier")
        if surface["id"] in ids:
            raise ValueError("duplicate surface id")
        ids.add(surface["id"])
        if not isinstance(surface.get("name"), str) or not surface["name"].strip():
            raise ValueError("surface requires name")
        if bool(surface.get("derivedPart")) == bool(surface.get("boundaries")):
            raise ValueError("surface requires exactly one of derivedPart or boundaries")
        for boundary in surface.get("boundaries", []):
            if not isinstance(boundary, dict) or not all(isinstance(boundary.get(k), str) and boundary[k] for k in ("region", "name")):
                raise ValueError("boundary requires exact region and name")
    for layer in layers:
        if not isinstance(layer, dict) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", layer.get("id", "")):
            raise ValueError("layer id must be a filename-safe identifier")
        if layer["id"] in ids:
            raise ValueError("duplicate surface/layer id")
        ids.add(layer["id"])
        for key in ("name", "derivedPart"):
            if not isinstance(layer.get(key), str) or not layer[key].strip():
                raise ValueError(f"layer requires exact {key}")
        if "fieldFunction" in layer and (not isinstance(layer["fieldFunction"], str) or not layer["fieldFunction"].strip()):
            raise ValueError("layer fieldFunction must be an exact scalar function name or omitted")
        if "field" in layer and (not isinstance(layer["field"], str) or not layer["field"].strip() or len(layer["field"])>128):
            raise ValueError("layer field must contain 1-128 characters")
        if "units" in layer and not isinstance(layer["units"], str):
            raise ValueError("layer units must be text")
        if layer.get("kind", "mesh") not in {"isosurface", "section", "surface", "mesh"}:
            raise ValueError("layer kind must describe a supported pre-exported surface mesh")
        if "colorRange" in layer:
            value=layer["colorRange"]
            if not isinstance(value,list) or len(value)!=2 or any(type(v) not in (int,float) or not math.isfinite(v) for v in value) or value[0]>=value[1]:
                raise ValueError("layer colorRange requires finite [minimum, maximum]")
        if "opacity" in layer and (type(layer["opacity"]) not in (int,float) or not math.isfinite(layer["opacity"]) or not 0<=layer["opacity"]<=1):
            raise ValueError("layer opacity must be between 0 and 1")
        if "visible" in layer and type(layer["visible"]) is not bool:
            raise ValueError("layer visible must be true/false")
        if "threshold" in layer and (type(layer["threshold"]) not in (int,float) or not math.isfinite(layer["threshold"])):
            raise ValueError("layer threshold must be finite")
        if "magnitudeOf" in layer and (not isinstance(layer["magnitudeOf"],str) or not layer["magnitudeOf"]):
            raise ValueError("magnitudeOf must name the inventoried source vector")
    sections = config.get("xSections", [])
    if not isinstance(sections, list) or any(type(x) not in (int, float) or not math.isfinite(x) for x in sections):
        raise ValueError("xSections must contain finite X positions in m")
    if any(a >= b for a, b in zip(sections, sections[1:])):
        raise ValueError("xSections must be strictly increasing")
    if sections and (not config.get("sectionRegions") or not all(isinstance(r, str) and r for r in config["sectionRegions"])):
        raise ValueError("xSections require explicit sectionRegions")
    fields = config.get("fields", {})
    if not isinstance(fields, dict) or any(k not in {"Cp", "CpT"} for k in fields) or ((surfaces or sections) and not fields):
        raise ValueError("surfaces and new X sections require at least one explicitly mapped Cp/CpT field")
    if not fields and not layers:
        raise ValueError("fields must explicitly map at least one of Cp/CpT or include existing layers")
    for name, field in fields.items():
        if not isinstance(field, dict) or bool(field.get("function")) == bool(field.get("expression")):
            raise ValueError(f"fields.{name} requires exactly one of function or expression")
        if not isinstance(field.get("function", field.get("expression")), str):
            raise ValueError(f"fields.{name}: expected text")
    # Coordinate orientation/scale of a SIM export is explicit and fixed here.
    # Arbitrary coordinate conversion belongs to the already-exported pack path.
    if config["meta"].get("units") != "m" or config["meta"].get("axis", {}).get("up") != "z":
        raise ValueError("STAR v1 export requires m, z-up; use explicit CSV/STL pack transformation otherwise")
    return config


def prepare_macro(config, output, operation="export"):
    """Write a runnable version-profile macro and pack config, without opening SIM."""
    if operation not in {"inspect", "export"}:
        raise ValueError("operation must be inspect or export")
    if operation == "export":
        _validate_config(config)
    output = Path(output).resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError("adapter output must be an empty directory; existing exports are preserved")
    output.mkdir(parents=True, exist_ok=True)
    raw = output / "raw"
    raw.mkdir()
    template = "ReviewInventory" if operation == "inspect" else "ReviewExport"
    code = resources.files("cfd_review").joinpath("star_macros", template + ".java.in").read_text(encoding="utf-8")
    code = code.replace("@@OUTPUT@@", _java(raw))
    expected = ["inventory.json"] if operation == "inspect" else []
    pack = None
    if operation == "export":
        code = code.replace("@@REPRESENTATION@@", _java(config["representation"]))
        field_lines = []
        field_columns = {}
        for field, definition in config.get("fields", {}).items():
            name = "CRS_" + field
            expression = definition.get("expression", "${" + definition.get("function", "") + "}")
            field_lines.append(f"fields.add(scalar({_java(name)}, {_java(expression)}));")
            if definition.get("function"):
                field_lines.append(f"reference({_java(definition['function'])});")
            field_columns[field] = name
        expected.append("references.json")
        body, parts, sections, layers = [], [], [], []
        for i, surface in enumerate(config.get("surfaces", [])):
            stem = "surface_" + surface["id"]
            if surface.get("derivedPart"):
                body.append(f"Part p{i} = sim.getPartManager().getPart({_java(surface['derivedPart'])});")
                body.append(f"if(p{i} == null) throw new IllegalArgumentException(\"Missing configured derived part\");")
                sources = f"Arrays.asList(p{i})"
            else:
                # A constant threshold wraps the exact selected boundary sources;
                # it cuts no scalar gradient and is not a surface remesher.
                names = ", ".join(f"boundary({_java(b['region'])}, {_java(b['name'])})" for b in surface["boundaries"])
                body.append(f"ThresholdPart p{i} = sim.getPartManager().createThresholdPart();")
                body.append(f"p{i}.getInputParts().setObjects(Arrays.asList({names}));")
                body.append(f"p{i}.setFieldFunction(allSurface); p{i}.setRange(new DoubleVector(new double[]{{0.5, 1.5}})); p{i}.setMode(ThresholdPart.BETWEEN);")
                sources = f"Arrays.asList({names})"
            body.append(f"exportPart(p{i}, {_java(stem)}, {sources});")
            entry={"id":surface["id"],"name":surface["name"],"stl":stem+".stl"}
            if field_columns:
                entry["csv"]=stem+".csv"; expected.append(stem+".csv")
            else:
                entry["fields"]={}
            parts.append(entry)
            expected.append(stem+".stl")
        for i, x in enumerate(config.get("xSections", [])):
            stem = f"section_{i:05d}"
            regions = ", ".join(f"region({_java(r)})" for r in config["sectionRegions"])
            body.extend([f"PlaneSection s{i} = sim.getPartManager().createPlaneSection();",
                         f"s{i}.getInputParts().setObjects(Arrays.asList({regions}));",
                         f"s{i}.setOrigin(new DoubleVector(new double[]{{{float(x)!r}, 0, 0}}));",
                         f"s{i}.setOrientation(new DoubleVector(new double[]{{1, 0, 0}}));",
                         f"exportPart(s{i}, {_java(stem)}, Arrays.asList(s{i}));"])
            sections.append({"x": x, "csv": stem + ".csv", "stl": stem + ".stl"})
            expected.extend([stem + ".csv", stem + ".stl"])
        for i, layer in enumerate(config.get("layers", [])):
            stem="layer_"+layer["id"]
            body.append(f"Part l{i} = sim.getPartManager().getPart({_java(layer['derivedPart'])});")
            body.append(f"if(l{i} == null || !meshPart(l{i})) throw new IllegalArgumentException(\"Configured layer is not a supported native surface part\");")
            selected=f"Collections.<FieldFunction>emptyList()"
            entry={k:copy.deepcopy(v) for k,v in layer.items() if k not in {"derivedPart","fieldFunction","magnitudeOf"}}
            entry.update(kind=layer.get("kind","mesh"),fields={},sourceDerivedPart=layer["derivedPart"])
            if layer.get("fieldFunction"):
                field_lines.append(f"FieldFunction lf{i}=existingScalar({_java(layer['fieldFunction'])},{_java(layer.get('magnitudeOf',''))});")
                field_lines.append(f"reference(lf{i});")
                entry.update(ensight=stem+".case",nativeMeta=stem+".meta.json",field=layer.get("field",layer["fieldFunction"]),
                             sourceFieldFunction=layer["fieldFunction"])
                body.append(f"exportJointPart(l{i}, {_java(stem)}, lf{i});")
                expected.extend([stem+".case",stem+".meta.json"])
            else:
                entry["stl"]=stem+".stl"
                body.append(f"exportPart(l{i}, {_java(stem)}, Arrays.asList(l{i}), {selected});")
                expected.append(stem+".stl")
            layers.append(entry)
        code = code.replace("@@FIELD_SETUP@@", "\n      ".join(field_lines))
        code = code.replace("@@EXPORT_BODY@@", "\n      ".join(body))
        pack = {"schema": "cfd-review-pack", "version": 1, "id": config["id"], "name": config["name"],
                "meta": copy.deepcopy(config["meta"]), "coordinateColumns": config.get("coordinateColumns", ["X (m)", "Y (m)", "Z (m)"]),
                "fields": field_columns, "tolerance": config.get("tolerance", 1e-6), "parts": parts, "sections": sections,"layers":layers}
        _write_json(raw / "pack-config.json", pack)
    macro = output / (template + ".java")
    macro.write_text(code, encoding="utf-8")
    result = {"operation": operation, "macro": str(macro), "rawDirectory": str(raw),
              "expectedFiles": expected, "apiProfile": "STAR-CCM+ 19.02.009", "runtimeValidated": False,
              "notes": "Compile against the target installation before execution; API compatibility alone does not validate exported fields."}
    _write_json(output / "adapter-plan.json", result)
    return result


def compile_macro(macro, star=None):
    environment = doctor(star)
    if not environment["installRoot"] or not environment["javac"]:
        raise ValueError("A STAR installation with javac is required for API compilation")
    install = Path(environment["installRoot"])
    java = install / "star/lib/java/platform"
    classpath = os.pathsep.join(str(java / p / "*") for p in ("modules/ext", "modules", "core", "lib"))
    macro = Path(macro).resolve()
    classes = macro.parent / "compiled"
    classes.mkdir(exist_ok=True)
    process = subprocess.run([environment["javac"], "-J-Duser.language=en", "-J-Duser.country=US",
                              "-encoding", "UTF-8", "-cp", classpath,
                              "-d", str(classes), str(macro)], capture_output=True,
                             text=True, encoding="utf-8", errors="replace", timeout=60)
    log = macro.parent / "compile.log"
    log.write_text(process.stdout + process.stderr, encoding="utf-8")
    result = {"compiled": process.returncode == 0, "returncode": process.returncode,
              "log": str(log), "apiProfile": "installation-local", "runtimeValidated": False}
    _write_json(macro.parent / "compile-receipt.json", result)
    if process.returncode:
        raise ValueError(f"STAR API compilation failed; see {log}")
    return result


def _native_output(raw):
    """Return a verified native-writer path and, if needed, an owned junction."""
    raw = Path(raw).resolve()
    if os.name != "nt" or str(raw).isascii():
        return str(raw), None
    import ctypes
    buffer = ctypes.create_unicode_buffer(32768)
    length = ctypes.windll.kernel32.GetShortPathNameW(str(raw), buffer, len(buffer))
    if 0 < length < len(buffer) and buffer.value.isascii() and os.path.samefile(buffer.value, raw):
        return buffer.value, None
    temporary_root = Path(os.environ.get("CFD_REVIEW_NATIVE_TEMP", tempfile.gettempdir())).resolve()
    if not str(temporary_root).isascii() or not temporary_root.is_dir():
        raise ValueError("Windows native STL export needs an existing ASCII temp directory; set CFD_REVIEW_NATIVE_TEMP")
    owned = Path(tempfile.mkdtemp(prefix="cfd-review-native-", dir=temporary_root))
    alias = owned / "data"
    environment = dict(os.environ, CFD_REVIEW_ALIAS=str(alias), CFD_REVIEW_ALIAS_TARGET=str(raw))
    # Values travel through environment strings, never interpolation into shell code.
    command = ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
               "New-Item -ItemType Junction -Path $env:CFD_REVIEW_ALIAS -Target $env:CFD_REVIEW_ALIAS_TARGET -ErrorAction Stop | Out-Null"]
    process = subprocess.run(command, env=environment, capture_output=True, timeout=30)
    if process.returncode or not alias.is_dir() or not os.path.samefile(alias, raw):
        if alias.exists():
            alias.rmdir()
        owned.rmdir()
        raise ValueError("Cannot create/verify the temporary ASCII native-output junction")
    return str(alias), owned


def _cleanup_native_output(native, owned, raw):
    if owned is None:
        return
    alias = Path(native)
    # Remove only our junction entry, never recursively traverse the real output.
    if alias.parent != owned or alias.name != "data" or not os.path.samefile(alias, raw):
        raise ValueError("Refusing cleanup of an unverified native-output alias")
    alias.rmdir()
    owned.rmdir()


def _execute_owned(command, cwd, log, timeout, environment=None, cancel_event=None):
    """Stop only this newly created process tree on timeout or cancellation."""
    _check_cancelled(cancel_event)
    options = {"start_new_session": True} if os.name != "nt" else {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    with Path(log).open("w", encoding="utf-8") as stream:
        process = subprocess.Popen(command, cwd=cwd, stdout=stream, stderr=subprocess.STDOUT, env=environment, **options)
        try:
            started = time.monotonic()
            samples = []
            low_physical_samples = 0
            while process.poll() is None:
                _check_cancelled(cancel_event)
                memory = memory_status()
                if memory:
                    samples.append(memory)
                    low_physical_samples = low_physical_samples + 1 if memory["availablePhysicalBytes"] < 192 * 1024 ** 2 else 0
                    if low_physical_samples >= 3 or memory["availableCommitBytes"] < 1536 * 1024 ** 2:
                        raise ValueError("Owned STAR stopped by memory guard (physical <192 MiB for 3 samples or commit <1.5 GiB)")
                if time.monotonic() - started >= timeout:
                    raise ValueError("Owned STAR export timed out")
                if cancel_event is None:
                    time.sleep(1)
                else:
                    cancel_event.wait(1)
            _check_cancelled(cancel_event)
            return process.returncode
        except (Exception, KeyboardInterrupt) as exc:
            if process.poll() is None:
                if os.name == "nt":
                    subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, timeout=20)
                else:
                    os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=20)
            error_type = CancelledError if isinstance(exc, CancelledError) else ValueError
            raise error_type(f"{exc}; only the owned process tree was stopped; see {log}") from exc
        finally:
            _write_json(Path(cwd) / "resource-samples.json", {"ownedPid": process.pid, "samples": samples})


def memory_status():
    """Windows commit/physical availability, with no third-party dependency."""
    if os.name != "nt":
        return None
    import ctypes
    class MemoryStatus(ctypes.Structure):
        _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong),
                    ("totalPhysical", ctypes.c_ulonglong), ("availablePhysical", ctypes.c_ulonglong),
                    ("totalPageFile", ctypes.c_ulonglong), ("availablePageFile", ctypes.c_ulonglong),
                    ("totalVirtual", ctypes.c_ulonglong), ("availableVirtual", ctypes.c_ulonglong),
                    ("availableExtendedVirtual", ctypes.c_ulonglong)]
    status = MemoryStatus()
    status.length = ctypes.sizeof(status)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        raise OSError("Cannot query available Windows memory before STAR export")
    return {"timeUtc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "availablePhysicalBytes": status.availablePhysical,
            "availableCommitBytes": status.availablePageFile}


def _resolve_native_layer_columns(pack, raw):
    """Bind native tables or joint metadata without guessing field values/units."""
    for layer in pack.get("layers", []):
        if layer.get("ensight"):
            meta=json.loads((raw/layer["nativeMeta"]).read_text(encoding="utf-8-sig"))
            if (meta.get("complete") is not True or meta.get("dataAtVerts") is not True or
                    meta.get("fieldFunction")!=layer.get("sourceFieldFunction") or
                    not isinstance(meta.get("internalUnitsSuffix"),str)):
                raise ValueError("Joint native layer lacks matching scalar/vertex export metadata")
            def unit(value):
                value=value.strip()
                if value.startswith("(") and value.endswith(")"):value=value[1:-1].strip()
                return "1"+value if value.startswith("/") else value
            actual=unit(meta.get("internalUnitsSuffix",""))
            if layer.get("units") and unit(layer["units"])!=actual:
                raise ValueError("Configured layer units differ from native field internal units")
            layer["units"]=actual
            layer["nativeAssociation"]={"format":"EnSight Gold","dataAtVerts":True,
                "fieldFunction":meta["fieldFunction"],"internalUnitsName":meta.get("internalUnitsName"),
                "internalUnitsSuffix":meta.get("internalUnitsSuffix"),"representation":meta.get("representation")}
            continue
        alias=layer.pop("nativeValueColumn",None)
        if not alias:
            continue
        with (raw/layer["csv"]).open("r",encoding="utf-8-sig",newline="") as stream:
            header=next(csv.reader(stream),[])
        candidates=[item.strip() for item in header if item.strip()==alias or
                    (item.strip().startswith(alias+" (") and item.strip().endswith(")"))]
        if len(candidates)!=1:
            raise ValueError(f"Native layer CSV does not have one unambiguous configured scalar column {alias!r}")
        column=candidates[0]
        units=column[len(alias)+2:-1] if column!=alias else ""
        if layer.get("units") and layer["units"]!=units:
            raise ValueError(f"Configured layer units {layer['units']!r} differ from actual CSV units {units!r}")
        layer["fields"]={"values":column}
        layer["units"]=units
        layer["sourceValueColumn"]=column


def _run(plan, sim, star=None, np=1, timeout=1800, cancel_event=None):
    _check_cancelled(cancel_event)
    sim = Path(sim).expanduser().resolve()
    if sim.suffix.lower() != ".sim" or not sim.is_file():
        raise ValueError("provide an existing saved STAR .sim file; .scm is not silently renamed")
    if type(np) is not int or np < 1:
        raise ValueError("np must be a positive integer")
    executable = find_star(star)
    if not executable:
        raise ValueError("No local STAR executable found; pass --star")
    output = Path(plan["macro"]).parent
    if output == sim.parent or sim in output.parents:
        raise ValueError("export output must be separate from the source SIM location")
    raw = Path(plan["rawDirectory"])
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout must be positive and finite")
    memory = memory_status()
    if memory and (memory["availablePhysicalBytes"] < 1024 ** 3 or memory["availableCommitBytes"] < max(6 * 1024 ** 3, sim.stat().st_size * 3)):
        raise ValueError("Insufficient initial memory: require >=1 GiB physical and >=6 GiB (or 3x SIM size) commit before opening STAR")
    _check_cancelled(cancel_event)
    before = {"sha256": sha256(sim), "size": sim.stat().st_size, "mtimeNs": sim.stat().st_mtime_ns}
    command = [str(executable), "-np", str(np), "-batch", plan["macro"], str(sim)]
    receipt = {"schema": "cfd-review-star-run", "version": 1, "operation": plan["operation"],
               "sourceBefore": before, "ownedProcess": True, "solved": False, "sourceSaved": False,
               "status": "running", "runtimeValidated": False, "startedUtc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    log = output / "star.log"
    case = None
    native, owned_alias = str(raw), None
    _write_json(output / "run-receipt.json", receipt)
    try:
        _check_cancelled(cancel_event)
        if plan["operation"] == "export":
            native, owned_alias = _native_output(raw)
            receipt["nativeOutput"] = {"aliasUsed": owned_alias is not None, "realDirectory": str(raw)}
        environment = dict(os.environ, CFD_REVIEW_NATIVE_OUTPUT=native)
        _check_cancelled(cancel_event)
        code = _execute_owned(command, str(output), log, timeout, environment, cancel_event)
        _check_cancelled(cancel_event)
        receipt["returncode"] = code
        if code:
            raise ValueError(f"STAR exited {code}; see {log}")
        completion_file = raw / "complete.json"
        if not completion_file.is_file():
            raise ValueError("STAR exit 0 had no completion receipt; export is incomplete")
        completion = json.loads(completion_file.read_text(encoding="utf-8-sig"))
        if completion.get("complete") is not True or completion.get("operation") != plan["operation"]:
            raise ValueError("invalid STAR completion receipt")
        if completion.get("iterationBefore") != completion.get("iterationAfter"):
            raise ValueError("STAR iteration changed during read-only operation")
        if any(not (raw / name).is_file() or not (raw / name).stat().st_size for name in plan["expectedFiles"]):
            raise ValueError("STAR completion is missing required output files")
        receipt["completion"] = completion
        _check_cancelled(cancel_event)
        if plan["operation"] == "inspect":
            inventory = json.loads((raw / "inventory.json").read_text(encoding="utf-8-sig"))
            if inventory.get("schema") != "cfd-review-star-inventory" or not isinstance(inventory.get("regions"), list):
                raise ValueError("invalid STAR inventory payload")
            receipt["inventory"] = inventory
        else:
            pack_file = raw / "pack-config.json"
            pack = json.loads(pack_file.read_text(encoding="utf-8"))
            pack["meta"]["sourceSha256"] = before["sha256"]
            pack["meta"]["isDemo"] = False
            pack["meta"]["exportProvenance"] = {"apiProfile": plan["apiProfile"], "iteration": completion["iterationAfter"],
                "fieldAssociation": "Native per-node fields: joint EnSight Gold for colored layers; vertex-associated tables for surfaces and new planes",
                "geometry": "Joint native surface connectivity for colored layers; native STL for other selected surfaces"}
            references = json.loads((raw / "references.json").read_text(encoding="utf-8-sig"))
            pack["meta"]["coefficientReference"] = {"configured": pack["meta"].get("coefficientReference"), "fromStar": references}
            _resolve_native_layer_columns(pack,raw)
            _write_json(pack_file, pack)
            case = pack_case(pack_file)
            _check_cancelled(cancel_event)
            receipt["case"] = "case.json"
        receipt["status"] = "complete"
        receipt["runtimeValidated"] = True
    except Exception as error:
        receipt["status"] = "cancelled" if isinstance(error, CancelledError) else "failed"
        receipt["error"] = str(error)
        raise
    finally:
        try:
            after = {"sha256": sha256(sim), "size": sim.stat().st_size, "mtimeNs": sim.stat().st_mtime_ns}
        except OSError as error:
            after = None
            receipt["sourceIdentityError"] = str(error)
        receipt["sourceAfter"] = after
        receipt["sourceUnchanged"] = before == after
        try:
            _cleanup_native_output(native, owned_alias, raw)
            receipt["nativeAliasCleaned"] = True
        except (OSError, ValueError) as error:
            receipt["nativeAliasCleanupError"] = str(error)
        if before != after:
            receipt["status"] = "source-changed"
            receipt["runtimeValidated"] = False
        elif cancel_event is not None and cancel_event.is_set():
            receipt["status"] = "cancelled"
            receipt["runtimeValidated"] = False
        elif case is not None and receipt["status"] == "complete":
            try:
                _write_json(output / "case.json", case)
            except OSError as error:
                receipt["status"] = "failed"
                receipt["runtimeValidated"] = False
                receipt["error"] = f"Cannot write verified case: {error}"
                _write_json(output / "run-receipt.json", receipt)
                raise
        _write_json(output / "run-receipt.json", receipt)
        if before != after:
            raise ValueError("Source SIM identity changed during export; result was not accepted")
        if receipt["status"] == "cancelled":
            raise CancelledError("Operation cancelled; source identity checks and run receipt were finalized")
    return receipt


def inspect_sim(sim, output, star=None, np=1, timeout=1800, run=False, compile_api=False, cancel_event=None):
    _check_cancelled(cancel_event)
    plan = prepare_macro({}, output, "inspect")
    if compile_api:
        plan["compilation"] = compile_macro(plan["macro"], star)
    _check_cancelled(cancel_event)
    return _run(plan, sim, star, np, timeout, cancel_event) if run else plan


def export_sim(config, output, star=None, np=1, timeout=1800, run=False, compile_api=False, cancel_event=None):
    _check_cancelled(cancel_event)
    if isinstance(config, (str, Path)):
        config_path = Path(config).resolve()
        config = json.loads(config_path.read_text(encoding="utf-8-sig"))
        if config.get("sim"):
            config["sim"] = str((config_path.parent / config["sim"]).resolve())
    plan = prepare_macro(config, output, "export")
    if compile_api:
        plan["compilation"] = compile_macro(plan["macro"], star)
    _check_cancelled(cancel_event)
    if run:
        if not config.get("sim"):
            raise ValueError("STAR config needs sim when --run is requested")
        return _run(plan, config["sim"], star, np, timeout, cancel_event)
    return plan
