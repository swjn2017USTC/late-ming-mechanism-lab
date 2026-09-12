"""Parameter sets: every P03 number is a declared assumption with sane structure."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from late_ming_lab.evidence.parameters import (
    CropParameters,
    HouseholdParameters,
    core_default_crop_parameters,
    core_default_household_parameters,
)
from late_ming_lab.networks.nodes import AgrarianZone


def test_crop_parameters_cover_every_zone_with_positive_yields() -> None:
    parameters = core_default_crop_parameters()

    assert set(parameters.yield_shi_per_mu) == set(AgrarianZone)
    assert parameters.provenance.is_assumption
    assert parameters.land_per_adult_capacity_mu > 0
    assert parameters.yield_loss_scale >= 0

    with pytest.raises(ValidationError, match="missing baseline yield"):
        CropParameters.model_validate(
            {
                **parameters.model_dump(),
                "yield_shi_per_mu": {"loess-dryland": 0.9},
            }
        )
    with pytest.raises(ValidationError, match="must be positive"):
        CropParameters.model_validate(
            {
                **parameters.model_dump(),
                "yield_shi_per_mu": {"loess-dryland": 0.0, "north-china-plain": 1.1},
            }
        )


def test_household_parameters_are_assumptions_with_ordered_thresholds() -> None:
    parameters = core_default_household_parameters()

    assert parameters.provenance.is_assumption
    assert parameters.temporary_migration_unmet_ratio <= parameters.permanent_migration_unmet_ratio
    assert parameters.rent_share_for("tenant-household") > 0.0
    assert parameters.rent_share_for("wealthy-farmer") == 0.0


def test_contradictory_parameter_values_are_rejected() -> None:
    base = core_default_household_parameters().model_dump()

    with pytest.raises(ValidationError, match="stricter than permanent migration"):
        HouseholdParameters.model_validate({**base, "temporary_migration_unmet_ratio": 0.5})
    with pytest.raises(ValidationError, match="rent shares"):
        HouseholdParameters.model_validate(
            {**base, "rent_share_of_harvest": {"tenant-household": 1.5}}
        )


def test_annual_need_scales_with_adults() -> None:
    parameters = core_default_household_parameters()

    assert parameters.annual_need_shi(2.0) == pytest.approx(
        2.0 * parameters.subsistence_grain_per_adult_month_shi * 12.0
    )
    assert parameters.annual_need_shi(0.0) == 0.0
