"""The three chains V2-P04 diagnoses, read back from the event log.

A price, a relief release and a departure are each the *outcome* of a chain, and a report that shows
only the outcome cannot say which link held. These readers keep the links apart:

```text
price chain        per node-month: what the merchant held, what buyers wanted and could not get,
                   what the trade links could carry and at what cost, and the price bounds — with
                   the one that bound the posted price
relief chain       per county-month: granary stock, treasury silver, logistics capacity and
                   eligibility, with the one that bound the release
migration chain    per cohort-month: the gate that decided the move, and the split between staying,
                   moving within the region and leaving it
```

Nothing here computes a verdict. The chains are read as frames, and the phase's diagnosis is written
from them rather than from a scalar that already merged the links.
"""

from __future__ import annotations

from typing import Final

import polars as pl

from late_ming_lab.systems.fiscal import RELIEF_CONSTRAINT_EVENT
from late_ming_lab.systems.markets import MARKET_CONSTRAINT_EVENT
from late_ming_lab.systems.migration import MIGRATION_GATE_EVENT

#: The binding tokens each chain declares, so a reader can check a token it does not recognise.
PRICE_BINDINGS: Final[tuple[str, ...]] = ("inventory", "ceiling", "floor", "none")
RELIEF_BINDINGS: Final[tuple[str, ...]] = ("stock", "silver", "capacity", "eligibility", "none")
MIGRATION_GATES: Final[tuple[str, ...]] = (
    "moved",
    "no-destination",
    "no-receiving-cohort",
    "capacity",
    "silver",
    "below-minimum",
    "returned",
    "temporary",
    "not-eligible",
)

#: The numeric fields each chain's event carries.
PRICE_FIELDS: Final[tuple[str, ...]] = (
    "price_tael_per_shi",
    "price_unclamped_tael_per_shi",
    "price_ceiling_tael_per_shi",
    "inventory_shi",
    "local_need_shi",
    "cover_of_target",
    "wanted_shi",
    "unfilled_demand_shi",
    "unaffordable_demand_shi",
    "demand_pressure",
    "trade_inbound_capacity_shi",
    "trade_best_margin_tael_per_shi",
    "transport_cost_tael_per_shi",
)
RELIEF_FIELDS: Final[tuple[str, ...]] = (
    "need_shi",
    "eligible_households",
    "eligible_adults",
    "grain_stock_shi",
    "treasury_tael",
    "capacity_relief",
    "demand_shi",
    "released_shi",
    "stock_bound_shi",
    "capacity_bound_shi",
    "eligibility_bound_shi",
    "unmet_after_shi",
)
MIGRATION_FIELDS: Final[tuple[str, ...]] = (
    "households",
    "adults",
    "silver_per_household",
    "eligible_permanent",
    "destination_is_exit",
    "edge_capacity_households",
    "edge_risk",
    "migration_cost_tael",
    "movers_households",
)


class ChainError(ValueError):
    """Raised when a chain cannot be read from a log at all."""


def _numeric(events: pl.DataFrame, fields: tuple[str, ...]) -> pl.DataFrame:
    """The trigger JSON pulled apart into numeric columns, with a missing field refused.

    A chain event missing one of its declared fields would be a chain whose links are silently
    absent, which is the failure this module exists to prevent; refusing is cheaper than a report
    that reads a null as a zero.
    """
    if events.is_empty():
        return events
    expressions = []
    for field in fields:
        expression = (
            events["trigger_json"].str.json_path_match(f"$.{field}").cast(pl.Float64, strict=False)
        )
        if expression.null_count() == events.height:
            raise ChainError(f"chain events carry no {field!r} in their trigger")
        expressions.append(expression.alias(field))
    return events.with_columns(expressions)


def price_chain(events: pl.DataFrame) -> pl.DataFrame:
    """Per node-month, every constraint that could have moved the price, and which one did."""
    frame = events.filter(pl.col("event_type") == MARKET_CONSTRAINT_EVENT)
    if frame.is_empty():
        raise ChainError(
            f"no {MARKET_CONSTRAINT_EVENT} rows: the log predates the price-chain instrumentation"
        )
    return (
        _numeric(frame, PRICE_FIELDS)
        .select(["tick", "region", "outcome", *PRICE_FIELDS])
        .sort(["region", "tick"])
    )


def relief_chain(events: pl.DataFrame) -> pl.DataFrame:
    """Per county-month, the four relief bottlenecks and which one bound the release."""
    frame = events.filter(pl.col("event_type") == RELIEF_CONSTRAINT_EVENT)
    if frame.is_empty():
        raise ChainError(
            f"no {RELIEF_CONSTRAINT_EVENT} rows: the log predates the relief-chain instrumentation"
        )
    return (
        _numeric(frame, RELIEF_FIELDS)
        .select(["tick", "region", "outcome", *RELIEF_FIELDS])
        .sort(["region", "tick"])
    )


def migration_chain(events: pl.DataFrame) -> pl.DataFrame:
    """Per cohort-month, the gate that decided the move and what the cohort could afford."""
    frame = events.filter(pl.col("event_type") == MIGRATION_GATE_EVENT)
    if frame.is_empty():
        raise ChainError(
            f"no {MIGRATION_GATE_EVENT} rows: the log predates the migration instrumentation"
        )
    return (
        _numeric(frame, MIGRATION_FIELDS)
        .select(["tick", "agent_id", "region", "outcome", *MIGRATION_FIELDS])
        .sort(["agent_id", "tick"])
    )


