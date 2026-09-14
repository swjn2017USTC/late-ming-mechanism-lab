"""The intermediate series the protocol requires, read from a run's log.

An outcome vector is an end state. The phase's fourth output is the other half: the quantities
inside each mechanism chain, at the county and the month, so a later report can see *how* a chain
moved rather than only where it stopped. The protocol declares which series those are
(`intermediates:` in `data/protocol/validation-protocol-v2.yaml`) and this module produces them, by
calling the analysis functions the project already has — a new measurement here would be a second
definition of something already measured.

Nothing here decides anything: these are frames. The reading rules that turn them into verdicts
live in `governance.py` and `mechanisms.py`, and the ensemble that moves their lines lives in
`protocol/robustness.py`.
"""

from __future__ import annotations

from typing import Final

import networkx as nx
import polars as pl

from late_ming_lab.analysis.concentration import trade_summary
from late_ming_lab.analysis.fiscal import county_fiscal_series
from late_ming_lab.analysis.governance import governance_series
from late_ming_lab.analysis.migration import migration_flows, node_migration
from late_ming_lab.analysis.military import band_series, garrison_series
from late_ming_lab.protocol.schema import ValidationProtocol

#: The indicator-tick sampling the governance series is read at, matching the P10 artifacts.
GOVERNANCE_SAMPLE_EVERY: Final[int] = 12


class IntermediateError(ValueError):
    """Raised when a declared series cannot be produced, or comes back empty."""


def retained_series(
    events: pl.DataFrame, *, trade_graph: nx.Graph[str] | None = None
) -> dict[str, pl.DataFrame]:
    """Every intermediate series the protocol declares, by id.

    `trade_graph` is accepted for signature parity with the outcome frames and is unused: each
    series here is read from the event log, which is what makes them re-derivable from a run.
    """
    return {
        "county_fiscal_month": county_fiscal_series(events),
        "military_standing_month": garrison_series(events),
        "armed_bands_month": band_series(events),
        "migration_month": migration_flows(events),
        "migration_by_node": node_migration(events),
        "trade_link": trade_summary(events),
        "governance_sample": governance_series(events, every=GOVERNANCE_SAMPLE_EVERY),
    }


def assert_retained(protocol: ValidationProtocol, events: pl.DataFrame) -> dict[str, pl.DataFrame]:
    """Produce the declared series and refuse a protocol that asks for one nothing produces.

    A declared series with no implementation, or with a declared field its frame does not carry, is
    an error rather than an omission: the phase requires the chain to be retained, and a silently
    missing series would leave a report reading a chain that is not there.

    A series with no rows is returned as empty rather than refused: "nothing migrated in this run"
    is a fact about the run, not a missing measurement. What is refused is every declared series
    being empty at once, which would mean the run retained no chain at all.
    """
    produced = retained_series(events)
    declared = {series.id for series in protocol.intermediates}
    missing = declared - set(produced)
    if missing:
        raise IntermediateError(
            f"the protocol declares {', '.join(sorted(missing))}, which nothing produces"
        )
    for series in protocol.intermediates:
        frame = produced[series.id]
        absent = [name for name in series.fields if name not in frame.columns]
        if absent:
            raise IntermediateError(
                f"{series.id}: the declared field(s) {', '.join(absent)} are not in the frame the "
                f"{series.source} returns"
            )
    if all(produced[name].is_empty() for name in declared):
        raise IntermediateError(
            "every declared intermediate series came back empty: this run retained no chain"
        )
    return {name: produced[name] for name in sorted(declared)}
