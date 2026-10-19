# Changelog

## 0.4.0 — offline tablet review and on-demand results (prerelease)

- Adapt one self-contained HTML to desktop and tablet review, automatically or through the More menu. Add touch rotation/zoom/pan, tap picking, settings/catalog drawers, a mobile single-canvas default and retained desktop comparison states.
- Split large reports into independently embedded surface cores, real sections and eligible additional layers. Load selected content on demand, cache at most two decoded sections per resident case, and release hidden layer GPU resources and decoded working copies. Keep original meshes, field precision and source attribution.
- Present computer-composed half-model comparisons under one camera on a tablet. Keep both original cases, common real-X sections, comments and review settings when saving offline HTML.
- Bundle pako 2.2.0 inflate as an offline fallback when native gzip decoding is unavailable. Prefer native decoding and retain decoded-byte limits, strict UTF-8 and gzip CRC32/size checks. Edited slots may save as larger plain JSON without native compression; unvisited packed v2 slots stay compressed.
- Merge project/comparison actions into one header and case selection into the camera toolbar. Keep picked values in a highlighted canvas overlay; put project details, language, review mode and project JSON save in More. Preserve usable touch targets and accessible menus.
- Show task status during local reads, decompression, model/layer preparation and HTML packaging. Show measured decoded bytes where available; keep other phases indeterminate.
- Explain A/B synchronization, disable its controls with one live view without changing saved preferences, and fix the asynchronous feedback guard during rapid linked section changes. Expand the orbit distance limit when explicitly fitting a large section.
- Preserve signed zero when upgrading older browser reports and saving new plain or packed slots. Retain previous report formats, desktop functionality and legacy command aliases.

This is a prerelease with automated desktop/tablet-touch coverage. A user screenshot shows a report rendering in HTML Viewer Q on iPadOS 16.3.1; full physical iPad/Safari qualification and universal mobile capacity are not established. Existing HTML must be upgraded or replaced to receive the new viewer. Multi-case import, comparison/stitching, editable color limits, comments, themes, bilingual UI and lossless gzip predate this release. See the [bilingual release notes](docs/RELEASE_NOTES_0.4.0.md).

## 0.3.1 — efficient large-model validation and publication preview

- Skip translation-dictionary scans for empty/ASCII-only validation fragments while preserving authored Chinese text and punctuation conversion. This avoids repeated UI translation work when validating dense scientific arrays.
- Add regression checks for all translation entries, punctuation handling, preserved source text and the absence of dictionary scans for repeated ASCII fragments.
- Add an explicitly authorized rendered real-case half-model preview to the bilingual project pages. Interactive downloadable examples remain synthetic; no real simulation geometry or field arrays are distributed.
- Credit Symn and Jilin University, and clarify the Gsmart / JLU Racing inspiration. Link installation downloads and record the initial hosted CI scope.

## 0.3.0 — English-first bilingual review

- Default to English in the desktop exporter and offline HTML; switch to Simplified Chinese without losing selections, current jobs, views or source data. Desktop preferences persist locally; HTML/project files retain their selected language.
- Translate application controls, statuses and errors while preserving exact source object names, field labels, user titles and comments. Add `--language en|zh-CN` to demo, build and upgrade commands.
- Provide English and Chinese review, template and installation instructions. Retain the fixed creator credit and acknowledge the JLU Racing GSmart workflow inspiration.
- Include complete third-party runtime license texts/provenance in release materials; provide an English-default, self-contained Windows installer with optional Chinese instructions.

## 0.2.6 — StarCapsule Studio and lossless portable results

- Introduce the StarCapsule project name and StarCapsule Studio interface. Add `starcapsule` / `starcapsule-gui` entry points while retaining the previous command aliases and data contracts.
- Losslessly gzip large embedded data slots using bounded Base64 chunks; use Python standard-library compression and native offline browser streams. Preserve original scientific precision, source meshes, selected layers, sections, settings and comments.
- Release embedded data text after decoding, remove redundant validation within the private startup path, and show loading progress before mounting the viewer.
- Bound decoded bytes before parsing and verify gzip integrity. Continue opening previous uncompressed reports and compact composition recipes.

## 0.2.5 — memory-conscious half-model comparison

