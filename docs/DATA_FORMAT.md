# Data format v1

All cases are self-contained JSON documents. Arrays carry actual values, not texture colors. The viewer convention is metres, X as the section axis, and Z up. Transform source geometry and positions explicitly before packing; record the transform in metadata. The following is a structural outline: a complete case needs at least one populated triangle-mesh part or layer.

```json
{
  "schema": "cfd-review-case", "version": 1,
  "id": "stable-case-id", "name": "Readable case name",
  "data": {
    "meta": {
      "title": "Field title", "source": "Saved state and provenance",
      "sourceKey": "stable-source-version", "units": "m", "axis": {"up": "z"},
      "isDemo": false, "halfCar": false,
      "ranges": {"Cp": [-3,3], "CpT": [-0.5,1]}, "surfaceRange": [-3,3]
    },
    "parts": [], "sections": [], "layers": []
  }
}
```

Each part has `id`, `name`, flat `positions` (xyz), and integer triangle `indices`. Optional `cp`/`cpt` arrays are vertex-associated. A mesh without a field remains a neutral geometry reference. Missing fields are never replaced by zero.

Each section adds its actual `x` coordinate and the same mesh/field arrays. Sections are strictly increasing. Its vertices must lie on that X plane within documented export/float precision. Each section needs at least one of `cp`/`cpt`; a case's whole section sequence must share at least one common field. The viewer enables that common set. Different cases may have different X sequences; synchronized review chooses the nearest real plane in the same coordinate frame and exposes its actual position.

A layer has `id`, `name`, `kind`, triangle positions/indices, and optional `values`, `field`, `units`, `colorRange`, `opacity`, `visible`, `criterion` and `threshold`. Supported kinds are `isosurface`, `section`, `surface` and `mesh`. A case can contain only layers, with `parts: []` and `sections: []`.

`values` are vertex-associated. A valued layer requires its scalar `field` label and finite increasing `colorRange`. Native existing layers use joint EnSight Gold topology/node fields plus STAR internal-unit metadata; legacy CSV inputs retain their explicit column/unit mapping. Conflicting configured units are rejected. A layer without values carries geometry only; it must not acquire a fabricated scalar readout. Display limits do not clip or rewrite raw values. A constant field can receive an expanded display range while its stored values remain constant.

Native source-layer provenance can include `sourceDerivedPart`, `sourcePartType`, `sourceFieldFunction`, `sourceValueColumn`, `criterion`, `threshold`, `isoValues` or `thresholdRange`, depending on the actual source object. These preserve source information rather than instructing the browser to compute new geometry. A saved source isosurface can be exported without storing the full CFD volume in the report. Changing its isovalue or computing an unexported plane requires source data and another export.

Joint native layers also retain `nativeAssociation`, native file hashes and per-part provenance. Face triangulation retains the original node coordinates/order and corresponding scalar values. Omitted line elements, strictly zero-area triangles, unused nodes and presentation triangulation are counted or described. The supported profile is a single saved snapshot with surface elements and a per-node scalar; it does not interpret volume meshes or synthesize time history. Unused line-only nodes remain in the arrays; automatic colors use the visible surface-node range. An explicit display range remains editable.

`halfCar: true` declares an actual half-model source. It does not alone enable full-car scalar reflection: that separate display operation additionally requires `mirrorAxis: "y"` and `scalarMirror: true`, supported by the source symmetry. Store the source SHA256 as `sourceSha256` when available. A human-readable label is not source identity.

Project documents have `schema: "cfd-review-project"`, `version: 1`, `title`, `cases`, one or two `views: [{caseId,state}]`, `links: {camera,section,field,color}`, and `notes: [{id,text,caseId,view,state}]`. State snapshots preserve source identity, camera, scalar, real plane, visibility, opacity, display ranges and layer settings. An optional `ui` object can contain `sidebarCollapsed: true` or `false` and `language: "en"` or `"zh-CN"`; invalid types/values are rejected. Reports without a language preference open in English. These UI preferences are retained by project JSON and standalone HTML and do not alter scientific data or source names. Templates may retain user-authored text in their own language.

## Display-only CpT transparency

The optional finite-number `data.meta.cptTransparentAbove` sets the initial CpT transparency threshold; the viewer default is `0.98`. A saved viewer state can supply its own finite-number `cptTransparentAbove`. For compatibility, the Boolean state field `hideNearOne` and metadata field `cptNearOneTransparent` still enable/disable the filter; their runtime meaning is now **CpT greater than or equal to the threshold becomes transparent**, rather than a tolerance band around one.

The threshold accepts any finite value, including values outside `[0,1]`. It applies only to CpT section rendering, independently of color limits. It does not clip/rewrite scalar arrays, change body Cp, generate values or recompute CFD. A saved threshold travels with its specific view and with comment snapshots. Older states without the field use the case/default threshold.

## Explicit user half-model declaration

