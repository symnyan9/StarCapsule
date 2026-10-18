# Local STAR adapter

## Native desktop workflow

Run `cfd-review-gui` in the installed environment, use the local installation's `Launch.cmd`, or double-click `Open Studio.cmd` in a source checkout. The interface selects a solved `.sim`, inventories the saved state, selects exact source objects and exports a standalone HTML. It uses the same adapter and validation as the CLI; no manual JSON editing is required.

The desktop window provides:

- **边界表面**: explicit surface-boundary selection, including available non-wall boundaries. Choose vehicle walls for body Cp. Boundaries start unselected; region/name pairs remain distinct.
- **已有后处理**: mesh-capable derived faces grouped by referencing scenes, with existing scalar coloring or geometry-only display. Select real parts rather than an empty Scene placeholder.
- **真实 X 截面**: optional new source-evaluated X planes, selected fluid regions and an explicit count/list. Verified selected-wall bounds initialize start/end; manual edits persist and the reset button restores those bounds. Wake layers do not extend vehicle length.
- Local output and template selection, background status, cancellation of the owned process, result opening and access to the most recent task directory.

Changing or re-reading a source clears previous inventory selections and geometric assumptions. A failed re-read cannot re-enable an old selection. Existing HTML files are preserved; choose a new destination filename.

The GUI defaults to `np=2`; CLI `inspect`/`export` default to one rank. Process count can be edited, but more ranks do not guarantee sufficient memory or faster postprocessing.

## Prerequisites and source protection

- Python 3.10+; Tkinter is needed for the desktop window.
- A compatible, licensed local STAR-CCM+ installation and a saved `.sim` containing the required mesh/solution fields.
- Sufficient physical/commit memory, disk space and any required license-server connection.
- Metres, X section planes and Z up for this native profile. Other coordinates require an explicit CSV/STL packing transform.

The current Java API profile is **STAR-CCM+ 19.02.009**. `doctor` discovers installation/JDK paths without opening a SIM or requesting a license. Select an installation with `--star "PATH_TO_STAR_EXECUTABLE"`, the GUI picker or `CFD_REVIEW_STAR`.

Only STAR reads the proprietary SIM. The owned export session does not solve, remesh, initialize, clear or save it. Actual runs compare source SHA256, size and modification time and record saved iteration checks. They do not interfere with unrelated STAR sessions. A portable HTML never starts STAR.

## Inventory and automatic X bounds

```powershell
python run.py inspect "YOUR_SOLVED_CASE.sim" --output inventory --compile --run
```

`inventory/raw/inventory.json` contains exact regions, boundaries, representations, fields, scenes and derived-part names. `representationDetails` adds the exact source name, native class, finite-volume status, cell count and export eligibility. The desktop lists only populated finite-volume representations, prefers `Volume Mesh`, and preserves exact raw names behind Chinese labels. Missing details require another inventory; source names alone do not establish eligibility. A populated mesh does not prove convergence. `boundaryDetails` includes native coordinate bounds when available. `derivedPartDetails` identifies the source type, mesh-export eligibility and accessible source criteria/thresholds or plane properties. `sceneDetails` records concrete displayer inputs and available scalar references; this is data selection, not a copy of a Scene's camera, lights or annotations.

Field inventory includes available scalar functions and vector-magnitude functions with their source-vector identity. Failed or unavailable getters remain absent/error-marked rather than acquiring guessed coordinates or values. Derived-part bounds are deferred to avoid evaluating every Q/threshold surface during inventory. Selected parts are evaluated during their actual export.

The desktop initializes X limits from selected wall bounds in metres. With only derived faces selected, it can use their bounds if already present; otherwise select relevant vehicle walls or enter coordinates. A partial vehicle selection describes that selection, not the whole car. A single fixed-X plane has no length interval and remains a prompt to expand the range explicitly.

Existing Scenes are optional for newly selected walls and X planes. Every object/field selection is exact, including case and whitespace. The adapter does not infer a vehicle wall from a name or invent missing solution fields.

## Wall surfaces and new X planes

Copy `examples/star-config.example.json` and replace its source path, metadata, exact field names, selected boundaries, fluid regions and X coordinates. Relative paths resolve against the configuration directory. Example limits and coordinates are display/format examples, not engineering recommendations.

```powershell
# Prepare and compile without opening the source.
python run.py export my-star-config.json --output native-export-plan --compile

# Run in a separate new/empty directory, then build the review report.
python run.py export my-star-config.json --output native-export-run --compile --run --np 2 --timeout 1800
python run.py build native-export-run/case.json --output review.html
```

Each `surfaces` entry selects either `boundaries: [{region,name}]` or an exact `derivedPart`. New constant-threshold wall wrappers and X planes exist only in the owned session. The macro exports native STL triangle connectivity and coordinate/field CSV, then exits without saving the SIM. Each `xSections` value requires an explicitly selected `sectionRegions` fluid region.

For Cp/CpT mappings use an exact existing scalar, for example `{"function":"YOUR_CP_FIELD"}`, or a verified explicit expression such as `{"expression":"(${Pressure}-YOUR_P_REF)/YOUR_Q_REF"}` after substituting the actual references. Source pressure, density, speed and total-pressure conventions must be consistent. Existing coefficient reference getters and configured definitions are recorded as provenance, not as a complete physical validation of the model.

## Existing isosurfaces and other source faces

The 19.02 profile marks these source classes as mesh-capable: `IsoPart`, `PlaneSection`, `ThresholdPart`, `CylinderSection`, `SphereSection` and `ArbitrarySection`. Points, lines and unrecognized types are not offered as triangle-face layers. This is a supported-type selection rule; each real object still needs a successful native export and validated receipt.

