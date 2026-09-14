"""The chain readers: each declared constraint comes back as a number, a missing one is refused.

A chain summary is what a diagnosis is written from, so the readers have to be exact about what they
will and will not accept: a field the log does not carry is an error rather than a zero, because a
zero would read as "that constraint never bound", which is the opposite of "nothing recorded it".
"""

from __future__ import annotations

import polars as pl
import pytest

from late_ming_lab.analysis.chains import (
    MIGRATION_FIELDS,
    PRICE_FIELDS,
    RELIEF_FIELDS,
    ChainError,
    chain_deltas,
    chain_summary,
    migration_chain,
    price_chain,
    relief_chain,
)

PRICE_ROW = {
    "tick": 0,
    "region": "a",
    "outcome": "inventory",
    **{name: 1.0 for name in PRICE_FIELDS},
}
RELIEF_ROW = {
    "tick": 0,
    "region": "a",
    "outcome": "stock",
    **{name: 1.0 for name in RELIEF_FIELDS},
}
GATE_ROW = {
    "tick": 0,
    "agent_id": "a:1",
    "region": "a",
    "outcome": "silver",
    **{name: 1.0 for name in MIGRATION_FIELDS},
}


def _frame(event_type: str, rows: list[dict[str, object]]) -> pl.DataFrame:
    return pl.DataFrame(
        [
            {
                "tick": row["tick"] if isinstance(row["tick"], int) else 0,
                "event_type": event_type,
                "region": str(row["region"]),
                "agent_id": str(row.get("agent_id", "a")),
                "outcome": str(row["outcome"]),
                "trigger_json": _payload(row),
            }
            for row in rows
        ],
        schema={
            "tick": pl.Int64,
            "event_type": pl.Utf8,
            "region": pl.Utf8,
            "agent_id": pl.Utf8,
            "outcome": pl.Utf8,
            "trigger_json": pl.Utf8,
        },
    )


def _payload(row: dict[str, object]) -> str:
    fields = {
        name: row[name]
        for name in (*PRICE_FIELDS, *RELIEF_FIELDS, *MIGRATION_FIELDS)
        if name in row
    }
    return "{" + ", ".join(f'"{name}": {value}' for name, value in fields.items()) + "}"


def test_each_chain_reads_its_own_event_and_its_declared_fields() -> None:
    events = pl.concat(
        [
            _frame("MARKET_CONSTRAINT", [PRICE_ROW]),
            _frame("RELIEF_CONSTRAINT", [RELIEF_ROW]),
            _frame("MIGRATION_GATE", [GATE_ROW]),
        ]
    )
    assert price_chain(events).height == 1
    assert relief_chain(events).height == 1
    assert migration_chain(events).height == 1
    assert price_chain(events)["outcome"].to_list() == ["inventory"]


def test_a_chain_with_no_events_is_refused_rather_than_read_as_empty() -> None:
    """An empty chain would sum to zero, and zero is a measurement rather than a missing log."""
    events = _frame("MARKET_CONSTRAINT", [PRICE_ROW])
    with pytest.raises(ChainError, match="relief"):
        relief_chain(events)


def test_a_chain_event_missing_a_declared_field_is_refused() -> None:
    """A partial row would leave one constraint silently absent from the summary."""
    partial = {key: value for key, value in PRICE_ROW.items() if key != "unfilled_demand_shi"}
    events = _frame("MARKET_CONSTRAINT", [partial])
    with pytest.raises(ChainError, match="unfilled_demand_shi"):
        price_chain(events)


def test_the_summary_reports_every_binding_share_and_them_alone() -> None:
    events = pl.concat(
        [
            _frame("MARKET_CONSTRAINT", [PRICE_ROW, {**PRICE_ROW, "outcome": "ceiling"}]),
            _frame("RELIEF_CONSTRAINT", [RELIEF_ROW]),
            _frame("MIGRATION_GATE", [GATE_ROW]),
        ]
    )
    summary = chain_summary(events)
    assert summary["price_bound_share.inventory"] == pytest.approx(0.5)
    assert summary["price_bound_share.ceiling"] == pytest.approx(0.5)
    assert summary["relief_bound_share.stock"] == pytest.approx(1.0)
    assert summary["migration_gate_share.silver"] == pytest.approx(1.0)
    assert summary["price_wanted_shi"] == pytest.approx(2.0)


def test_chain_deltas_names_only_what_moved() -> None:
    left = {"a": 1.0, "b": 2.0}
    right = {"a": 1.0, "b": 3.0, "c": 4.0}
    assert chain_deltas(left, right) == {"b": 1.0}