A genuine Y=0 half model exported without its declaration can be confirmed in the case library. The action validates that exported parts, layers and sections occupy a single side of Y=0, records the user's physical-symmetry confirmation, and changes only `halfCar`/`mirrorAxis`. A one-sided geometry check is distinct from establishing a simulation's physical symmetry; the latter is the user's explicit declaration. Coordinate arrays, scalar arrays, source identity, `scalarMirror`, view states and comments are retained.

The optional active metadata record has this shape:

```json
{
  "symmetryDeclaration": {
    "kind": "user-confirmed-y0-half",
    "version": 1,
    "statement": "User confirmed the source as a Y=0 symmetric half model",
    "confirmedAt": "2026-01-01T00:00:00.000Z",
    "original": {
      "halfCar": false,
      "mirrorAxisPresent": false,
      "mirrorAxis": null
    }
  }
}
```

This example is structural, not an assertion about any case. An active declaration requires `halfCar: true` and `mirrorAxis: "y"`. `original.halfCar` is `false`; `mirrorAxisPresent` is Boolean, with original `mirrorAxis` equal to `x`/`y`/`z` when present and `null` otherwise. The nonempty statement and ISO timestamp retain the confirmation's provenance. Undo restores those original metadata fields before composition use. When a composition references the source, undo is disabled to preserve its validated source relationship and notes; reopening the earlier project restores the pre-composition state.

## Same-canvas half-model composition

The browser can retain two original cases and add a derived comparison case under `data.meta.comparison`. Both originals must be distinct actual half models about Y=0, with compatible coordinates and scalar labels/units. Source A is displayed on −Y and B on +Y. Reflection changes display geometry and triangle winding where necessary; each source's scalar arrays remain unchanged. The composed case has `halfCar: false` and `scalarMirror: false`, preventing a second automatic reflection.

Comparison metadata uses `kind: "half-car-stitch"`, `version: 1`, two `sources`, `sectionPolicy: "common-x-no-interpolation"`, `sourceSectionXs` and `sectionsStatus`. Each source records `caseId`, `sourceId`, side A/B, original half side, display Y sign and source/display reflection mapping; available source SHA256/key values remain attached. Parts/layers carry `sourceCaseId`, `sourceSide`, `sourceYSign` and the original `sourcePartId`/`sourceLayerId`.

Only actual matching X planes and fields common to both sources become a composed section. Equal counts alone do not prove coordinate agreement; different counts can still share some actual X positions. Matching uses the exported coordinates with the validator's numerical tolerance, not resampling. `comparisonRanges` attributes the vertex span of each half to its original case and section index. No matching planes or fields produces `no-common-x` or `no-common-fields`, with an empty composed section list; surface/layer comparison remains available. Exactly one shared plane supports a fixed-plane comparison; a meaningful spatial sweep needs at least two shared planes. Picking restores the original source point and identity while also recording the display point. Saved comparison picks include `sourceDataId` matching the original case SHA/key, the original case/object identity and the inverse Y mapping; validators reject a mismatched source identity or coordinate mapping.

The project must retain the two original cases so the validator can verify the composition's geometry, values, source identity and section sequence. Comparison coefficient references are preserved separately; the viewer does not silently renormalize them. Existing single-view and two-view projects remain supported.

## Standalone HTML storage

StarCapsule Studio keeps the existing application hooks and scientific schemas. A data slot may also contain the following lossless storage envelope:

```json
{"schema":"cfd-review-compressed","version":1,"encoding":"gzip-base64","decodedBytes":1234567,"chunks":["...independently encoded base64 chunks..."]}
```

Exactly these five keys are allowed. `decodedBytes` is an integer from 1 through 500 MiB. `chunks` is a nonempty array; each entry is a nonempty strict canonical Base64 string, at most 1 MiB of characters. Decode each entry independently and concatenate its bytes into one gzip stream. Decode gzip completely, including integrity/end checks, enforce the declared byte count while streaming, then parse strict UTF-8 JSON. Nested compression envelopes are rejected. The decoded value must still pass the ordinary project, case, composition, source and state checks. Encoded data slots retain their 500 MiB bound; recipes retain their 1 MiB decoded bound.

Default exports compress eligible data slots of at least 1 MiB; small data and composition recipes remain plain JSON. Both primary and case slots can use the envelope, including a legacy complete project stored in a compressed primary slot. Bundle manifests remain version 1. Opening compressed HTML requires a desktop browser with WebGL and native `DecompressionStream('gzip')`, verified locally with Chromium. Browser saving uses native `CompressionStream`; when unavailable it retains the plain JSON storage path. No network library is loaded. Compressed reports require the new reader; use `upgrade` or append old reports in a current workspace to retain backward compatibility.

Compression does not reduce mesh resolution or round scientific values. It reduces file size and stored text; decoded arrays and GPU buffers still require memory. Startup releases parsed data text from the DOM after the runtime has captured the template shell. Future saves rebuild the data slots from the validated project.

The authored template still has the same seven required hooks. The fixed `script#cfd-project-data[type="application/json"]` can contain either a legacy complete `cfd-review-project` document or a version 1 bundle manifest:

