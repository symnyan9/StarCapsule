# Offline review and multi-case comparison

[简体中文](REVIEW.zh-CN.md) · [Installation](INSTALL.md) · [Templates](TEMPLATES.md)

The desktop exporter reads selected results through a compatible, licensed local STAR-CCM+ installation. The exported HTML contains the selected geometry, scalar values, template assets and viewer. Open it in a browser environment with JavaScript and WebGL; gzip uses native streaming or the bundled offline decoder. No STAR, Python, server or network connection is needed for viewing.

Version 0.4.0 adds automatic mobile review, touch controls and on-demand case/section/layer loading. A computer-composed half-model HTML can be presented under one camera on a tablet. Read the [tablet guide and physical-device validation limits](MOBILE_REVIEW.md) before delivery.

## Choose a language

New installations and reports default to **English**. Use the **Language** selector in the desktop header or the HTML's **More** menu to choose **简体中文**. The desktop remembers the local preference, and its next exports use that language. HTML and project JSON retain the current language when saved. Switching updates the interface without resetting cases, cameras, section positions, colors, layer visibility or comments.

Simulation object names, field names, titles and user comments remain exactly as supplied. Custom template prose remains user-authored; it is not automatically translated. The included Engineering Blue shell follows the selected language.

## Export selected results

1. Choose a solved `.sim`, then click **Read simulation**. Leave the STAR path blank to detect a local installation.
2. Select body walls in **Boundary surfaces** and/or supported source face objects in **Existing postprocessing**. Existing isosurfaces and planes retain their source identity. Choose source scalar coloring or geometry-only display.
3. For a real X sweep, enable section export, choose fluid regions and review the start/end in metres. Selected body-wall bounds supply the initial range; an explicit comma-separated X list replaces start/end/count.
4. Set a new output filename and click **Export and open HTML**. The application starts its own background STAR process; you do not need to launch STAR's graphical interface manually. A compatible installation and valid license are still required.

Cp and CpT select only their available source coefficient functions, or **Do not export**. Other valid scalar fields are selected as layer coloring with their own labels and units. Existing face export retains mesh/field data, not every visual effect or annotation of its source STAR scene.

## Build a case library

Click **Import HTML / data** to append another exported HTML or single case JSON. Repeat to collect results in one workspace; choose any two cases in the A/B selectors. Only the selected views are rendered.

| Input | Behavior |
| --- | --- |
| Exported `.html` / `.htm` | Append new cases and compatible saved views/comments; retain the current editor and template |
| Single `case.json` | Append a source case |
| `project.json` | Restore that entire project, replacing the current project and its state |
| `.sim` | Export first with the desktop application and local STAR |

HTML import extracts validated data slots only. Scripts, CSS and other page elements from the imported report are not executed or adopted. A source ID already present with matching provenance keeps its current data; conflicting identities are rejected.

## Compare cases

**Side-by-side:** select **Compare**, then choose A and B. Link the camera, physical X position, scalar and color limits independently. Different section counts are allowed: X linking chooses each case's nearest actual exported plane and displays its real position. Check coordinate frames, units and coefficient reference definitions before comparing.

Open **A/B sync** to select what follows between two live views. With one live view these options are disabled and saved preferences are retained. Turning a link off stops subsequent synchronization; it does not hide an element or undo the current view. Re-enabling it aligns B with A.

**Half-models in one canvas:** select two genuine Y=0 half-model sources, assign A to −Y and B to +Y, and compose. Their geometry and picks retain the original case identity. A shared sweep uses only actual matching X planes and fields: zero common planes permits surface/layer comparison; one permits a fixed section comparison; two or more permit a spatial sweep. Equal counts alone do not establish matching positions.

If a genuine half-model lacks the source declaration, its case-library checkbox lets you explicitly confirm Y=0 symmetry after a one-sided geometry check. This confirms physical symmetry; it does not enable full-car display. The separate **Mirror full car** switch reflects a single half-model for viewing. It retains original values and records source/display coordinates for picks.

## Inspect and adjust

Drag to rotate, scroll to zoom and Shift-drag to pan. Use fit, standard views or fullscreen for detail. Component and layer visibility/opacity are independent.

The case selector shares one row with camera tools. Open **Camera** for standard views and **Fit section**; the case's three-dot menu holds rename, metadata and its comment action. Picked values appear in a highlighted overlay inside the canvas. **More** holds report title, language, review mode and project JSON save.

Choose X with the slider or coordinate entry; playback traverses the actual exported spatial planes back and forth. It is a spatial sweep, not transient time history. Double-click a visible triangle, or enable point picking and click, to read its position and available scalar. Scalar reads use barycentric interpolation within the exported triangle; a geometry-only layer supplies position only.

Surface, section and valued-layer color limits can be changed in the HTML without exporting again. Values outside the display range use endpoint colors; the original numbers remain intact. **CpT ≥ threshold: transparent** hides CpT section values at or above the applied threshold, initially **0.98**. The threshold and color range are independent. Cp sections, body Cp and additional layers have their own controls.

## Comment, save and reopen

Right-click the scene or use the comment button to record an observation with its camera, real plane, scalar, color limits, transparency, object settings and pick. Restore a comment to revisit that saved scientific view.

**Export HTML** saves the complete case library, selected A/B views, display settings, comments, language, sidebar preference, template and offline viewer. Reopen that file to continue reviewing. **Save project** saves JSON state/data for restoring within a viewer; it does not carry the appearance template.

| Format limit | Current ceiling |
| --- | --- |
| Cases including derived compositions | 32 |
| Source case (all its slots combined), or project manifest | 500 MiB each |
| Derived composition recipe | 1 MiB |
| Complete HTML | 2 GiB |
| Ordinary JSON import/save | 500 MiB; use HTML for larger combined projects |

These are validation limits, not device-capacity guarantees. Lossless compression reduces delivery size; decompressed arrays and GPU meshes still require memory. Original cases are stored once, and derived half-model compositions use bounded recipes to avoid repeating their complete arrays.

Large reports split surfaces, actual sections and eligible additional layers into independent embedded slots. Opening loads the selected case cores and current sections; each resident case caches at most two decoded sections. Showing a layer loads its data; hiding it frees its render resources and decoded working copy. Original packed slots remain available for complete HTML save, including content not yet viewed. **Save project** expands complete JSON and can require more temporary memory than **Export HTML**.

The task indicator distinguishes local reading, decompression, model/layer preparation and packaging. Only measurable decompression progress has a byte fraction; other phases remain indeterminate. Native gzip decoding is preferred, with an embedded offline fallback when unavailable. Without native `CompressionStream`, edited slots may save as plain JSON and increase output size; unvisited packed v2 slots remain compressed.

## Refresh an older report

Old HTML embeds its old viewer. Refresh it without starting STAR:

```powershell
starcapsule upgrade old-review.html --output updated-review.html --language en
```

Use `--language zh-CN` for Chinese. Omitting the flag retains a saved preference, or defaults to English if absent. A new filename preserves the original. Use `--template path/to/template` to select a custom appearance.

The HTML is a portable snapshot of selected results, not a backup of the complete `.sim`. New section geometry, changed source isovalues or additional flow structures require source data and another export. The official interface displays **Designed by Symn** in the existing view status row; licensing is described in the [README](../README.md).
