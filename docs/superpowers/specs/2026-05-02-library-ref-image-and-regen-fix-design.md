# Library Reference Image + Regenerate Fix

**Date:** 2026-05-02

## Problem

Two gaps in reference image handling:

1. **CharacterCatalogScreen** (library browser) has no way to add, change, or remove a reference image on library characters. This only works in the Wizard and PortraitsScreen.
2. **Regenerate** in both PortraitsScreen and CharacterCatalogScreen ignores any stored reference image, generating from `physical_description` alone — even when the user previously uploaded a ref image via style-transfer.

## Design

### 1. Library browser: per-row reference image buttons

Add "Ref Image" / "Change Ref" and "Rm Ref" buttons to each library character row, following the same pattern as `PortraitsScreen`.

**Button layout** (in `_mount_row`, after existing "Regenerate" button):

- `ref_label = "Change Ref" if entry.reference_image_path else "Ref Image"`
- Mount `Button(ref_label, id=f"ref-{entry.id}")`
- If `entry.reference_image_path is not None`: mount `Button("Rm Ref", id=f"rm-ref-{entry.id}")`

**Ref image flow** (`_open_ref_image_modal`):

- Push `ReferenceImageModal(entry.name)`
- On dismiss with `ReferenceImageResult`, call `_apply_ref_image_worker`

**Worker** (`_apply_ref_image_worker`):

- Read source image, convert to RGBA PNG bytes
- For `"use_as_is"` mode: ref bytes become portrait bytes, set `portrait_prompt="(from reference image)"`
- For `"style_transfer"` mode: call `self._image_provider.generate_portrait(physical_description, transparent=True, art_style=app_state.DEFAULT_ART_STYLE, reference_image=png_bytes)`
- Persist via `save_library_character(entry, portrait_bytes, reference_bytes=ref_bytes)` (existing function already handles writing `reference.png` and setting `reference_image_path`)
- Rebuild the list

**Remove ref** (`_remove_reference_image`):

- Re-load entry, call `save_library_character` with `reference_bytes=None` and clear `reference_image_path` on the model
- Delete `library_reference_path(entry.id)` from disk
- Rebuild the list

**Button dispatch** (in `on_button_pressed`):

- `"ref-"` prefix → `_open_ref_image_modal(library_id)`
- `"rm-ref-"` prefix → `_remove_reference_image(library_id)`

### 2. Fix Regenerate to use stored reference image

All regenerate call sites that have access to a stored reference image should load and pass it to `generate_portrait`.

**CharacterCatalogScreen `_regenerate_worker`:**

- Before the `generate_portrait` call, check `entry.reference_image_path`
- If set, load ref bytes from `library_reference_path(entry.id)`
- Pass as `reference_image=ref_bytes` to `generate_portrait`

**PortraitsScreen `_regenerate_worker`:**

- Before the `generate_portrait` call, check `char.reference_image_path`
- If set, resolve via `paths.safe_join(paths.game_dir(save_id), char.reference_image_path)`
- Pass as `reference_image=ref_bytes` to `generate_portrait`

**PortraitsScreen `_create_outfit_worker`:**

- Same pattern: check `char.reference_image_path`, load ref bytes, pass to `generate_portrait`

### 3. CreateCharacterModal: optional reference image

Extend the character creation modal to allow attaching a reference image.

**UI additions to `CreateCharacterModal`:**

- Add a path `Input` (placeholder: "Reference image path (optional)") and a "Browse" button below the concept area
- "Browse" triggers `tkinter.filedialog.askopenfilename` (same pattern as `ReferenceImageModal`)
- On path change, show a small preview thumbnail (reuse `render_image_thumbnail` or inline `Pixels`)
- Store loaded PNG bytes in `self._ref_bytes: bytes | None`

**Model change to `CreateCharRequest`:**

- Add `reference_image: bytes | None = None`

**Flow through to worker:**

- On "Create" button press, include `reference_image=self._ref_bytes` in the `CreateCharRequest`
- In `_create_character_worker`, if `request.reference_image` is set:
  - For `"use_as_is"` mode not applicable here (always style-transfer during creation)
  - Pass `reference_image=request.reference_image` to `generate_portrait`
  - Persist via `save_library_character(..., reference_bytes=request.reference_image)`

## Files Changed

| File | Change |
|---|---|
| `src/storygen/screens/_create_char_modal.py` | Add reference image path input, browse button, preview |
| `src/storygen/screens/library_browser.py` | Add ref/rm-ref buttons, modal dispatch, apply worker, fix regen worker |
| `src/storygen/screens/portraits.py` | Fix `_regenerate_worker` and `_create_outfit_worker` to pass ref image |

## Not Changed

- `ReferenceImageModal` — reused as-is
- `save_library_character` — reused as-is (already handles `reference_bytes`)
- Image providers — no changes needed (OpenAI already supports `reference_image`, others silently discard it)
- Pipeline `_portraits` — out of scope (mid-story auto-generation is a different flow)
