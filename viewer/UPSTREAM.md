# Upstream

`viewer/` is a vendored copy of [Ahd4wnn/stratum](https://github.com/Ahd4wnn/stratum) at commit
`46abc2279903` (2026-09-11, "Build offline Three.js terrain explorer with worker-based analysis").

It is a plain copy, not a submodule, so our contract patches are tracked in this repo.
Every local change to upstream files is listed under "Open issues" in `docs/VIEWER_CONTRACT.md`.
Files we added (not upstream): this file, `src/backend.ts`, `scripts/contract-test.mjs`.
