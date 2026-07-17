# ENH-007 — Web code-splitting + render optimization

## Goal
Cut the play/characters pages' initial JS and stop whole-page re-renders during streaming updates:
modals load on demand (`next/dynamic`), heavy visual components are memoized, and store subscriptions
are narrowed. Success = measurably smaller first-load JS for `/play/[gameId]` (Next build output table)
and no full-page re-render per WS event (React DevTools profiler or render-count probes in tests).

## Current state
- **Hard prerequisite**: AUDIT QA-001/QA-002 (PlayPage/CharactersPage decomposition into
  `web/src/components/play/*Modal.tsx`, `web/src/components/characters/*`, and feature hooks). This plan
  is the follow-on polish; on the monoliths it is not executable.
- `web/src/components/story/StoryGraph.tsx` — `TreeNodeBox` (CC 19) renders per tree node.
- Zustand store: `web/src/stores/game-store.ts`; components may subscribe broadly
  (`useGameStore()` with no selector = re-render on every store change).
- If ENH-002 (token streaming) landed, store updates arrive many times per second during generation —
  the payoff here compounds.

## Steps
1. **Baseline**: `cd web && npm run build` and record the route-size table (paste into your report).
2. **Dynamic modals**: for each extracted modal that is closed by default, convert the import in the
   page/parent to:
   ```tsx
   const PortraitsModal = dynamic(() => import("@/components/play/PortraitsModal"), { ssr: false });
   ```
   (`import dynamic from "next/dynamic"`). Only modals/overlays — not the story panel, choice list, or
   anything visible at first paint. Verify each modal still opens (loading flash acceptable; add a
   `loading:` spinner component only if noticeable).
3. **Narrow selectors**: audit every `useGameStore(` call site (`rg -n "useGameStore" web/src`):
   - Replace bare `useGameStore()` destructuring with per-field selectors
     (`useGameStore((s) => s.nodes)`) or `useShallow` from `zustand/react/shallow` for multi-field picks.
   - Components that only dispatch actions should select only the action (actions are stable references).
4. **Memoize hot leaves**: wrap `TreeNodeBox` (and siblings rendered per-node) in `React.memo`; ensure
   their props are primitives/stable references (derive per-node props in the parent with `useMemo` if a
   fresh object is currently created per render). Same for choice-list items if rendered per token update.
5. **Streaming isolation** (if ENH-002 landed): the streaming text consumer must be a leaf component
   selecting only `streamingText`, so token appends re-render one small component.
6. **Guardrails**: no `useEffect`-based hacks, no state duplication; this pass changes *where* renders
   happen, never *what* renders. UI must be pixel-identical.
7. **Tests**: existing vitest suites must stay green; add a render-count test for one memoized component
   if the harness supports it cheaply (optional — the build-size diff and profiler are the real checks).

## Files to touch
- Edit: page shells (`web/src/app/play/[gameId]/page.tsx`, `web/src/app/characters/page.tsx`),
  extracted modal import sites, `web/src/components/story/StoryGraph.tsx`, `useGameStore` call sites
- Read-only: `web/src/stores/game-store.ts` (selectors are consumer-side)

## Verification
```sh
cd web && npx tsc --noEmit && npm run lint && npm run test && npm run build
```
Compare the build output table against the step-1 baseline — `/play/[gameId]` first-load JS should drop.
Manual: open a game, open every modal, advance; with React DevTools profiler (or `console.count` probes
temporarily), confirm token/beat updates no longer render the page shell. E2E: `npm run e2e` if the
Playwright spec covers play flow.

## Rollback
Each step is independently revertible (dynamic-import lines, memo wrappers, selector changes are all
local edits). `git revert` the commit(s); no data or API surface involved.

## Pitfalls
- `next/dynamic` + `ssr: false` inside a client component is fine; don't dynamic-import components that
  hold form state you need preserved across open/close unless state lives in the parent/store.
- `React.memo` on a component receiving a fresh inline object/lambda every render is a no-op — fix the
  prop, or skip memoizing that component.
- Zustand selector equality is `Object.is` by default — selecting a derived array/object each call
  re-renders every time; use `useShallow` or select primitives.
- Don't chase the last few kilobytes: modals + selectors + `TreeNodeBox` are the whole payoff; stop there.
