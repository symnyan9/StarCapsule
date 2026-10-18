# StarCapsule: project introduction and launch copy

[简体中文](GITHUB_LAUNCH.zh-CN.md) · [Project guide](../README.md) · [Native export](STAR_ADAPTER.md)

Project name: **StarCapsule**. Desktop application and exported interface: **StarCapsule Studio**.

## GitHub About

> Portable offline 3D review for STAR-CCM+ results. Export selected data to one HTML, compare cases, inspect real sections and preserve comments with review state.

Chinese version:

> 将 STAR-CCM+ 所选结果封装为单文件离线三维审阅工作台：真实截面、工况对比、数值取点、状态批注与模板定制。

Suggested topics: `starccm`, `cfd`, `post-processing`, `scientific-visualization`, `offline-first`, `threejs`, `engineering`, `python`.

## One-line positioning

**Portable STAR-CCM+ results. Interactive review. One offline HTML.**

Turn selected STAR-CCM+ results into an interactive, offline HTML that can travel with an ongoing review.

## Project introduction

StarCapsule brings selected CFD results to design reviews, technical presentations and engineering handoffs. It packages geometry, scalar fields, real section planes and existing postprocessing faces from saved STAR-CCM+ simulations into a self-contained 3D workspace. Recipients open one HTML to rotate the model, inspect local values, sweep sections, compare designs and record observations without installing STAR, Python or a server.

On the exporting computer, StarCapsule uses a compatible, licensed local STAR-CCM+ installation in an owned background process. Users do not need to open the STAR graphical interface manually. Selected walls and new X sections can be evaluated from the saved solution; existing isosurfaces and other supported face objects can be selected with available source-definition metadata retained. The required mesh, saved solution fields and field functions must still exist in the source simulation.

Geometry, exported numeric values, source identities and review settings stay together, so a discussion can return to a particular case, section, view and picked location. Append another case, arrange a comparison, add comments and export again to pass the review context to the next person. The review environment travels with the results, reducing setup for the recipient.

## Core value

### From a local simulation to an independent deliverable

Choose a `.sim`, read its object inventory and select walls, coefficient fields, sections and existing postprocessing layers. The application invokes local STAR for native extraction. The resulting HTML embeds its viewing engine, interface and data; reviewing requires no CDN, cloud account, AI service or local server.

### Keep results open to inspection

Rotation, zoom, pan and fullscreen expose geometry details. Manual X-section selection, pause and automatic back-and-forth sweeping follow spatial changes through real exported planes. Reviewers can switch Cp/CpT, edit independent color limits, adjust the CpT transparency threshold and control part visibility directly in the page. Picks interpolate the exported triangle's vertex field values and retain source attribution and coordinates.

### Compare designs in the same review environment

Append multiple cases to one HTML, choose any available A/B sources and independently link cameras, physical X position, scalar selection and color limits. Two compatible symmetric half-models can also occupy opposite sides of one canvas under a shared camera, with each side retaining its source identity.

### Preserve the context of a discussion

Comments carry their associated viewing state. A saved HTML retains the case library, A/B selection, camera, section, layers, color limits and comments, allowing the review to continue after reopening. It can also serve as a portable catalog of selected results for handoffs, teaching or recurring design discussions.

### Make the deliverable fit your presentation

The desktop application and exported HTML default to English, offer Simplified Chinese and retain the selected language. Source object names and user-entered titles stay unchanged. HTML/CSS templates expose defined containers and engine hooks for team or personal styling. Official exports retain a compact **Designed by Symn** credit.

### Retain selected detail while reducing duplication

Large data slots use lossless gzip and chunked embedding. Stored export data is not compressed by automatic mesh reduction or decimal rounding. Unchanged arrays are reused internally, and derived same-canvas comparisons are saved as source-based composition records, reducing avoidable copies and repeated storage. File size, startup time and usable case count still depend on selected geometry, sections, layers and hardware; a file-size reduction is not an equivalent reduction in decoded memory use.

## Typical uses

- **Technical presentations:** move from the complete model to real sections and local values while explaining the evidence behind a design change.
- **Team design reviews:** compare two cases under matching views, color limits and physical positions, then save observations with their display context.
- **Simulation handoffs:** deliver selected results to colleagues without STAR while retaining provenance and an interface they can continue using.
- **Offline result catalogs:** organize a focused set of cases in one file for repeated review in a supported desktop browser.

## Suggested demonstration

1. Open a synthetic example and demonstrate model rotation, local picking and color-limit editing.
2. Select a real exported section manually, then show automatic spatial sweeping and pause.
3. Append a second case; show linked A/B views and a compatible same-canvas half-model comparison.
4. Add a comment, save the HTML and reopen it offline with the cases and review state restored.
5. Show a custom template and language switching, then link to installation, usage and validation details.

## Scope

StarCapsule provides a **portable snapshot and review workspace for selected results**. Its HTML contains exported geometry, values and context rather than the complete `.sim` solver environment. Keep the source simulation for backup, further solving and complete simulation archival.

Native extraction requires a compatible local STAR installation, sufficient resources and a valid license. License-server connectivity depends on the local licensing arrangement. The native interface has been validated against **STAR-CCM+ 19.02.009**; other releases require separate verification. Viewing the standalone HTML does not start STAR.

Automatic sweeping visits actually exported spatial planes. It is not transient playback or arbitrary reslicing of the original volume. New sections, changed source-isosurface thresholds and newly calculated vortex structures require another export from the saved simulation. Same-canvas half-model comparison requires compatible coordinates, genuine Y=0 half-models and available fields. Linked two-view comparisons accept differing section counts and expose the actual matched positions.

Precision retention applies to the exported data. Convergence, physical definitions, coefficient references and case comparability still require engineering judgment. Public examples are explicitly synthetic; the [validation record](VALIDATION.md) separates synthetic checks, real native exports and device-specific tests.

## Creator and inspiration

**Designed by Symn**

**Inspired by the simulation and design-review workflows of JLU Racing GSmart.**

灵感来自 JLU Racing GSmart 车队的仿真与设计评审工作流。
