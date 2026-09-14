"""The threshold ensemble's observable contract: every line carries a band, and the band is honest.

The phase's rule is that a mechanism verdict may not rest on an arbitrary reading line, so these
tests attack the ways that rule could quietly stop holding: a band that does not contain the live
line, a line left out of the ensemble or one the parameter set does not have, a rule too thin to be
a band, a draw that is not reproducible from its seed, a "sample" that invents members the design
does not hold, and a parameter set built from a draw that drops the provenance of the line it
replaced. The file's honesty is checked against the things that would have to agree with it - the
live parameter set and the V1 cards in the registry - and never by reading its own prose back.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from late_ming_lab.evidence.cards import load_cards
from late_ming_lab.evidence.grades import DataProvenance
from late_ming_lab.evidence.parameters import (
    GovernanceIndicatorParameters,
    core_default_governance_indicators,
)
from late_ming_lab.protocol.thresholds import (
    LINE_FIELDS,
    GridRule,
    ThresholdEnsemble,
    ThresholdEnsembleError,
    load_ensemble,
    sample_draws,
    to_parameters,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
PARAMETER_SET = "GovernanceIndicatorParameters"
ENSEMBLE_FILE = "threshold-ensemble-v2.yaml"
SEED = 20_260_915


@pytest.fixture(scope="module")
def ensemble() -> ThresholdEnsemble:
    return load_ensemble(REPO_ROOT)


def _payload(ensemble: ThresholdEnsemble) -> dict[str, Any]:
    """The frozen file as data, so a broken variant differs only where a test says it does."""
    payload: dict[str, Any] = ensemble.model_dump(mode="json")
    return payload


def _entry(payload: dict[str, Any], entry_id: str) -> dict[str, Any]:
    entries: list[dict[str, Any]] = payload["entries"]
    for entry in entries:
        if entry["id"] == entry_id:
            return entry
    raise AssertionError(f"{entry_id} is not in the payload")


def _load(tmp_path: Path, payload: dict[str, Any]) -> ThresholdEnsemble:
    """Load a payload from where the loader looks, so what refuses it is the loader."""
    source = tmp_path / "data" / "protocol" / ENSEMBLE_FILE
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return load_ensemble(tmp_path)


def test_the_ensemble_carries_every_reading_line_and_nothing_else(
    ensemble: ThresholdEnsemble,
) -> None:
    assert ensemble.ids == LINE_FIELDS
    assert len({entry.indicator for entry in ensemble.entries}) == len(ensemble.entries)


def test_every_line_sits_inside_the_band_it_is_read_over(ensemble: ThresholdEnsemble) -> None:
    for entry in ensemble.entries:
        low, high = entry.range
        assert low < high
        assert low <= entry.value <= high


def test_every_declared_value_is_the_line_the_model_runs(ensemble: ThresholdEnsemble) -> None:
    live = core_default_governance_indicators()

    for entry in ensemble.entries:
        assert entry.value == getattr(live, entry.id)


def test_every_identity_and_value_is_what_the_card_says(ensemble: ThresholdEnsemble) -> None:
    """A line the cards describe as an assumption must not be filed here as anything stronger."""
    cards = load_cards(REPO_ROOT)

    for entry in ensemble.entries:
        card = cards.require(PARAMETER_SET, entry.id)
        assert entry.value == card.central
        expected = "evidence-bounded" if card.ledger_entries else "model-assumption"
        assert entry.identity == expected


def test_a_grid_reads_its_band_at_exactly_its_declared_points(ensemble: ThresholdEnsemble) -> None:
    members = sample_draws(ensemble, seed=SEED)

    for entry in ensemble.entries:
        low, high = entry.range
        values = {member[entry.id] for member in members}
        assert all(low <= value <= high for value in values)
        if isinstance(entry.sampling, GridRule):
            assert len(values) == entry.sampling.points
            # the band is symmetric about the live line, so the declared verdict is one member
            assert entry.value in values
        else:
            assert len(values) > 1


def test_the_design_enumerates_each_member_exactly_once(ensemble: ThresholdEnsemble) -> None:
    members = sample_draws(ensemble, seed=SEED)
    ids = ensemble.ids

    assert len(members) == ensemble.total_draws
    assert len({tuple(member[name] for name in ids) for member in members}) == len(members)
    # the last line's rule varies fastest, so consecutive members differ there and nowhere else
    first, second = members[0], members[1]
    assert {name for name in ids if first[name] != second[name]} == {ids[-1]}


def test_loading_refuses_a_band_that_does_not_bracket_its_line(
    ensemble: ThresholdEnsemble, tmp_path: Path
) -> None:
    inverted = _payload(ensemble)
    _entry(inverted, "unmet_share_of_need")["range"] = [0.45, 0.05]
    with pytest.raises(ValidationError, match="inverted"):
        _load(tmp_path, inverted)

    outside = _payload(ensemble)
    _entry(outside, "unmet_share_of_need")["value"] = 0.5
    with pytest.raises(ValidationError, match="outside its range"):
        _load(tmp_path, outside)

    single_point = _payload(ensemble)
    _entry(single_point, "largest_band_share")["range"] = [0.5, 0.5]
    with pytest.raises(ValidationError, match="single point"):
        _load(tmp_path, single_point)


def test_loading_refuses_a_line_left_out_or_a_line_that_is_not_one(
    ensemble: ThresholdEnsemble, tmp_path: Path
) -> None:
    missing = _payload(ensemble)
    missing["entries"] = [
        entry for entry in missing["entries"] if entry["id"] != "largest_band_share"
    ]
    with pytest.raises(ValidationError, match="largest_band_share"):
        _load(tmp_path, missing)

    unread = _payload(ensemble)
    _entry(unread, "largest_band_share")["id"] = "largest_band_share_of_adults"
    with pytest.raises(ValidationError, match="not a reading line"):
        _load(tmp_path, unread)

    repeated = _payload(ensemble)
    repeated["entries"] = [*repeated["entries"], dict(_entry(repeated, "pay_shortfall_share"))]
    with pytest.raises(ValidationError, match="unique"):
        _load(tmp_path, repeated)


def test_loading_refuses_a_rule_too_thin_to_be_a_band(
    ensemble: ThresholdEnsemble, tmp_path: Path
) -> None:
    one_point = _payload(ensemble)
    _entry(one_point, "pay_shortfall_share")["sampling"] = {"kind": "grid", "points": 1}
    with pytest.raises(ValidationError, match="points"):
        _load(tmp_path, one_point)

    uncounted = _payload(ensemble)
    _entry(uncounted, "out_migration_share_of_households")["sampling"] = {"kind": "uniform"}
    with pytest.raises(ValidationError, match="draws"):
        _load(tmp_path, uncounted)


def test_loading_refuses_a_file_of_another_schema(
    ensemble: ThresholdEnsemble, tmp_path: Path
) -> None:
    other_schema = _payload(ensemble) | {"schema_version": "threshold-ensemble-v1"}
    with pytest.raises(ThresholdEnsembleError, match="threshold-ensemble-v1"):
        _load(tmp_path, other_schema)

    with pytest.raises(ThresholdEnsembleError, match="is missing"):
        load_ensemble(tmp_path / "nowhere")


def test_a_draw_is_deterministic_in_its_seed(ensemble: ThresholdEnsemble) -> None:
    assert sample_draws(ensemble, draws=32, seed=SEED) == sample_draws(
        ensemble, draws=32, seed=SEED
    )
    assert sample_draws(ensemble, draws=32, seed=SEED) != sample_draws(
        ensemble, draws=32, seed=SEED + 1
    )
    # the whole design is seeded too, through each uniform rule's independent draws
    assert sample_draws(ensemble, seed=SEED) != sample_draws(ensemble, seed=SEED + 1)


def test_a_sample_is_drawn_from_the_design_and_never_padded(ensemble: ThresholdEnsemble) -> None:
    ids = ensemble.ids
    design = {tuple(member[name] for name in ids) for member in sample_draws(ensemble, seed=SEED)}

    sample = sample_draws(ensemble, draws=16, seed=SEED)
    assert len(sample) == 16
    assert all(tuple(member[name] for name in ids) in design for member in sample)

    with pytest.raises(ThresholdEnsembleError, match="design holds"):
        sample_draws(ensemble, draws=ensemble.total_draws + 1, seed=SEED)
    with pytest.raises(ThresholdEnsembleError, match="design holds"):
        sample_draws(ensemble, draws=0, seed=SEED)


def test_a_drawn_parameter_set_is_the_draw_with_the_base_provenance(
    ensemble: ThresholdEnsemble,
) -> None:
    live = core_default_governance_indicators()
    draw = sample_draws(ensemble, draws=8, seed=SEED)[3]

    parameters = to_parameters(draw)
    assert isinstance(parameters, GovernanceIndicatorParameters)
    for name, value in draw.items():
        assert getattr(parameters, name) == value
    assert parameters.provenance == live.provenance
    assert parameters.version == live.version

    base = GovernanceIndicatorParameters.model_validate(
        {**live.model_dump(), "provenance": DataProvenance.assumption("a reviewer's own lines")}
    )
    assert to_parameters(draw, base=base).provenance == base.provenance

    with pytest.raises(ValidationError, match="receipts_below_quota_share"):
        to_parameters({**draw, "receipts_below_quota_share": 1.5})
    with pytest.raises(ValidationError, match="mystery_line"):
        to_parameters({**draw, "mystery_line": 0.5})
