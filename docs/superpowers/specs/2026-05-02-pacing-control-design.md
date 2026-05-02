# Dynamic Difficulty / Pacing Control

**Date:** 2026-05-02

## Problem

Beat narration length and choice count are hardcoded in the beat system prompt ("2-5 paragraphs", "2-4 options"). Players who want a slow, atmospheric experience or a fast, action-heavy one cannot tune this without editing prompts.

## Solution

Add a `Pacing` enum (`slow | moderate | fast`) set during the wizard's LENGTH step. The value flows through `GameSave` → `build_beat_agent()` → `beat_system_prompt()`, which dynamically adjusts paragraph-count ranges, choice-count ranges, and style guidance. Escalation thresholds in `_pacing_hint_for_depth()` also adapt per pacing level.

## Type & Storage

```python
# models.py
Pacing = Literal["slow", "moderate", "fast"]
```

Default: `"moderate"` (identical to current hardcoded behavior).

**`GameSave`** gains `pacing: Pacing = "moderate"` — existing saves without the field deserialize with the default via Pydantic.

**`WizardDefaults`** gains `pacing: str = "moderate"` and `DEFAULT_PACING = "moderate"` is added to `app_state.py`.

**Settings screen**: Add a pacing selector to the wizard defaults section so the default pacing for new stories is configurable.

## Prompt Mapping

`beat_system_prompt()` gains a `pacing: Pacing = "moderate"` parameter. A helper maps pacing to ranges:

| Pacing | Narration paragraphs | Choices | Extra prompt guidance |
|--------|---------------------|---------|----------------------|
| slow | 4–6 | 2 | "Take time with description, atmosphere, and inner thoughts. Choices should feel weighty." |
| moderate | 2–5 | 2–4 | *(none — current behavior)* |
| fast | 1–3 | 3–5 | "Keep the pace brisk — action over description. Give the player frequent choices." |

The hardcoded strings `"2-5 paragraphs"` and `"2-4 meaningfully different options"` in the prompt become dynamic based on the pacing parameter.

## Escalation Tuning

`_pacing_hint_for_depth(depth, target)` becomes `_pacing_hint_for_depth(depth, target, pacing)`. Thresholds adjust:

- **slow**: thresholds multiplied by 1.4 (story breathes longer before escalation)
- **moderate**: current thresholds unchanged
- **fast**: thresholds multiplied by 0.7 (story tightens sooner)

This means a fast-paced story with `target_major_beats=5` starts tightening around depth 2 instead of 3, while a slow-paced story gives more room.

## Wizard Integration

The LENGTH step (`WizardStep.LENGTH`) gains a `RadioSet` with three options: Slow / Moderate / Fast. Default comes from `WizardDefaults.pacing`. The step header updates to "Length & Pacing". The existing `target_major_beats` slider remains unchanged — pacing and story length are orthogonal controls.

Layout: RadioSet below the existing slider, with a one-line description for each option:
- Slow: "Long narration, fewer but weightier choices"
- Moderate: "Balanced narration and choices"
- Fast: "Short narration, more frequent choices"

The selected value is passed through `WizardFlow` to `GameSave.pacing`.

## App Wiring Chain

```
WizardDefaults.pacing → WizardScreen LENGTH step → WizardFlow
  → GameSave.pacing
  → build_beat_agent(pacing=save.pacing)
    → beat_system_prompt(pacing=...)
      → dynamic paragraph/choice ranges
    → _pacing_hint_for_depth(depth, target, pacing)
      → pacing-adjusted escalation thresholds
```

## Files Changed

| File | Change |
|------|--------|
| `src/storygen/core/models.py` | Add `Pacing` type alias |
| `src/storygen/storage/app_state.py` | Add `DEFAULT_PACING`, `pacing` field to `WizardDefaults` |
| `src/storygen/storage/save.py` | Add `pacing: Pacing` field to `GameSave` |
| `src/storygen/llm/prompts.py` | Add `pacing` param to `beat_system_prompt()`, dynamic ranges + helper |
| `src/storygen/llm/agents.py` | Add `pacing` param to `build_beat_agent()` |
| `src/storygen/pipeline.py` | Pass pacing to `_pacing_hint_for_depth()`, adjust thresholds |
| `src/storygen/screens/wizard.py` | Add pacing RadioSet to LENGTH step, wire into flow |
| `src/storygen/app.py` | Pass `save.pacing` to `build_beat_agent()` |
| `src/storygen/screens/settings.py` | Add pacing selector to wizard defaults section |

## Backward Compatibility

- Existing saves without `pacing` field get `"moderate"` via Pydantic default — behavior is unchanged.
- Existing wizard defaults without `pacing` get `"moderate"` — no migration needed.
- `beat_system_prompt()` defaults `pacing="moderate"` so callers that don't pass it get current behavior.

## Testing

- Unit test the pacing-to-range mapping in `prompts.py`
- Unit test `_pacing_hint_for_depth()` with each pacing level
- Unit test `GameSave` serialization/deserialization with and without pacing field
- Wizard flow test: verify pacing is captured and stored in the resulting `GameSave`
