# Editable offline export templates

[简体中文](TEMPLATES.zh-CN.md)

The engine interface defaults to English and offers Simplified Chinese; its choice is saved in `project.ui.language`. Source names and user-authored template prose remain literal. Supply your own bilingual surrounding copy when needed. The included Engineering Blue shell follows the selected interface language.

The local export dialog accepts a **template folder**. A template changes layout, typography, colors and static artwork around the existing review application. It retains the shipped renderer, source data, picking, comparison, notes and offline HTML export. Templates do not change a scalar value, coordinate, source identifier, coefficient definition or geometry triangle.

Export the editable starting pack using `starcapsule templates --output MY_TEMPLATES` (or `python run.py templates --output MY_TEMPLATES` from a checkout), then select `MY_TEMPLATES/engineering-blue` in the desktop dialog. The destination must be new or empty. The default application remains available by clearing the template selection.

## Folder contract

```text
engineering-blue/
  template.json
  layout.html
  theme.css
  mark.svg
```

```json
{
  "schema": "cfd-review-template",
  "version": 1,
  "name": "Engineering Blue",
  "html": "layout.html",
  "css": "theme.css"
}
```

`html` and `css` are optional individually; at least one is required. A CSS-only pack uses the built-in layout. All paths, including image sources and CSS `url(...)`, are relative to the **template folder**, even when a stylesheet is in a subdirectory. Files and symlinks must resolve inside that folder. The validator embeds supported local images and fonts as data URLs. No file server, CDN or network access is required by the resulting HTML.

Supported assets are PNG, JPEG, WebP, GIF, AVIF, ICO, static self-contained SVG, WOFF, WOFF2, TTF and OTF. Use fonts and images you have permission to distribute. Static SVG references may use `#fragment`; scripts, animation and external references are rejected. CSS imports, `image-set`, extra JavaScript, event attributes, external links, forms, frames and external stylesheets are outside the version 1 template contract. Declare the stylesheet in `template.json`; use local `url(...)` for assets.

## Required layout slots

A full HTML layout must have one explicitly balanced `head`, one `body`, and one `<div id="app">` inside the body. The application replaces that div's contents. Reserve at least **1200 × 760 CSS pixels** for it; the exporter supplies minimum dimensions. Surrounding headings, explanatory text and static images can be edited freely. Keep surrounding headers compact so the 3D canvas starts near the top of the desktop window. The engine fits its workspace to the available viewport and independently scrolls its scientific settings/sidebar; avoid fixed outer heights or padding that squeeze this workspace.

The current engine has **seven mandatory hooks**. Keep each exactly once in these containers and in this order:

```html
<style id="studio-style">{{STUDIO_CSS}}</style>
<style id="field-viewer-style">{{FIELD_VIEWER_CSS}}</style>
```

The following five blocks must follow the app slot, directly in the body:

```html
<script id="cfd-project-data" type="application/json">{{PROJECT_JSON}}</script>
<script id="three-runtime">{{THREE_JS}}</script>
<script id="orbit-runtime">{{ORBIT_CONTROLS_JS}}</script>
<script id="field-viewer-runtime">{{FIELD_VIEWER_JS}}</script>
<script id="studio-runtime">{{STUDIO_JS}}</script>
```

A large report may use a `cfd-review-html-bundle` manifest in `PROJECT_JSON`, followed by engine-generated `application/json` case-data scripts. The exporter inserts those scripts itself, immediately after the project-data script and before runtime scripts. **No new authored hook is required.** Keep the same seven hooks, IDs and containers; do not add, delete, rename or manually generate `cfd-case-data-N` slots in a template. See [Data format](DATA_FORMAT.md#standalone-html-storage).

The optional eighth hook is `<style id="cfd-template-style">{{TEMPLATE_CSS}}</style>`, after the two built-in styles in the head. When it is omitted, the exporter inserts it before the closing head. The supplied CSS is applied after built-in styles. Hook containers contain only their hook; do not insert JavaScript or data alongside a runtime placeholder. Duplicate IDs, duplicate/missing hooks and incorrect hook order are rejected before STAR starts.

The exporter supplies a fixed Content Security Policy, including `connect-src 'none'`, `object-src 'none'`, local data images and `font-src data:`. A template cannot weaken this policy. Runtime engine code and JSON are inserted in one substitution pass, with JSON/script escaping; strings that happen to contain a hook remain literal data.

Appending an exported HTML in the review application reads its validated embedded data only. Imported page scripts, CSS and outer markup are not adopted. The open application retains its current template; a newly saved HTML carries that template and all loaded cases. Selecting a template in the desktop exporter is the deliberate path for changing the outer design.

The application displays the creator credit **Designed by Symn** independently of the template's descriptive text. Retain the credit and dependency license notices. This is project attribution, not DRM or a claim that open-source files cannot be modified.

## AI layout handoff

Give another design/coding assistant the entire exported template folder and this instruction:

> Edit this local StarCapsule Studio template for the requested presentation style. Modify only the outer HTML layout, CSS and licensed static images/fonts. Keep one div id="app", with at least 1200 × 760 CSS pixels. Preserve the seven mandatory engine/data hooks and their exact containers and order from docs/TEMPLATES.md; the eighth TEMPLATE_CSS hook is optional and follows the two built-in style hooks. Keep runtime scripts directly in body after the app slot. Keep the project JSON hook's id="cfd-project-data" and type="application/json". Preserve Designed by Symn attribution and dependency notices. Use only files inside this folder; write asset paths relative to the template folder. Do not add JavaScript, event handlers, remote resources, CSS imports, frames or forms. Do not edit exported scientific data, computation, sampling, physics, component identity or the engine. Use professional desktop typography, clear hierarchy and a fully usable application slot. Keep the outer header compact, preserve independent sidebar/settings scrolling, and leave engine-generated cfd-case-data-N scripts to the exporter; the seven authored hooks remain unchanged. Deliver the edited folder with template.json, rather than a rendered screenshot.

Validate a pack with `cfd-review validate-template PATH_TO_FOLDER`. A successful check proves the structural/offline template contract; it does not replace visual review of the final report. The desktop dialog validates before opening STAR and revalidates when building the report.
