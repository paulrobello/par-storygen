"""Extracted section logic for the God screens (ARC-012 / QA-006).

Textual's ``@work`` decorator and message routing force interactive handlers
and workers to live on the ``Screen`` itself, so these screens can't become
thin "compose-and-delegate" shells the way a plain MVC split would. What *can*
move out — and does, module by module — is the cohesive, side-effect-free
logic behind each section: pure transformations, option builders, and narrow
helper classes that take specific dependencies rather than a whole ``Screen``.

Each screen's extracted logic lives in a module named after that section.
The screens keep their message handlers, ``@work`` workers, and the
``save_game`` / ``notify`` / ``_rebuild`` side effects, delegating the pure
core here so it is unit-testable without a Textual ``App``.
"""
