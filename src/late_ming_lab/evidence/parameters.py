"""Parameter sets built from explicit model assumptions.

Every set here is a development-scale placeholder: the values are graded ``S`` (assumption)
and are sensitivity targets. The evidence ledger that will replace them with sourced
parameter cards belongs to P08; nothing in this module claims a historical measurement.

Units are stated once, here, and used consistently everywhere:

- grain in ``shi`` (石), silver in ``tael`` (两), land in ``mu`` (畝), time in months;
- ``households`` counts households represented by one cohort (the cohort weight).
"""

from __future__ import annotations

from typing import Final

from pydantic import BaseModel, ConfigDict, Field, model_validator

from late_ming_lab.evidence.grades import DataProvenance
from late_ming_lab.networks.nodes import AgrarianZone

CROP_PARAMETERS_VERSION: Final[str] = "crop-parameters-v1"
HOUSEHOLD_PARAMETERS_VERSION: Final[str] = "household-parameters-v1"


class CropParameters(BaseModel):
    """Production function parameters, per agrarian zone."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    version: str = CROP_PARAMETERS_VERSION
    yield_shi_per_mu: dict[AgrarianZone, float]
    land_per_adult_capacity_mu: float = Field(gt=0)
    yield_loss_scale: float = Field(ge=0.0)
    provenance: DataProvenance

    @model_validator(mode="after")
    def _exact_zone_coverage(self) -> CropParameters:
        missing = [zone.value for zone in AgrarianZone if zone not in self.yield_shi_per_mu]
        if missing:
            raise ValueError(f"missing baseline yield for zones: {', '.join(missing)}")
        if any(value <= 0 for value in self.yield_shi_per_mu.values()):
            raise ValueError("baseline yields must be positive")
        return self


class HouseholdParameters(BaseModel):
    """Subsistence, coping-ladder and placeholder-credit parameters.

    The credit and price entries are *not* a market: they are fixed assumed terms used to
    resolve a subsistence shortfall, so that the coping ladder can be exercised at all. P04
    replaces them with an endogenous market and an explicit lender.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    version: str = HOUSEHOLD_PARAMETERS_VERSION

    subsistence_grain_per_adult_month_shi: float = Field(gt=0)
    minimum_consumption_fraction: float = Field(gt=0, le=1)

    wage_grain_shi_per_adult_month: float = Field(
        ge=0,
        description=(
            "in-kind agricultural wage, scaled by local labour demand (the last local yield "
            "fraction); a declared placeholder for the labour market of P05"
        ),
    )

    grain_reference_price_tael_per_shi: float = Field(
        gt=0,
        description=(
            "reference (non-crisis) price used to value grain in kind, for example when a "
            "household repays a loan out of its harvest"
        ),
    )
    distress_grain_price_tael_per_shi: float = Field(
        gt=0, description="price a household faces when it must buy grain short of food"
    )
    land_reference_value_tael_per_mu: float = Field(gt=0)
    land_distress_price_tael_per_mu: float = Field(gt=0)

    loan_to_value: float = Field(ge=0)
    interest_rate_monthly: float = Field(ge=0)
    debt_repayment_silver_reserve_tael_per_household: float = Field(ge=0)
    debt_repayment_grain_ratio_of_annual_need: float = Field(ge=0)

    harvest_recovery_grain_ratio: float = Field(ge=0)

    temporary_migration_unmet_ratio: float = Field(ge=0, le=1)
    permanent_migration_unmet_ratio: float = Field(ge=0, le=1)
    recruitment_unmet_ratio: float = Field(ge=0, le=1)
    recruitment_max_land_per_household_mu: float = Field(ge=0)

    rent_share_of_harvest: dict[str, float]

    provenance: DataProvenance

    @model_validator(mode="after")
    def _ordered_thresholds_and_rent(self) -> HouseholdParameters:
        if self.land_distress_price_tael_per_mu > self.land_reference_value_tael_per_mu:
            raise ValueError(
                "a distress sale cannot fetch more than the collateral reference value"
            )
        if self.distress_grain_price_tael_per_shi < self.grain_reference_price_tael_per_shi:
            raise ValueError(
                "buying grain short of food cannot be cheaper than the reference price"
            )
        if not (self.temporary_migration_unmet_ratio <= self.permanent_migration_unmet_ratio):
            raise ValueError(
                "temporary-migration eligibility cannot be stricter than permanent migration"
            )
        if any(not 0.0 <= share <= 1.0 for share in self.rent_share_of_harvest.values()):
            raise ValueError("rent shares must lie in [0, 1]")
        return self

    def rent_share_for(self, cohort_class: str) -> float:
        return self.rent_share_of_harvest.get(cohort_class, 0.0)

    def annual_need_shi(self, adults: float) -> float:
        return adults * self.subsistence_grain_per_adult_month_shi * 12.0


def core_default_crop_parameters() -> CropParameters:
    """Development-scale production assumptions for the two core zones."""
    return CropParameters(
        yield_shi_per_mu={
            AgrarianZone.LOESS_DRYLAND: 0.9,
            AgrarianZone.NORTH_CHINA_PLAIN: 1.1,
        },
        land_per_adult_capacity_mu=12.0,
        yield_loss_scale=0.5,
        provenance=DataProvenance.assumption(
            "development-scale yields and labour capacity for the loess dryland and north "
            "China plain zones; grade S, to be replaced by sourced parameter cards in P08"
        ),
    )


def core_default_household_parameters() -> HouseholdParameters:
    """Development-scale subsistence, ladder and credit assumptions."""
    return HouseholdParameters(
        subsistence_grain_per_adult_month_shi=0.25,
        minimum_consumption_fraction=0.75,
        wage_grain_shi_per_adult_month=0.3,
        grain_reference_price_tael_per_shi=0.6,
        distress_grain_price_tael_per_shi=1.5,
        land_reference_value_tael_per_mu=5.0,
        land_distress_price_tael_per_mu=2.5,
        loan_to_value=0.5,
        interest_rate_monthly=0.005,
        debt_repayment_silver_reserve_tael_per_household=0.5,
        debt_repayment_grain_ratio_of_annual_need=1.0,
        harvest_recovery_grain_ratio=0.5,
        temporary_migration_unmet_ratio=0.05,
        permanent_migration_unmet_ratio=0.2,
        recruitment_unmet_ratio=0.2,
        recruitment_max_land_per_household_mu=2.0,
        rent_share_of_harvest={"tenant-household": 0.4},
        provenance=DataProvenance.assumption(
            "development-scale subsistence need, consumption floor, in-kind wage, distress "
            "prices, credit terms, rent share and eligibility thresholds; grade S, to be "
            "replaced by sourced parameter cards in P08"
        ),
    )
