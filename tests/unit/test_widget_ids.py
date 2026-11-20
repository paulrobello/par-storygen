"""Tests for embedding arbitrary strings in Textual widget ids."""

from __future__ import annotations

import pytest
from textual.dom import check_identifiers

from storygen.screens._widget_ids import decode_id_part, encode_id_part


@pytest.mark.parametrize(
    "value",
    ["alyx", "char-0", "Jane Doe", "john_smith", 'Zoë\'s "dog"', "a__b", "_000020", ""],
)
def test_round_trip_and_valid_identifier(value: str) -> None:
    encoded = encode_id_part(value)
    assert decode_id_part(encoded) == value
    assert "__" not in encoded
    check_identifiers("id", f"prefix-{encoded}")


def test_safe_values_pass_through_unchanged() -> None:
    assert encode_id_part("char-0") == "char-0"
    assert encode_id_part("3f2a9c") == "3f2a9c"
