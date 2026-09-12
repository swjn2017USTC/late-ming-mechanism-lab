"""Scalar reads from Polars frames, typed once so every analysis module can rely on them.

Polars returns a union type for aggregations over a column, which strict typing will not accept as
a float. Rather than casting in a dozen places — six of which were already drifting apart — the
conversions live here, with the two rules stated once:

- an empty frame, an absent column, or an all-null column yields ``0.0``, because every caller in
  this package is summing or averaging a quantity that the run may legitimately not have produced
  yet, and a missing measurement of a zero-sum quantity is zero;
- the value is otherwise taken as-is, so no caller can hide a surprising type behind a default.
"""

from __future__ import annotations

from typing import cast

import polars as pl

MISSING = 0.0


def total(frame: pl.DataFrame, column: str) -> float:
    """Sum of a numeric column, or 0.0 when there is nothing to sum."""
    if frame.is_empty() or column not in frame.columns:
        return MISSING
    value = frame[column].sum()
    return MISSING if value is None else cast("float", value)


def mean(frame: pl.DataFrame, column: str) -> float:
    """Mean of a numeric column, or 0.0 when the column is empty."""
    if frame.is_empty() or column not in frame.columns:
        return MISSING
    value = frame[column].mean()
    return MISSING if value is None else cast("float", value)


def last(frame: pl.DataFrame, column: str) -> float:
    """Last value of a numeric column, or 0.0 when the column is empty."""
    if frame.is_empty() or column not in frame.columns:
        return MISSING
    value = frame[column].last()
    return MISSING if value is None else cast("float", value)


def largest(frame: pl.DataFrame, column: str) -> float:
    """Largest value of a numeric column, or 0.0 when the column is empty."""
    if frame.is_empty() or column not in frame.columns:
        return MISSING
    value = frame[column].max()
    return MISSING if value is None else cast("float", value)


def smallest(frame: pl.DataFrame, column: str) -> float:
    """Smallest value of a numeric column, or 0.0 when the column is empty."""
    if frame.is_empty() or column not in frame.columns:
        return MISSING
    value = frame[column].min()
    return MISSING if value is None else cast("float", value)
