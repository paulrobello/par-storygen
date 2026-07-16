"""Headless runtime utilities shared by the TUI and the FastAPI surface.

Houses logic that has no Textual/Starlette/FastAPI dependency so it can be
imported by both composition roots (``storygen.app`` and ``storygen_api``):

- :mod:`.adapters` — pydantic-ai → pipeline Protocol adapters + image-provider
  helpers (extracted from the duplicated blocks in ``app.py`` and
  ``storygen_api/deps.py`` per ARC-003).
- :mod:`.wizard_flow` — the headless wizard state machine (moved out of
  ``screens/wizard.py`` per ARC-005).
"""
