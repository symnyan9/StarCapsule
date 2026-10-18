# StarCapsule Studio

<!-- impeccable:product-schema 1 -->

## Platform

Windows desktop export workflow and offline web review

## Stack

Delegated by the user: Python local export/packaging, a native Tkinter/ttk desktop file picker and export form, and plain HTML, CSS, JavaScript with the existing MIT-licensed Three.js/OrbitControls viewer. Browser use is independent of Python, STAR, Codex, and internet access once a report is exported.

## Users and purpose

Engineering designers and reviewers share saved CFD results, compare cases, inspect geometry and exported field data, and leave reproducible three-dimensional comments. The user intends to publish source code as a personal GitHub project; publication remains a separate explicitly authorized step.

## Operating context

Desktop-first Windows engineering work. STAR-CCM+ is accessed through an owned, compatible, licensed local process. The browser imports validated case/project JSON packages, not proprietary SIM files. No project data, source files, or telemetry leave the machine.

## Capabilities and constraints

The current implementation targets two side-by-side views, optional camera/coordinate/field/color links, editable names, independent display settings, surface/section data, pre-exported isosurface layers, persistent view states and comments, and a self-contained HTML export. Arbitrary new sections or isovalue extraction require the source field and an export operation; display editing does not recompute CFD. Case identity and source metadata travel with the geometry and raw scalar arrays.

The desktop export surface is an Operate workflow: select a solved SIM, inventory its saved contents, explicitly select boundaries/fields and optional real X sections, and export/open a standalone HTML. Local work runs in a background controller, preserving responsive controls and allowing cancellation of its own process. Boundaries start unselected; changing or re-reading the SIM clears the previous selection and symmetry/section assumptions. Existing coefficient functions retain source definitions. The desktop form uses no server or additional runtime dependency beyond Python's Tk support.

Existing STAR postprocessing faces are selectable in their own tab, grouped by the scenes that reference them. The adapter identifies which concrete derived parts support triangle-mesh export; empty scenes and point/line objects are not presented as exportable faces. Selected existing isosurfaces, planes and surface wrappers can accompany wall data or form a geometry/layer-only report. Default layer coloring follows an available scalar function referenced by each source scene; the user can choose another existing scalar, geometry-only display, a display range and opacity. The export carries mesh/field data, rather than reproducing a STAR scene's camera, lights or annotations. Physical scalar units come from the native exported data.

For new X sweeps, verified coordinate bounds from selected vehicle walls supply the initial start/end automatically. A selected downstream wake layer does not change vehicle length. With only postprocessing faces selected, their bounds can be used when already available; unavailable derived bounds prompt a vehicle-wall selection or manual coordinates. These ranges describe the selected objects, including partial-vehicle selections. Manual changes remain intact until the user explicitly restores the selection bounds; absent or incomplete bounds remain visible. Export errors link to the most recent task directory so logs stay accessible without opening STAR's graphical interface.

Users can choose a validated local HTML/CSS/assets template directory from the native header. Template selection is global to the current desktop session and survives SIM changes, with an explicit restore-default action. Validation occurs locally before any export process starts and repeats at export. The software and generated HTML carry the fixed creator credit “Designed by Symn”; template selection provides no control to hide or rename it.

The native exporter filters calculation-mesh choices from actual finite-volume type and positive cell counts, preserves exact source identity behind localized descriptions, and automatically selects a usable mesh. A populated mesh is not a convergence claim. English/Chinese labels distinguish coefficient selection, display-only limits, spatial cuts and process count. Memory and data-limit errors name the recovery action while retaining technical details in the task log. Dense CFD arrays have separate bounded validation budgets; geometry-only STL uses exact coordinate indexing without altering triangle corners or creating scalar values.

## Evidence on hand

`reference-viewer/` contains synthetic examples and an existing field-viewer implementation. New examples remain synthetic with a persistent DEMO label. Real-SIM and cross-version compatibility claims require separately recorded tests. No team geometry or private results are included.

## Language and presentation

English is the default for the native exporter and generated viewer; Simplified Chinese is selectable. Desktop preferences persist locally, while a report/project retains its own `ui.language`. Switching changes authored interface copy only and preserves source names, user text, scientific arrays and active review state. Installation and review instructions are available in both languages. Custom template prose remains controlled by its author.

## Product principles

- Inspect the original values; color limits affect appearance only.
- Link views by physical coordinates rather than frame indices.
- Keep missing fields missing and display source identity.
- Preserve the existing project when an import fails.
- Export a readable offline artifact with the data and dependencies included.

## Project identity

The local release uses MIT for original code. The public repository is https://github.com/symnyan9/StarCapsule; publication was explicitly authorized by the author. The professional neutral engineering Operate layout is an implementation choice inferred from this task, rather than an independently approved brand identity.
