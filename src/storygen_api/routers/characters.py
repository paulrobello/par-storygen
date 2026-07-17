"""Cross-game character library + per-portrait regeneration routes."""

from __future__ import annotations

import io
import logging
from datetime import UTC, datetime
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from PIL import Image

from storygen.core.models import Character
from storygen.images.split_provider import SplitImageProvider
from storygen.llm import agents as agent_mod
from storygen.llm.provider_factory import build_text_model
from storygen.storage import app_state
from storygen.storage import paths as save_paths
from storygen.storage.library import (
    PLACEHOLDER_PNG,
    LibraryCharacter,
    LibrarySource,
    delete_library_character,
    library_portrait_path,
    library_reference_path,
    list_library_characters,
    load_library_character,
    save_library_character,
)
from storygen_api.deps import get_app_config, get_session_manager, get_wizard_image_provider
from storygen_api.rate_limit import enforce_rate_limit
from storygen_api.schemas import (
    CharacterCreateRequest,
    CharacterExportRequest,
    CharacterLibraryEntry,
    CharacterLibraryResponse,
    CharacterUpdateRequest,
    PortraitEditRequest,
    PortraitRegenerateRequest,
    StoryImportRequest,
)
from storygen_api.security import verify_token
from storygen_api.session import PipelineSessionManager

router = APIRouter(
    prefix="/api/characters",
    tags=["characters"],
    # SEC-001: every characters route reads, mutates user content, or triggers
    # cost-incurring LLM/image generation. Gate all of them.
    dependencies=[Depends(verify_token)],
)

_logger = logging.getLogger(__name__)


def _lib_to_entry(char: LibraryCharacter) -> CharacterLibraryEntry:
    portrait_path = library_portrait_path(char.id)
    ref_path = library_reference_path(char.id)
    return CharacterLibraryEntry(
        id=char.id,
        name=char.name,
        backstory=char.backstory,
        personality=char.personality,
        physical_description=char.physical_description,
        portrait_prompt=char.portrait_prompt,
        exported_at=char.exported_at,
        source=char.source,
        has_portrait=bool(portrait_path.exists()),
        has_reference_image=bool(char.reference_image_path and ref_path.exists()),
        reference_image_path=char.reference_image_path,
    )