- Replace full-data internal editing snapshots with metadata copies that retain source numeric arrays. Reuse unchanged arrays during half-stitch composition and allocate reflected geometry as needed.
- Save derived half-stitch HTML slots as compact, provenance-checked recipes while retaining both original cases once. Reconstruct compositions on reopening; continue reading legacy complete-case reports and leave ordinary project JSON unchanged.
- Restrict desktop Cp/CpT selectors to their respective available source coefficient functions and **不导出**. Other valid scalars remain available for existing-layer coloring with their actual quantity names and units.

## 0.2.4 — full-car mirror display switch

- Add a saved per-view mirror-display switch, separate from the source half-model declaration. Source surfaces, sections and layers share their original geometry/scalar buffers across the reflected display.
- Preserve original coordinates, values and half-model metadata. Mirrored picks retain inverse source coordinates; comparison cases keep their two independent halves.
- Save mirror preferences in view states, notes and standalone HTML, retaining legacy defaults for old reports.

## 0.2.3 — focused scalar readouts and compact attribution

- Highlight picked Cp, CpT and other scalar values in a separate filled rectangle, with larger tabular numerals and secondary component/coordinate text. Retain zero and missing-value distinctions.
- Keep the readout height stable between empty, picked and restored states so selecting a point does not move the canvas beneath the cursor.
- Move the fixed creator credit into the active view's existing status row, reclaiming the former bottom space. Preserve one isolated credit through fullscreen, comparison and saved HTML reopening.

## 0.2.2 — threshold filtering and multi-case review

- Edit the CpT transparency threshold directly in HTML; samples at or above the threshold become transparent. Default is 0.98. View states, notes and exports retain it without changing source values.
- Move the 3D workspace upward by removing repeated titles, compact the header, and add a narrow collapsible sidebar whose state persists. Remove triangle counts from the project overview.
- Keep picked scalar values and coordinates above the canvas in a highlighted readout; distinguish active readings from empty or missed selections, and emphasize the main inspection controls.
- Append exported HTML as source data, choose arbitrary cases for A/B comparison, and retain the whole case library when exporting and reopening. Existing project JSON imports keep their project-replacement meaning.
- Explicitly confirm a source's Y=0 half-model declaration without rerunning STAR; validate one-sided geometry and record the user's declaration. Same-canvas sweeps use actual common X positions.
- Store large multi-case HTML in bounded per-case JSON slots, avoiding one giant serialized string. Existing saved HTML can be rebuilt with current assets using the offline `upgrade` command.

## 0.2.1 — clearer native export choices

- Offer only native finite-volume representations with saved cells, automatically select the available calculation mesh, and retain exact source names behind Chinese descriptions. Unknown, geometric and empty representations are rejected before starting an export.
- Clarify coefficient fields, display limits, parallel processes, existing face types, optional spatial sections and half-model reflection in the native export window.
- Explain memory-protection stops in Chinese with recovery steps, retaining the original exception in the task log.
- Count dense CFD arrays separately from JSON structure in matching bounded Python/browser checks. Keep numeric, nesting, index and unsafe-key validation.
- Index geometry-only STL by exact XYZ bit patterns, retaining every nonzero triangle corner and winding while reducing duplicated coordinate storage. Colored CSV and Gold associations retain their existing routes.
- Keep source values, offline HTML, local templates and the fixed creator credit unchanged.

## 0.2.0 — native export, source layers and editable templates

Adds a native Tkinter SIM picker, exact source inventory selection, background progress, owned-process cancellation, output preservation and access to the latest task directory. The default desktop export process count is two.

- Select existing mesh-capable STAR postprocessing parts, including source isosurfaces and planes, with existing scalar/magnitude coloring or geometry-only display. Layer-only reports are supported; actual source/export limits remain in [Validation](docs/VALIDATION.md).
- Initialize X sweeps from selected vehicle-wall bounds, preserve manual changes, and restore selected bounds explicitly. Wake layers do not redefine vehicle length.
- Compare two independent half-model cases in a single canvas, with source-attributed geometry, original values and common real X planes; retain the two-view mode.
- Choose validated local HTML/CSS/static-asset templates, export an editable starting pack, and retain the selection across SIM changes. Add the official software/report credit **Designed by Symn**, with no template toggle. Original code remains MIT licensed.

Generated reports remain self-contained and offline. Test counts and real native acceptance are maintained in the validation record rather than duplicated here.

## 0.1.0 — development release

This version establishes the local export/data contract and offline review application. The README and validation record list behavior that has actually been checked and the remaining adapter compatibility limits.

The initial reference viewer was preserved locally during development. Generated examples are synthetic and contain no team vehicle or simulation result.
