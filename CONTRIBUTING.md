# Contributing

Keep a small, verifiable path from a saved result to an offline review report.

1. Install the package from this repository (`python -m pip install -e '.[dev]'`).
2. Run `python -m unittest discover -s tests -v`.
3. Generate a fresh synthetic report with `python -m cfd_review demo --language zh-CN --output demo-check.html`.
4. Run `python tools/check_studio.py --html demo-check.html --output checks/browser` when changing browser behavior. The optional checker needs Playwright Chromium (`python -m playwright install chromium`).
   Also run `python tools/check_language.py --output checks/language` for English defaults and language switching.
5. Test export adapters against a privately supplied, authorized saved simulation. Include the STAR version and exact verification scope in the result; never add the model or proprietary results to a pull request.

Browser runtime dependencies must be bundled locally. Keep Three.js/OrbitControls versions matched and retain their notices. Changing dependencies requires a real offline-browser check.

Do not modify source SIM files. Exporting a new display object is distinct from changing the solution. Validate all mesh/field associations, transformations, source identities, and state imports. Test malformed documents before replacing an open project.

Synthetic fixtures must keep `isDemo: true`. Describe implementation, data validation, and physical interpretation separately. A synthetic tube can test an isosurface layer without being a computed vortex.

Use `codex/` branches for automated contributions. CI tests are configured for GitHub; a local check is not evidence that a hosted CI run has completed.