def _load_char_or_404(library_id: str) -> LibraryCharacter:
    """Load a library character or raise HTTPException."""
    try:
        return load_library_character(library_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Character not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid library ID") from exc


def _get_ref_bytes(char: LibraryCharacter) -> bytes | None:
    """Read reference image bytes if the character has one."""
    if char.reference_image_path:
        ref_path = library_reference_path(char.id)
        if ref_path.exists():
            return ref_path.read_bytes()
    return None


def _image_to_png_bytes(image_bytes: bytes) -> bytes:
    """Convert arbitrary image bytes to PNG."""
    with Image.open(io.BytesIO(image_bytes)) as im:
        im = im.convert("RGBA")
        buf = io.BytesIO()
        im.save(buf, format="PNG")
        return buf.getvalue()


def _read_save_asset(save_id: str, rel_path: str) -> bytes | None:
    """Read a save-relative asset (portrait/reference) safely.

    Performs ``safe_join`` containment + read; returns ``None`` when the path
    is invalid or unreadable so callers can fall back to the placeholder.
    """
    try:
        abs_path = save_paths.safe_join(save_paths.game_dir(save_id), rel_path)
        if abs_path.exists():
            return abs_path.read_bytes()
    except (ValueError, OSError) as exc:
        _logger.debug("asset copy skipped for %s/%s: %s", save_id, rel_path, exc)
    return None


# ---------------------------------------------------------------------------
# Existing CRUD endpoints
# ---------------------------------------------------------------------------


@router.get("", response_model=CharacterLibraryResponse)
async def list_characters() -> CharacterLibraryResponse:
    """List all library characters."""
    chars = list_library_characters()
    return CharacterLibraryResponse(characters=[_lib_to_entry(c) for c in chars])


@router.get("/{library_id}", response_model=CharacterLibraryEntry)
async def get_character(library_id: str) -> CharacterLibraryEntry:
    """Get a single library character."""
    char = _load_char_or_404(library_id)
    return _lib_to_entry(char)


@router.get("/{library_id}/portrait")
async def get_character_portrait(library_id: str) -> FileResponse:
    """Serve a library character's portrait PNG."""
    try:
        portrait_path = library_portrait_path(library_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid library ID") from exc
    if not portrait_path.exists():
        raise HTTPException(status_code=404, detail="Portrait not found")
    return FileResponse(str(portrait_path), media_type="image/png")


@router.post("", response_model=CharacterLibraryEntry, status_code=201)
async def export_character(body: CharacterExportRequest) -> CharacterLibraryEntry:
    """Export a character to the library."""
    lib_id = uuid4().hex
    exported_from = None
    if body.save_id:
        exported_from = LibrarySource(
            save_id=body.save_id,
            save_title=body.save_title,
            character_id=body.character_id,
        )

    char = LibraryCharacter(
        id=lib_id,
        name=body.name,
        backstory=body.backstory,
        personality=body.personality,
        physical_description=body.physical_description,
        portrait_prompt=body.portrait_prompt or body.physical_description,
        exported_at=datetime.now(UTC),
        exported_from=exported_from,
        source="export",
    )

    save_library_character(char, PLACEHOLDER_PNG)
    return _lib_to_entry(char)


@router.delete("/{library_id}", status_code=204)
async def delete_character(library_id: str) -> None:
    """Remove a character from the library."""
    try:
        delete_library_character(library_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid library ID") from exc


@router.put("/{library_id}", response_model=CharacterLibraryEntry)
async def update_character(
    library_id: str,
    body: CharacterUpdateRequest,
) -> CharacterLibraryEntry:
    """Edit character fields."""
    char = _load_char_or_404(library_id)

    updates: dict[str, object] = {}
    if body.name is not None:
        updates["name"] = body.name
    if body.backstory is not None:
        updates["backstory"] = body.backstory
    if body.personality is not None:
        updates["personality"] = body.personality
    if body.physical_description is not None:
        updates["physical_description"] = body.physical_description
    if body.portrait_prompt is not None:
        updates["portrait_prompt"] = body.portrait_prompt

    if updates:
        char = char.model_copy(update=updates)
        # Re-save with existing portrait
        portrait_path = library_portrait_path(library_id)
        portrait_bytes = portrait_path.read_bytes() if portrait_path.exists() else b""
        if portrait_bytes:
            save_library_character(char, portrait_bytes)
        else:
            save_library_character(char, PLACEHOLDER_PNG)

    return _lib_to_entry(char)


# ---------------------------------------------------------------------------
# New endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/{library_id}/regenerate-portrait",
    response_model=CharacterLibraryEntry,
    dependencies=[Depends(enforce_rate_limit)],
)
async def regenerate_portrait(
    library_id: str,
    body: PortraitRegenerateRequest,
    image_provider: SplitImageProvider = Depends(get_wizard_image_provider),
) -> CharacterLibraryEntry:
    """Regenerate a library character's portrait using their stored portrait_prompt."""
    char = _load_char_or_404(library_id)
    ref_bytes = _get_ref_bytes(char)
    prompt = char.portrait_prompt or char.physical_description

    try:
        portrait_bytes = await image_provider.generate_portrait(
            prompt,
            transparent=True,
            art_style=body.art_style,
            reference_image=ref_bytes,
        )
    except Exception as exc:
        # SEC-004: log server-side; return a generic message (no str(exc)).
        _logger.exception("Portrait regeneration failed")
        raise HTTPException(status_code=500, detail="Portrait generation failed") from exc

    save_library_character(char, portrait_bytes)
    return _lib_to_entry(char)


@router.post(
    "/{library_id}/edit-portrait",
    response_model=CharacterLibraryEntry,
    dependencies=[Depends(enforce_rate_limit)],
)
async def edit_portrait(
    library_id: str,
    body: PortraitEditRequest,
    image_provider: SplitImageProvider = Depends(get_wizard_image_provider),
) -> CharacterLibraryEntry:
    """Edit portrait prompt and regenerate."""
    char = _load_char_or_404(library_id)

    if body.mode == "edit":
        original = char.portrait_prompt or char.physical_description
        description = f"{original}\n\nEdit instructions: {body.prompt}"
    else:
        description = body.prompt

    ref_bytes: bytes | None = None
    if body.use_current_as_ref:
        portrait_path = library_portrait_path(library_id)
        if portrait_path.exists():
            ref_bytes = portrait_path.read_bytes()
        # Also use stored reference if available
        if ref_bytes is None:
            ref_bytes = _get_ref_bytes(char)

    try:
        portrait_bytes = await image_provider.generate_portrait(
            description,
            transparent=True,
            art_style=body.art_style,
            reference_image=ref_bytes,
        )
    except Exception as exc:
        # SEC-004: log server-side; return a generic message (no str(exc)).
        _logger.exception("Portrait edit-regen failed")
        raise HTTPException(status_code=500, detail="Portrait generation failed") from exc

    char = char.model_copy(update={"portrait_prompt": description})
    save_library_character(char, portrait_bytes)
    return _lib_to_entry(char)


@router.post(
    "/{library_id}/reference-image",
    response_model=CharacterLibraryEntry,
    dependencies=[Depends(enforce_rate_limit)],
)
async def upload_reference_image(
    library_id: str,
    image: UploadFile,
    mode: str = "style_transfer",
    image_provider: SplitImageProvider = Depends(get_wizard_image_provider),
) -> CharacterLibraryEntry:
    """Upload a reference image for a library character.

    Accepts multipart form with ``image`` file and ``mode`` field
    (``"use_as_is"`` or ``"style_transfer"``).
    """
    char = _load_char_or_404(library_id)

    raw_bytes = await image.read()
    if not raw_bytes:
        raise HTTPException(status_code=400, detail="Empty image upload")

    try:
        png_bytes = _image_to_png_bytes(raw_bytes)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid image file") from exc

    if mode == "use_as_is":
        portrait_bytes = png_bytes
        char = char.model_copy(
            update={
                "portrait_prompt": "(from reference image)",
                "reference_image_path": "reference.png",
            }
        )
    else:
        # style_transfer
        try:
            portrait_bytes = await image_provider.generate_portrait(
                char.physical_description,
                transparent=True,
                art_style=app_state.DEFAULT_ART_STYLE,
                reference_image=png_bytes,
            )
        except Exception as exc:
            # SEC-004: log server-side; return a generic message (no str(exc)).
            _logger.exception("Style-transfer failed")
            raise HTTPException(
                status_code=500, detail="Style-transfer generation failed"
            ) from exc
        char = char.model_copy(
            update={
                "portrait_prompt": char.physical_description,
                "reference_image_path": "reference.png",
            }
        )

    save_library_character(char, portrait_bytes, reference_bytes=png_bytes)
    return _lib_to_entry(char)


@router.delete("/{library_id}/reference-image", response_model=CharacterLibraryEntry)
async def delete_reference_image(library_id: str) -> CharacterLibraryEntry:
    """Remove a character's reference image."""
    char = _load_char_or_404(library_id)

    ref_path = library_reference_path(library_id)
    if ref_path.exists():
        ref_path.unlink()

    char = char.model_copy(update={"reference_image_path": None})

    # Re-save with existing portrait (reference removed)
    portrait_path = library_portrait_path(library_id)
    portrait_bytes = portrait_path.read_bytes() if portrait_path.exists() else PLACEHOLDER_PNG
    save_library_character(char, portrait_bytes)
    return _lib_to_entry(char)


@router.get("/{library_id}/reference-image")
async def get_reference_image(library_id: str) -> Response:
    """Serve a library character's reference image PNG."""
    try:
        ref_path = library_reference_path(library_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid library ID") from exc
    if not ref_path.exists():
        raise HTTPException(status_code=404, detail="Reference image not found")
    return FileResponse(str(ref_path), media_type="image/png")


@router.post(
    "/create",
    response_model=CharacterLibraryEntry,
    status_code=201,
    dependencies=[Depends(enforce_rate_limit)],
)
async def create_character(
    body: CharacterCreateRequest,
    image_provider: SplitImageProvider = Depends(get_wizard_image_provider),
) -> CharacterLibraryEntry:
    """Create a new library character via LLM from a concept description."""
    config = get_app_config()
    text_model = build_text_model(config.text_config)

    agent = agent_mod.build_catalog_character_agent(text_model)

    prompt = body.concept
    if body.name:
        prompt = f"Create a character named '{body.name}'. {body.concept}"

    try:
        result = await agent.run(prompt)  # type: ignore[reportUnknownMemberType]
        raw_output = getattr(result, "output", None)
    except Exception as exc:
        # SEC-004: log server-side; return a generic message (no str(exc)).
        _logger.exception("Character generation LLM call failed")
        raise HTTPException(status_code=500, detail="Character generation failed") from exc

    if not isinstance(raw_output, list) or not raw_output:
        raise HTTPException(status_code=500, detail="LLM returned no characters")

    first = raw_output[0]  # type: ignore[reportUnknownVariableType]
    if not isinstance(first, Character):
        raise HTTPException(status_code=500, detail="LLM returned unexpected type")

    char: Character = first
    if body.name:
        char = char.model_copy(update={"name": body.name})

    # Generate portrait
    portrait_bytes: bytes = PLACEHOLDER_PNG
    try:
        portrait_bytes = await image_provider.generate_portrait(
            char.physical_description,
            transparent=True,
            art_style=app_state.DEFAULT_ART_STYLE,
        )
    except Exception:
        # Not a SEC-004 leak (no str(exc)); placeholder is the documented fallback.
        _logger.exception("Portrait generation failed during character creation")
        # Continue with placeholder

    lib_char = LibraryCharacter(
        id=uuid4().hex,
        name=char.name,
        backstory=char.backstory,
        personality=char.personality,
        physical_description=char.physical_description,
        portrait_prompt=char.physical_description,
        exported_at=datetime.now(UTC),
        source="created",
    )
    save_library_character(lib_char, portrait_bytes)
    return _lib_to_entry(lib_char)


@router.post("/import-from-story", response_model=list[CharacterLibraryEntry], status_code=201)
async def import_from_story(
    body: StoryImportRequest,
    mgr: PipelineSessionManager = Depends(get_session_manager),
) -> list[CharacterLibraryEntry]:
    """Import characters from a saved game into the library."""
    # ARC-101: use the owned save for consistency with the session contract.
    try:
        save = mgr.get_or_load_save(body.save_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Save not found") from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid save_id") from exc

    save_id = str(save.id)
    created: list[CharacterLibraryEntry] = []

    for char_id in body.character_ids:
        char = next((c for c in save.characters if c.id == char_id), None)
        if char is None:
            continue

        # Copy portrait bytes (fall back to placeholder when missing/unreadable)
        portrait_bytes: bytes = PLACEHOLDER_PNG
        if char.portrait_path:
            read = _read_save_asset(save_id, char.portrait_path)
            if read is not None:
                portrait_bytes = read

        # Copy reference image bytes if present
        ref_bytes: bytes | None = None
        if char.reference_image_path:
            ref_bytes = _read_save_asset(save_id, char.reference_image_path)

        lib_char = LibraryCharacter(
            id=uuid4().hex,
            name=char.name,
            backstory=char.backstory,
            personality=char.personality,
            physical_description=char.physical_description,
            portrait_prompt=char.portrait_prompt or char.physical_description,
            exported_at=datetime.now(UTC),
            exported_from=LibrarySource(
                save_id=save_id,
                save_title=save.theme.title,
                character_id=char.id,
            ),
            source="story_import",
        )
        save_library_character(lib_char, portrait_bytes, reference_bytes=ref_bytes)
        created.append(_lib_to_entry(lib_char))

    return created
