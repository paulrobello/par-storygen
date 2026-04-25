"""Smoke test: package imports and exposes __version__."""

import storygen


def test_version_exposed() -> None:
    assert hasattr(storygen, "__version__")
    assert isinstance(storygen.__version__, str)
    assert storygen.__version__ != ""