def _as_float(value: object) -> float:
    """A polars aggregate as a float, refusing anything that is not a number.

    Polars types an aggregate as a union because a column can hold anything; a chain summary is
    arithmetic over numbers, so a value that is not one is an error rather than a coerced zero.
    """
    if isinstance(value, (int, float)):
        return float(value)
    raise ChainError(f"expected a number from the log, got {type(value).__name__}")


def chain_summary(
    events: pl.DataFrame, *, windows: tuple[tuple[str, int, int], ...] = ()
) -> dict[str, float]:
    """The chains' headline facts for one run, as numbers a report may print.

    Binding-constraint shares are reported rather than a single "coverage": a share of months in
    which the granary was empty and a share in which nobody qualified are different findings, and
    the whole point of the phase is that they not be merged.

    `windows` is a tuple of ``(label, first_tick, last_tick)``; each is reported separately so a
    chain can be read in the hold-out years without being read only there.
    """
    summary: dict[str, float] = {}
    price = price_chain(events)
    relief = relief_chain(events)
    migration = migration_chain(events)
    for token in PRICE_BINDINGS:
        summary[f"price_bound_share.{token}"] = _as_float((price["outcome"] == token).mean())
    summary["price_unfilled_demand_shi"] = _as_float(price["unfilled_demand_shi"].sum())
    summary["price_unaffordable_demand_shi"] = _as_float(price["unaffordable_demand_shi"].sum())
    summary["price_wanted_shi"] = _as_float(price["wanted_shi"].sum())
    summary["price_ceiling_share"] = _as_float(
        (price["price_tael_per_shi"] >= price["price_ceiling_tael_per_shi"] * 0.999).mean()
    )
    summary["price_max_tael_per_shi"] = _as_float(price["price_tael_per_shi"].max())
    summary["price_dispersion_mean"] = _as_float(_dispersion(price)["cv"].mean())
    for token in RELIEF_BINDINGS:
        summary[f"relief_bound_share.{token}"] = _as_float((relief["outcome"] == token).mean())
    summary["relief_released_shi"] = _as_float(relief["released_shi"].sum())
    summary["relief_need_shi"] = _as_float(relief["need_shi"].sum())
    summary["relief_coverage_share"] = (
        summary["relief_released_shi"] / summary["relief_need_shi"]
        if summary["relief_need_shi"] > 0.0
        else 0.0
    )
    summary["relief_eligible_households_mean"] = _as_float(relief["eligible_households"].mean())
    for token in MIGRATION_GATES:
        summary[f"migration_gate_share.{token}"] = _as_float((migration["outcome"] == token).mean())
    summary["migration_movers_households"] = _as_float(migration["movers_households"].sum())
    summary["migration_silver_refusals_households"] = float(
        migration.filter((pl.col("outcome") == "silver") & (pl.col("eligible_permanent") > 0.0))[
            "households"
        ].sum()
    )
    summary["migration_capacity_refusals"] = _as_float((migration["outcome"] == "capacity").sum())
    for label, first, last in windows:
        in_window = migration.filter((pl.col("tick") >= first) & (pl.col("tick") <= last))
        summary[f"migration_movers_households.{label}"] = float(
            in_window["movers_households"].sum()
        )
        price_window = price.filter((pl.col("tick") >= first) & (pl.col("tick") <= last))
        summary[f"price_max_tael_per_shi.{label}"] = (
            _as_float(price_window["price_tael_per_shi"].max()) if price_window.height else 0.0
        )
        relief_window = relief.filter((pl.col("tick") >= first) & (pl.col("tick") <= last))
        need = _as_float(relief_window["need_shi"].sum())
        summary[f"relief_coverage_share.{label}"] = (
            _as_float(relief_window["released_shi"].sum()) / need if need > 0.0 else 0.0
        )
    return summary


def _dispersion(price: pl.DataFrame) -> pl.DataFrame:
    """Cross-node price dispersion per tick, the same measure the hold-out check reads.

    `maintain_order` and the sort are not cosmetic: floating-point addition is not associative, so a
    summary that averages a grouped column depends on the group's row order, and polars does not
    promise one. Two runs whose logs are byte-identical (their digests agree) would otherwise report
    slightly different means, which is exactly the false difference the no-op detector must not see.
    """
    grouped = (
        price.filter(pl.col("local_need_shi") > 0.0)
        .group_by("tick", maintain_order=True)
        .agg(
            [
                pl.col("price_tael_per_shi").mean().alias("mean"),
                pl.col("price_tael_per_shi").std().alias("sd"),
                pl.col("price_tael_per_shi").max().alias("high"),
                pl.col("price_tael_per_shi").min().alias("low"),
            ]
        )
    )
    return grouped.sort("tick").with_columns(
        pl.when(pl.col("mean") > 0.0)
        .then(pl.col("sd").fill_null(0.0) / pl.col("mean"))
        .otherwise(0.0)
        .alias("cv")
    )


def chain_deltas(left: dict[str, float], right: dict[str, float]) -> dict[str, float]:
    """The per-fact difference between two runs' chain summaries.

    A structural arm has to move *something*; this is what makes that checkable rather than assumed,
    and it is why the detector reports which facts moved rather than only that one did.
    """
    shared = sorted(set(left) & set(right))
    return {key: right[key] - left[key] for key in shared if right[key] != left[key]}


__all__ = [
    "MIGRATION_FIELDS",
    "MIGRATION_GATES",
    "PRICE_BINDINGS",
    "PRICE_FIELDS",
    "RELIEF_BINDINGS",
    "RELIEF_FIELDS",
    "ChainError",
    "chain_deltas",
    "chain_summary",
    "migration_chain",
    "price_chain",
    "relief_chain",
]
