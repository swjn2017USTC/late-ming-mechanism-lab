"""The band chain: six components that partition the change in the largest band's share.

Two of these read a real compact run, because the partition has to hold on what a run actually did.
The rest read hand-built logs, because whether a component fires at all is a property of the
fixture: the compact run happens not to split a band, and leaving the split's and the merger's
arithmetic untested because of that is how a decorative link stays decorative. A test that a
component with no events reads as zero has the same problem the other way round, so it is given a
log in which one has none.
"""

from __future__ import annotations

import json

import polars as pl
import pytest

from late_ming_lab.analysis.band_chain import (
    COMPONENTS,
    BandChainError,
    band_chain,
    band_chain_summary,
    largest_share_series,
)
from late_ming_lab.core.config import SimulationConfig
from late_ming_lab.experiments.integrated import IntegratedScenario, run_integrated_scenario

COMPACT_CONFIG = SimulationConfig.model_validate({"tick_count": 60, "warmup_ticks": 12})

SCENARIO = IntegratedScenario(
    label="band-chain-unit", dataset="toy", monthly_event_probability=0.4, severity_floor=0.6
)

_LOG_SCHEMA = {
    "tick": pl.Int64(),
    "event_type": pl.String(),
    "agent_id": pl.String(),
    "outcome": pl.String(),
    "trigger_json": pl.String(),
}


@pytest.fixture(scope="module")
def events() -> pl.DataFrame:
    return run_integrated_scenario(SCENARIO, config=COMPACT_CONFIG).result.events


def _row(
    tick: int, event_type: str, agent_id: str, outcome: str, **trigger: float
) -> dict[str, object]:
    return {
        "tick": tick,
        "event_type": event_type,
        "agent_id": agent_id,
        "outcome": outcome,
        "trigger_json": json.dumps(trigger),
    }


def _formed(tick: int, band_id: str, troops: float) -> list[dict[str, object]]:
    """A band appears, opened by the levy that fills it: the two records a formation writes."""
    return [
        _row(
            tick,
            "BAND_FORMED",
            band_id,
            "formed-at:toy-sx-a",
            troops=troops,
            levied_troops=troops,
        ),
        _row(
            tick,
            "RECRUIT_LEVY",
            band_id,
            "formed-from:levy",
            troops_joined=troops,
            troops_delta_people=troops,
            troops=troops,
        ),
    ]


def _state(tick: int, band_id: str, troops: float) -> dict[str, object]:
    return _row(tick, "BAND_STATE", band_id, "band-state", troops=troops)


def _log(rows: list[dict[str, object]]) -> pl.DataFrame:
    return pl.DataFrame(rows, schema=_LOG_SCHEMA)


def _last_share(frame: pl.DataFrame) -> float:
    """The level the log records at its last tick, which the chain's total is measured against."""
    return float(frame.select(pl.col("largest_band_share").last()).item() or 0.0)


def _formation_and_intake_log() -> pl.DataFrame:
    """Two levies form two bands, and the second month feeds one of them: no merge, no split."""
    return _log(
        [
            *_formed(1, "band-0001", 100.0),
            _state(1, "band-0001", 100.0),
            *_formed(2, "band-0002", 100.0),
            _row(
                2,
                "RECRUIT_LEVY",
                "band-0001",
                "joined-from:levy",
                troops_joined=50.0,
                troops_delta_people=50.0,
                troops=150.0,
            ),
            _state(2, "band-0001", 150.0),
            _state(2, "band-0002", 100.0),
        ]
    )


def _merge_and_split_log() -> pl.DataFrame:
    """Two bands of a hundred, one absorbing the other, then the survivor splitting in half."""
    return _log(
        [
            *_formed(1, "band-0001", 100.0),
            *_formed(1, "band-0002", 100.0),
            _state(1, "band-0001", 100.0),
            _state(1, "band-0002", 100.0),
            _row(
                2,
                "DESERTERS_LEFT",
                "band-0002",
                "merge-to:merged-into:band-0001",
                troops_left=100.0,
                troops_delta_people=-100.0,
                troops=0.0,
            ),
            _row(
                2,
                "RECRUIT_LEVY",
                "band-0001",
                "joined-from:merge:band-0002",
                troops_joined=100.0,
                troops_delta_people=100.0,
                troops=200.0,
            ),
            _state(2, "band-0001", 200.0),
            _row(
                3,
                "DESERTERS_LEFT",
                "band-0001",
                "split-to:splinter",
                troops_left=100.0,
                troops_delta_people=-100.0,
                troops=100.0,
            ),
            _row(
                3,
                "RECRUIT_LEVY",
                "band-0003",
                "formed-from:split:band-0001",
                troops_joined=100.0,
                troops_delta_people=100.0,
                troops=100.0,
            ),
            _state(3, "band-0001", 100.0),
            _state(3, "band-0003", 100.0),
        ]
    )