```json
{
  "schema": "cfd-review-html-bundle",
  "version": 1,
  "project": {
    "schema": "cfd-review-project",
    "version": 1,
    "title": "Offline comparison",
    "views": [{"caseId": "case-a", "state": null}],
    "links": {"camera": true, "section": true, "field": true, "color": true},
    "notes": [],
    "ui": {"sidebarCollapsed": false}
  },
  "cases": [{"id": "case-a", "elementId": "cfd-case-data-0"}]
}
```

The manifest's `project` is the original project without `cases`. Each reference points to a separate inline `application/json` script containing a full original case or a compact derived-composition recipe, immediately after the primary data script. Case-slot IDs are canonical and ordered: `cfd-case-data-0`, `cfd-case-data-1`, and so on. Each slot's case `id` must match its manifest reference. Duplicate, missing, mismatched and unreferenced case slots are rejected. Legacy complete-project data and full-case bundle slots remain supported, with no orphan bundle slots.

A recipe has exactly five top-level keys: `schema: "cfd-review-composition"`, integer `version: 1`, `id`, `name`, and the composed case's complete `meta` object. Its derived identity is `meta.sourceKey: "half-stitch:" + id`; `meta.sourceSha256` is absent. `meta.comparison.sources` must identify two distinct retained original full cases, with source ID, SHA256 and key matching the corresponding original metadata. A recipe cannot depend on another recipe or on a complete derived comparison case. Original slots may appear before or after the recipe. Each recipe is limited to **1 MiB**.

On reopening, the runtime resolves both originals, rebuilds the attributed Y reflection, winding and actual common-X sections, and validates geometry, scalar values and provenance against those sources. Recipe metadata retains edited presentation settings. Only the originals' arrays are stored; the recipe never supplies replacement geometry, resampled fields or invented planes. Ordinary project JSON continues to use complete case documents rather than recipes. Python serialization preserves older full-case representations whose derived identity does not satisfy the recipe contract.

Internal editing snapshots copy editable metadata and retain source numeric-array references, treating those arrays as source data. Half-stitch rendering reuses unchanged arrays and creates reflected geometry where required. This removes avoidable full-project cloning; actual rendering allocations still depend on mesh size and selected views.

The runtime rebuilds the ordinary validated project from those slots before mounting the viewer. Browser HTML export uses separate case blobs, rather than one aggregate project/HTML string; Python report generation can retain the legacy format for small output and uses bundle storage for large multi-case output or derived compositions. These are storage variants, not different scientific schemas. They retain every case, original values, active A/B selection, cameras, thresholds, display ranges, comments and sidebar preference.

Limits are **32 total cases**, including derived comparisons, **500 MiB per full-case or project-manifest JSON slot**, **1 MiB per composition-recipe slot**, and **2 GiB per HTML file**. Ordinary JSON import/save is limited to 500 MiB; a larger multi-case project should use standalone HTML. These bounds do not guarantee a browser/device can render a project at the maximum size. Available RAM, browser/GPU limits, mesh density, layers and the two active views determine practical capacity. No automatic mesh reduction is used to fit a limit.

Importing an exported HTML or a single case JSON appends cases to the existing project; importing a project JSON replaces the current project for restoration. For HTML merge, already known matching case IDs/source identities retain their current data; an ID referring to a different source is rejected. The imported page's scripts/styles/outer markup are ignored; only embedded validated data is reused under the current viewer and template. Saving a new HTML preserves the current template, not the imported page's template.

## Saved states and validation

Optional Boolean `state.mirrorDisplay` controls a per-view Y=0 display reflection independently of source `meta.scalarMirror`. A true value requires an original declared Y=0 half-model case with one-sided exported geometry; composed A/B cases retain their two attributed halves. Missing state values use the legacy case default. Mirrored picks require mirror display and retain the inverse-Y source coordinates. The switch changes scene objects only: reflected meshes share source geometry, scalar/color buffers and material. Saved states, notes and standalone HTML retain the choice.

The source declaration remains while a live mirrored view or saved mirrored note references it. Turn off the view first; a note keeps its own reproducible mirror choice and required source declaration.

Layer state is keyed by stable layer ID: `layerSettings: {"layer-id": {"visible": true, "opacity": 0.5, "colorRange": [0,1]}}`. Visibility and opacity are required for a saved layer entry; colorRange is optional. A geometry-only layer has no scalar readout: saved picks use `field: null, value: null`. A geometry-only surface similarly cannot carry a saved Cp/CpT value.

The Python schema and browser importer independently reject malformed arrays, non-finite values, duplicate JSON keys/identifiers, unsafe prototype keys, out-of-range indices, invalid states, and unsupported coordinate conventions. Invalid imports leave the open project intact. Unknown metadata is informational and must never execute code.

Use the generated synthetic examples to inspect a complete document. Values and geometries in those examples are mathematical demonstrations, not results of a CFD solver.

HTML/CSS templates are packaging input rather than CFD data. Project JSON preserves cases, views and comments; retain the editable template folder separately when rebuilding with `--template`. A standalone HTML embeds the resolved template assets and viewer. The official runtime adds its creator credit independently of the scientific JSON.
