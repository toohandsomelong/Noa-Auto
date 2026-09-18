from __future__ import annotations

import dataclasses

import pytest

from core.match_result import MatchResult


def test_center_of_even_size():
    assert MatchResult((10, 10), (10, 10), 0.9).center == (15, 15)


def test_center_of_odd_size_uses_integer_division():
    assert MatchResult((0, 0), (5, 5), 0.9).center == (2, 2)


def test_center_with_offset_location():
    assert MatchResult((100, 50), (20, 40), 0.8).center == (110, 70)


def test_match_result_is_frozen():
    result = MatchResult((0, 0), (1, 1), 0.5)
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.confidence = 0.1