def test_the_components_partition_the_change_in_the_largest_share(
    events: pl.DataFrame,
) -> None:
    chain = band_chain(events)
    series = largest_share_series(events)
    per_tick = (
        chain.group_by("tick")
        .agg(pl.col("largest_band_share_delta").sum())
        .sort("tick")
        .join(series.select("tick", "largest_band_share"), on="tick", how="left")
    )
    assert per_tick["tick"].to_list() == series["tick"].to_list()
    # A run opens with no band — the layer is built empty and every band in it is formed by rule —
    # so the components' effects, accumulated from that state, are the share the log records.
    assert per_tick["largest_band_share_delta"].cum_sum().to_list() == pytest.approx(
        series["largest_band_share"].to_list()
    )
    summary = band_chain_summary(events)
    assert summary["band_chain_largest_share_change"] == pytest.approx(_last_share(series))


def test_every_component_total_is_non_negative(events: pl.DataFrame) -> None:
    """Men move; a component reports how many, so a negative total would be a sign error."""
    chain = band_chain(events)
    summary = band_chain_summary(events)
    assert set(chain["component"].unique()) == set(COMPONENTS)
    for component in COMPONENTS:
        rows = chain.filter(pl.col("component") == component)
        assert float(rows.select(pl.col("troops").min()).item() or 0.0) >= 0.0
        assert summary[f"band_chain_troops.{component}"] >= 0.0


def test_a_component_with_no_events_reads_as_zero() -> None:
    log = _formation_and_intake_log()
    summary = band_chain_summary(log)
    for component in ("deserter_intake", "dissolution", "split", "merger"):
        assert summary[f"band_chain_troops.{component}"] == 0.0
        assert summary[f"band_chain_bands.{component}"] == 0.0
        assert summary[f"band_chain_largest_share_delta.{component}"] == 0.0
    assert summary["band_chain_troops.formation"] == pytest.approx(200.0)
    assert summary["band_chain_bands.formation"] == pytest.approx(2.0)


def test_the_formation_and_intake_tracks_are_attributed_apart() -> None:
    """A levy into a standing band is not a formation, and it does not add a band."""
    summary = band_chain_summary(_formation_and_intake_log())
    # Month 1 forms one band of a hundred, which holds the whole armed population. Month 2 forms a
    # second of the same size — halving the largest one's share — and then feeds the first, which
    # lifts it to 0.6 of the two hundred and fifty men now under arms.
    assert summary["band_chain_troops.refugee_intake"] == pytest.approx(50.0)
    assert summary["band_chain_bands.refugee_intake"] == 0.0
    assert summary["band_chain_largest_share_delta.formation"] == pytest.approx(0.5)
    assert summary["band_chain_largest_share_delta.refugee_intake"] == pytest.approx(0.1)
    assert summary["band_chain_largest_share_end"] == pytest.approx(0.6)
    assert summary["band_chain_largest_share_change"] == pytest.approx(0.6)


def test_a_merge_and_a_split_are_attributed_to_their_own_components() -> None:
    """The one link the model's documentation names, given a log in which it actually fires."""
    log = _merge_and_split_log()
    summary = band_chain_summary(log)
    assert summary["band_chain_troops.merger"] == pytest.approx(100.0)
    assert summary["band_chain_bands.merger"] == pytest.approx(-1.0)
    assert summary["band_chain_largest_share_delta.merger"] == pytest.approx(0.5)
    assert summary["band_chain_troops.split"] == pytest.approx(100.0)
    assert summary["band_chain_bands.split"] == pytest.approx(1.0)
    assert summary["band_chain_largest_share_delta.split"] == pytest.approx(-0.5)
    assert summary["band_chain_largest_share_change"] == pytest.approx(
        _last_share(largest_share_series(log))
    )


def test_the_summary_is_reproducible_for_the_same_log(events: pl.DataFrame) -> None:
    assert band_chain_summary(events) == band_chain_summary(events)


def test_a_log_with_no_band_events_at_all_is_refused(events: pl.DataFrame) -> None:
    """Zero would be a measurement; a log with no band in it has no chain to measure."""
    without_bands = events.filter(
        (pl.col("event_type") != "BAND_STATE") & ~pl.col("agent_id").str.starts_with("band-")
    )
    assert without_bands.height > 0
    with pytest.raises(BandChainError, match="no band"):
        band_chain(without_bands)
    with pytest.raises(BandChainError, match="no band"):
        largest_share_series(without_bands)


def test_a_log_that_lost_a_movement_is_refused(events: pl.DataFrame) -> None:
    """A dropped movement would be charged to the component applied last, so it is refused."""
    without_intake = events.filter(
        ~((pl.col("event_type") == "RECRUIT_LEVY") & (pl.col("outcome") == "joined-from:levy"))
    )
    assert without_intake.height < events.height
    with pytest.raises(BandChainError, match="the movements give"):
        band_chain(without_intake)
