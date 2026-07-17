# ENH-001 — Generate TypeScript API types from OpenAPI

## Goal
Replace the hand-written REST interfaces in `web/src/lib/api.ts` with types generated from the
FastAPI OpenAPI schema, so Pydantic model changes propagate to the frontend mechanically.
Success = a Pydantic field rename breaks `npx tsc --noEmit` in web without any hand edits to type definitions.

## Current state
- `web/src/lib/api.ts` (~305 lines) hand-declares interfaces (`GameSummary`, `GameDetail`, `NodeDetail`, …)
  mirroring `src/storygen_api/schemas.py` by convention (`web/AGENTS.md` documents the convention).
- The WS contract is separately pinned (`web/src/lib/ws-types.ts` + pydantic-mirror test) — leave it alone;
  this plan covers REST only.
- If AUDIT ARC-108 landed, there is an OpenAPI snapshot test (`tests/unit/test_api_openapi_snapshot.py`)
  — keep it; codegen and the snapshot are complementary (snapshot = server-side alarm, codegen = client-side fix).
- Assumes AUDIT SEC-102 (token plumbing) and QA-013 (`sceneImageUrl`) are done or absent — neither conflicts.

## Steps
1. **Export the schema deterministically.** Add `scripts/export_openapi.py` (repo root `scripts/`, create if absent):
   ```python
   """Write the FastAPI OpenAPI schema to web/openapi.json (deterministic)."""
   import json, pathlib
   from storygen_api.main import app

   out = pathlib.Path(__file__).resolve().parent.parent / "web" / "openapi.json"
   out.write_text(json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n")
   print(f"wrote {out}")
   ```
   Run with `uv run python scripts/export_openapi.py` (requires the `api` extra — Makefile `build` installs it post-ARC-111).
2. **Add the generator dep.** `cd web && npm install --save-dev openapi-typescript` (pin the version npm resolves; record it in `package.json` as an exact or caret version consistent with the file's existing style).
3. **Add npm scripts** to `web/package.json`:
   ```json
   "gen:api": "openapi-typescript openapi.json -o src/lib/api-types.gen.ts",
   "gen:api:check": "npm run gen:api && git diff --exit-code -- src/lib/api-types.gen.ts openapi.json"
   ```
4. **Generate once**: `uv run python scripts/export_openapi.py && cd web && npm run gen:api`. Commit both
   `web/openapi.json` and `web/src/lib/api-types.gen.ts` (generated-but-committed, like a lockfile).
   Add a header comment via generator options if supported, else a README note: "generated — do not edit".
5. **Migrate `api.ts`**: for each hand-written interface, replace its body with a re-export/alias of the
   generated type, e.g.:
   ```ts
   import type { components } from "./api-types.gen";
   export type GameSummary = components["schemas"]["GameSummary"];
   ```
   Keep the exported names identical so no other file changes. Where the hand type intentionally diverges
   (narrowed unions, client-only fields), keep the hand type and add a `// diverges from schema: <why>` comment —
   list these divergences in your report.
6. **Wire the check into the gate**: add `npm run gen:api:check` to the `web-check` Makefile target
   (from AUDIT QA-004) *after* a schema-export step: the Make recipe becomes
   `uv run python scripts/export_openapi.py && cd web && npm run gen:api:check && npm run lint && npm run test && npx tsc --noEmit`.
   If QA-004 hasn't landed, add a standalone `web-typegen-check` target and note it for CI.
7. **Docs**: add a short "API types are generated" paragraph to `web/AGENTS.md` and `web/README.md`
   (replacing the "update the matching interface" convention for REST).

## Files to touch
- New: `scripts/export_openapi.py`, `web/openapi.json` (generated), `web/src/lib/api-types.gen.ts` (generated)
- Edit: `web/package.json`, `web/src/lib/api.ts`, `Makefile` (web-check), `web/AGENTS.md`, `web/README.md`
- Read-only: `src/storygen_api/schemas.py`, `src/storygen_api/main.py`

## Verification
```sh
uv run python scripts/export_openapi.py
cd web && npm run gen:api:check && npx tsc --noEmit && npm run lint && npm run test
make checkall
```
Then the mutation test: temporarily rename a field in `schemas.py` → `export_openapi` + `gen:api` →
`npx tsc --noEmit` must fail in web; revert.

## Rollback
Generated files and the script are additive — delete `scripts/export_openapi.py`, `web/openapi.json`,
`web/src/lib/api-types.gen.ts`, remove the npm scripts/dep and the Makefile line, and restore the previous
`api.ts` interface bodies from git (`git checkout HEAD~1 -- web/src/lib/api.ts`). No runtime behavior changes at any point.

## Pitfalls for the implementer
- `openapi-typescript` emits `components["schemas"][...]` paths keyed by the Pydantic class names — if two models
  share a name across modules FastAPI suffixes them; check the generated file for `GameSummary1`-style names before aliasing.
- Determinism: always `sort_keys=True` in the export, or the `git diff --exit-code` check flakes.
- Do not regenerate inside `npm run build` (network-free CI steps stay reproducible); generation is explicit + committed.
