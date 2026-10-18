# StarCapsule Studio — working agreement

This is an independent software project published at https://github.com/symnyan9/StarCapsule. It is separate from the user's Formula Student team deliverables.

- Read README.md and docs/STAR_ADAPTER.md before starting. Respond to the user in Chinese unless requested otherwise. A local historical HANDOFF.md may also exist outside the public release.
- Keep source code, synthetic examples, configuration templates, and checks in this project. Never edit the Aero working directory, team reports, simulation library, or existing deliverables as part of this project.
- Do not copy team SIM files, actual vehicle geometry, CFD results, private paths, or historical receipts into this repository. Downloadable reference examples must stay explicitly synthetic. The author explicitly authorized only the rendered real-case screenshot at docs/images/real-half-comparison.png for the public README; this does not authorize publishing its source geometry, arrays or simulations.
- Local development and reversible checks are authorized. Creating a public repository, pushing code, publishing a release/site, or uploading any files requires an explicit publication instruction. The user explicitly authorized this repository and its release publication on 2026-10-19.
- Source `.sim` files must be read through a compatible, licensed local STAR-CCM+ installation. Do not claim browser JavaScript or a generic Python parser reads arbitrary proprietary SIM files directly.
- For export: do not solve, remesh, clear/initialize a solution, save back to the source SIM, or interfere with unrelated STAR sessions. Use an owned export process or a clearly identified working copy; preserve source hashes and export provenance.
- Missing scenes can be generated from a valid saved solution; missing solution fields or unsaved time history cannot be invented.
- Production operation must be local and must not depend on Codex, an LLM API, a CDN, telemetry, or cloud services. STAR license-server availability remains an independently checked prerequisite; do not promise air-gapped use before checking the installed license arrangement.
- Keep geometry, scalar data, configuration, and source identity together. Never mix cases or fill missing data with zero. Record transformations, interpolation, simplification, and display-only settings.
- Preserve licenses for bundled dependencies. This project currently includes Three.js/OrbitControls reference files and their MIT license. Do not copy code from the compared third-party STAR post-processing repository; only its public URL is a reference.
- Prefer the existing tested viewer and standard/native interfaces. No backend rewrites, elaborate plugin frameworks, or new dependencies without a concrete need.
- Distinguish implemented and tested behavior from plans. A DEMO check is not a real-SIM check or proof of cross-vehicle compatibility.
- Run checks proportional to each change and keep concise results. Git work branches use `codex/`.
