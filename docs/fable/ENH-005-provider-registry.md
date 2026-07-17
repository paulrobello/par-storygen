# ENH-005 — Single provider-metadata registry

## Goal
One declarative source of truth for provider metadata (display name, kind, default model, key env var,
base-URL rules, ref-image capability, suggested models) consumed by the TUI settings screen, the wizard,
the API, and the web settings UI. Success = adding a hypothetical new image provider means editing one
registry entry (plus its provider class) and every surface picks it up.

## Current state
- Provider knowledge is spread across (verify each with rg before starting):
  - `src/storygen/config.py` — env-var names, defaults, priority resolution
  - `src/storygen/screens/settings.py` — select options, suggested models, key-status labels
    (post-QA-009 this lives in the `ProviderSection` helper — **do this plan after QA-009**)
  - `src/storygen/screens/wizard.py` / `runtime/wizard_flow.py` — wizard provider choices
  - `src/storygen_api/routers/settings.py` + `schemas.py` — API settings surface
  - `web/` settings page — its own hardcoded lists
  - `src/storygen/images/*_provider.py` — per-provider capability facts (ref support; ARC-115 adds
    `supports_reference_images` — build on it, don't duplicate it)
- CLAUDE.md documents provider facts (OpenAI/Gemini ref-aware; Z.AI text-to-image only; Ollama local/no key).

## Steps
1. **Inventory pass** (do not skip): `rg -n "openai|gemini|zai|ollama|openrouter" src/storygen/config.py src/storygen/screens/settings.py src/storygen/screens/wizard.py src/storygen_api/routers/settings.py web/src --ignore-case -l`
   and list every site that hardcodes provider names/models. The registry must cover all of them.
2. **Create `src/storygen/core/providers.py`** (core layer — importable by everything):
   ```python
   """Declarative provider metadata registry — single source for all surfaces."""
   from dataclasses import dataclass, field

   @dataclass(frozen=True)
   class ProviderInfo:
       id: str                      # "openai", "openrouter", "ollama", "gemini", "zai"
       label: str                   # display name
       kind: frozenset[str]         # {"text"}, {"image"}, or both
       key_env_var: str | None      # None for local providers
       default_model: str | None
       default_base_url: str | None
       allows_loopback_base_url: bool   # mirrors security.py's per-provider policy
       supports_reference_images: bool  # image providers only; mirrors ARC-115
       suggested_models: tuple[str, ...] = ()

   TEXT_PROVIDERS: dict[str, ProviderInfo] = {...}
   IMAGE_PROVIDERS: dict[str, ProviderInfo] = {...}
   ```
   Populate from the inventory — every value must be traced to an existing site (cite the source file in
   a comment per entry). Do NOT invent new defaults.
3. **Migrate consumers one surface at a time**, gate-green between each:
   a. `config.py`: env-var names + defaults come from the registry (keep the documented priority order intact).
   b. TUI settings (`ProviderSection` post-QA-009): options/labels/suggested lists render from the registry.
   c. Wizard: provider steps render from the registry.
   d. API: add `GET /api/providers` (token-gated like the other content routes) returning the registry
      (a pydantic response model mirroring `ProviderInfo`); `routers/settings.py` validates provider ids
      against it.
   e. Web: settings page fetches `/api/providers` instead of hardcoding (types via ENH-001 if landed).
4. **Consistency guards**: a unit test asserting registry ⊇ every provider id accepted by
   `config.load_config`, and that `supports_reference_images` matches each provider class's ARC-115
   attribute (import the classes and compare).
5. **security.py**: do NOT move the SSRF allowlist into the registry in this pass — validation policy
   stays in `security.py`; the registry only carries the `allows_loopback_base_url` fact that
   security.py can consume if trivially wireable, else leave security.py untouched and note it.

## Files to touch
- New: `src/storygen/core/providers.py`, API route (in `src/storygen_api/routers/settings.py` or a new
  `providers.py` router), tests
- Edit: `src/storygen/config.py`, settings controllers, wizard modules, `src/storygen_api/schemas.py`,
  web settings page
- Read-only: `src/storygen/images/*_provider.py`, `src/storygen_api/security.py`

## Verification
```sh
make checkall            # after every migration sub-step, not just at the end
cd web && npm run test && npx tsc --noEmit
```
Manual: TUI settings shows identical options/labels as before; wizard unchanged; `curl` the new
`/api/providers` route; web settings renders from it.

## Rollback
Migrate surface-by-surface in separate commits — each surface can be reverted independently; the registry
module itself is inert until consumed. Full rollback = revert the migration commits (registry file can stay, unused).

## Pitfalls
- This is a refactor with zero intended behavior change — any visible difference in options, labels,
  defaults, or env handling is a bug. Snapshot the TUI settings options (existing settings tests) before starting.
- Priority order (env > .env > prefs > defaults) is load-bearing and documented — the registry supplies
  *values*, `config.py` keeps the *resolution logic*.
- Don't let the registry import provider classes (core must stay bottom-layer) — the consistency test
  imports both and compares from the test side.