The GUI allows existing layers alongside vehicle walls or a layers-only report. A selected layer can follow its source Scene's available scalar, use another inventoried scalar/magnitude, or remain geometry only. A source isosurface keeps its criterion and available isovalue metadata. An existing plane retains its source position; it is an independent layer rather than an invented new sweep frame.

For CLI configuration, add entries inside the existing STAR configuration's `layers` array:

```json
{
  "id": "existing-source-face",
  "name": "Source postprocessing face",
  "derivedPart": "YOUR_EXACT_DERIVED_PART",
  "kind": "isosurface",
  "fieldFunction": "YOUR_EXISTING_SCALAR_FUNCTION",
  "field": "YOUR_EXISTING_SCALAR_FUNCTION",
  "opacity": 0.7,
  "visible": true
}
```

This is an entry outline, not a complete configuration. Use the actual source type and scalar; the desktop derives the layer kind from its verified inventory. Omit `fieldFunction`/`field` for geometry-only export. For a layers-only configuration, `surfaces` and `xSections` can be empty and `fields` can be `{}`. Walls or new X planes still require at least one Cp/CpT field mapping.

Colored existing layers use one native **EnSight Gold geometry + per-node scalar** dataset. This keeps topology and field association together when independent STL and table exports use different surface sampling. Physical units come from STAR's internal units for the selected field; raw unit suffixes are retained alongside their normalized display spelling. Configured units must agree. Geometry-only layers retain the native STL route, with no fabricated CSV or scalar. Wall/new-X exports keep the separately validated CSV/STL path.

The joint surface profile supports the exercised little-endian C Binary format and ASCII equivalents, one recorded time snapshot, off/assign IDs, and `tria3`, `quad4` and `nsided` faces with a single per-node scalar. It requires one populated finite-volume representation so the source representation is unambiguous. Polygons use their original ordered nodes for validated presentation triangulation; no new nodes or scalar samples are inserted. Embedded `bar2` lines are omitted from this surface-only display with explicit counts. Unsupported volume elements, per-element scalars and transient sequences are rejected. Raw native node arrays remain intact, including unused line-only nodes; visible surface-node ranges drive automatic colors. Geometry, scalar hashes and triangulation/omission details travel with the layer.

Optional `colorRange` changes display only. Constant fields receive an expanded display range while stored values remain constant. Native source criteria and isovalues remain attached; changing an isovalue requires another source export.

A selected Q/lambda2/other source isosurface must be evaluated by native STAR from genuine saved results. The browser neither computes a new threshold surface from the full volume nor turns a synthetic shape into CFD evidence. Successful Java compilation or a mathematical demonstration does not establish successful export of every source vortex object. The exercised real selections and remaining limitations belong in [Validation](VALIDATION.md).

## Outputs and failure evidence

| File | Purpose |
| --- | --- |
| `adapter-plan.json`, generated Java macro | Prepared operation and API profile |
| `compile-receipt.json`, `compile.log` | Compilation against the selected local libraries |
| `run-receipt.json` | Execution, source checks, timeout/error and memory samples |
| `raw/*.stl`, `raw/*.csv` | Native mesh topology and actual exported vertex fields; geometry-only layers have STL only |
| `raw/*.case` and referenced geometry/scalar files, `raw/*.meta.json` | Joint existing-layer topology/node fields and actual native units/association |
| `raw/references.json`, `raw/pack-config.json` | Source references and explicit packing configuration |
| `case.json` | Written after all expected exports and data checks succeed |
| Desktop `desktop-job.json`, final HTML | Background workflow receipt and the completed report |

A zero process exit is insufficient: the completion marker, expected files, unchanged source and validated case are checked. Failed/partial outputs remain available for diagnosis and are not labelled complete cases. Adapter output directories must start new/empty; desktop jobs create unique subdirectories and publish a new final HTML only after success.

On Windows the runner checks initial headroom and samples memory during its own process. Timeout, cancellation and the low-memory guard stop only its owned process tree. Model size and source-derived field evaluation still determine memory use; the desktop error/task directory exposes the actual failure rather than replacing it with synthetic output.

## Already exported CSV/STL

```powershell
python run.py pack examples/pack-config.example.json --output packed-case.json
python run.py build packed-case.json --output packed-review.html
```

The supplied fixture is synthetic. Packing retains native STL triangles and associates declared CSV scalar columns by coordinate within an explicit tolerance. It records source hashes and transformations, omits only strictly zero-area STL triangles with a count, and rejects unmatched or ambiguous coincident samples. Geometry-only entries use an STL and `fields: {}`. A pre-exported source isosurface can be included as a `layers` entry with its actual scalar/units and criterion metadata. See [Data format](DATA_FORMAT.md).

## Templates and comparison

The desktop's template picker validates a local folder before an export job starts, then validates it again when building HTML. For CLI use:

```powershell
python run.py templates --output my-templates
python run.py validate-template my-templates/engineering-blue
python run.py build native-export-run/case.json --template my-templates/engineering-blue --output themed-review.html
```

Templates control layout/CSS/static assets, not source arrays or physics. See [Templates](TEMPLATES.md) for the required app slot/hooks, local-asset rules and official **Designed by Symn** attribution. Original code remains MIT licensed; the official fixed credit is not an additional visible-watermark requirement under MIT.

The browser imports case/project JSON and supports both linked two-view comparison and same-canvas Y-half-model stitching. Meaningful comparison requires compatible source coordinates, units and physical references. Stitching preserves source identity and uses common actual X planes without interpolation. Creating unexported planes, changing an isovalue or recovering unsaved time history requires the source data and another export.
