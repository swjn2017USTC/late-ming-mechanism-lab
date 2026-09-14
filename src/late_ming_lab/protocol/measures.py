"""The measured quantities the protocol reads an outcome from.

`analysis.outcomes.outcome_scalars` already computes most of what the protocol names. Two of the
protocol's measures are not in it — the subsistence need a run met and the part it left unmet — so
they are computed here, from the same `CONSUMPTION` events and with the same accounting the
governance indicator uses, which is the point: a second unpublished definition of "unmet need" would
be a second protocol.

Nothing here decides anything. This module produces numbers; `protocol.outcomes` applies the
protocol's aggregation, direction and missingness rules to them, and `protocol.robustness` reports
how a verdict moves when a reading line moves.
"""

from __future__ import annotations

from typing import Final

import networkx as nx
import polars as pl

from late_ming_lab.analysis.fiscal import fiscal_totals
from late_ming_lab.analysis.outcomes import outcome_scalars
from late_ming_lab.analysis.scalars import total
from late_ming_lab.evidence.parameters import GovernanceIndicatorParameters

#: The measures this module adds to `outcome_scalars`, so a report can tell which keys come from
#: where and a test can hold the protocol to keys that actually exist.
PROTOCOL_EXTRA_MEASURES: Final[tuple[str, ...]] = (
    "subsistence_need_shi",
    "subsistence_unmet_shi",
    "relief_released_shi",
    "relief_coverage_share",
    "livelihood_shortfall_share",
)


class MeasurementError(ValueError):
    """Raised when a run's log cannot be measured at all."""


def subsistence_totals(events: pl.DataFrame) -> dict[str, float]:
    """The subsistence floor the run measured, and the part of it the run left unmet.

    Both are summed over every `CONSUMPTION` event in the log, in shi. A run that recorded no
    consumption has no measured need, which is not the same as a need of zero: the caller decides
    what a missing denominator means, and `protocol.outcomes` refuses it by default.
    """
    consumption = events.filter(pl.col("event_type") == "CONSUMPTION")
    if consumption.is_empty():
        return {"subsistence_need_shi": 0.0, "subsistence_unmet_shi": 0.0}
    scaled = consumption.with_columns(
        [
            consumption["trigger_json"]
            .str.json_path_match("$.need_shi")
            .cast(pl.Float64, strict=False)
            .alias("need_shi"),
            consumption["trigger_json"]
            .str.json_path_match("$.unmet_shi")
            .cast(pl.Float64, strict=False)
            .alias("unmet_shi"),
        ]
    )
    return {
        "subsistence_need_shi": total(scaled, "need_shi"),
        "subsistence_unmet_shi": total(scaled, "unmet_shi"),
    }


def protocol_measurements(
    events: pl.DataFrame,
    *,
    thresholds: GovernanceIndicatorParameters,
    population_adults: float,
    starting_households: float,
    trade_graph: nx.Graph[str],
) -> dict[str, float]:
    """Every quantity the frozen protocol names, measured from one run.

    The governance reading lines enter here and nowhere else: `outcome_scalars` needs them to score
    the eight indicators, and the rest of the protocol's measures are independent of them. That
    asymmetry is what `robustness.py` reports.
    """
    if "event_type" not in events.columns or "tick" not in events.columns:
        raise MeasurementError(
            "an event log needs at least an event_type and a tick column to be measured"
        )
    scalars = outcome_scalars(
        events,
        thresholds=thresholds,
        population_adults=population_adults,
        starting_households=starting_households,
        trade_graph=trade_graph,
    )
    subsistence = subsistence_totals(events)
    need = subsistence["subsistence_need_shi"]
    unmet = subsistence["subsistence_unmet_shi"]
    released = relief_released_shi(events)
    scalars.update(subsistence)
    # The released quantity itself, not only the coverage share: a report may want the shi, and a
    # measure the protocol names has to be in the set under the name the protocol uses.
    scalars["relief_released_shi"] = released
    scalars["relief_coverage_share"] = released / need if need > 0.0 else 0.0
    scalars["livelihood_shortfall_share"] = unmet / need if need > 0.0 else 0.0
    return scalars


def relief_released_shi(events: pl.DataFrame) -> float:
    """Grain the run released as relief, in shi, read off the county fiscal ledger.

    Summed over counties and months by the same function that produces the fiscal totals, so the
    protocol's relief measure and the county ledger cannot drift apart.
    """
    return float(fiscal_totals(events)["relief_released_shi"])
