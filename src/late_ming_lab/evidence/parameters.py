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
MARKET_PARAMETERS_VERSION: Final[str] = "market-parameters-v1"
FISCAL_PARAMETERS_VERSION: Final[str] = "fiscal-parameters-v1"
MILITARY_PARAMETERS_VERSION: Final[str] = "military-parameters-v1"
BAND_PARAMETERS_VERSION: Final[str] = "band-parameters-v1"
ELITE_PARAMETERS_VERSION: Final[str] = "elite-parameters-v1"


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
    """Subsistence and coping-ladder parameters.

    Prices, credit terms and the lender live in :class:`MarketParameters` and
    :class:`EliteParameters`: the household decides *what* to do down the ladder, and the market
    and the elite decide what it can actually buy, borrow and sell.
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

    land_reference_value_tael_per_mu: float = Field(
        gt=0, description="collateral value of land as the borrower values it"
    )
    tax_grain_sale_floor_ratio_of_annual_need: float = Field(
        ge=0,
        description=(
            "grain a household will not sell to pay tax: below this share of a year's need it "
            "would rather fall into arrears"
        ),
    )
    surplus_keep_ratio_of_annual_need: float = Field(
        ge=0,
        description=(
            "grain kept before a household sells its harvest surplus on the market; 1.0 keeps "
            "a full year of need"
        ),
    )
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
        land_reference_value_tael_per_mu=5.0,
        tax_grain_sale_floor_ratio_of_annual_need=0.5,
        surplus_keep_ratio_of_annual_need=1.0,
        debt_repayment_silver_reserve_tael_per_household=0.5,
        debt_repayment_grain_ratio_of_annual_need=1.0,
        harvest_recovery_grain_ratio=0.5,
        temporary_migration_unmet_ratio=0.05,
        permanent_migration_unmet_ratio=0.2,
        recruitment_unmet_ratio=0.2,
        recruitment_max_land_per_household_mu=2.0,
        rent_share_of_harvest={"tenant-household": 0.4},
        provenance=DataProvenance.assumption(
            "development-scale subsistence need, consumption floor, in-kind wage, surplus "
            "retention, rent share and eligibility thresholds; grade S, to be replaced by "
            "sourced parameter cards in P08"
        ),
    )


class MarketParameters(BaseModel):
    """Grain-market parameters: price formation, transport and trade risk.

    Prices are endogenous here — the market's own inventory moves them — but the *form* of the
    price rule, its reference level and the transport conversion are declared assumptions
    (grade ``S``, sensitivity targets), not estimates.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    version: str = MARKET_PARAMETERS_VERSION

    reference_price_tael_per_shi: float = Field(gt=0)
    price_elasticity: float = Field(gt=0)
    target_cover_months: float = Field(gt=0)
    price_floor_ratio: float = Field(gt=0, le=1)
    price_ceiling_ratio: float = Field(ge=1)

    transport_cost_tael_per_cost_unit_per_shi: float = Field(
        gt=0,
        description=(
            "converts a G_trade cost (declared dimensionless in P02) into silver per shi moved"
        ),
    )
    capacity_unit_shi_per_month: float = Field(
        ge=0,
        description=(
            "converts a G_trade capacity (declared dimensionless in P02) into shi per month; "
            "zero means no intercounty trade at all, the autarky reference"
        ),
    )
    risk_loss_fraction_scale: float = Field(
        ge=0, description="fraction of a consignment lost = link risk x this scale"
    )
    minimum_trade_margin_tael_per_shi: float = Field(ge=0)
    max_export_share_of_stock: float = Field(gt=0, le=1)

    provenance: DataProvenance

    @model_validator(mode="after")
    def _ordered_bounds(self) -> MarketParameters:
        if self.price_floor_ratio > 1.0:
            raise ValueError("the price floor cannot sit above the reference price")
        if self.price_ceiling_ratio < 1.0:
            raise ValueError("the price ceiling cannot sit below the reference price")
        return self

    def transport_cost_tael_per_shi(self, edge_cost: float) -> float:
        return edge_cost * self.transport_cost_tael_per_cost_unit_per_shi


class EliteParameters(BaseModel):
    """Elite action parameters: lending, land purchase, relief and tax mediation.

    These are rules, not verdicts. A higher rate or a lower relief share is not "bad"; the phase
    measures what each rule produces, including the possibility that lending both delays
    collapse and concentrates land.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    version: str = ELITE_PARAMETERS_VERSION

    land_purchase_price_tael_per_mu: float = Field(gt=0)
    loan_to_value: float = Field(ge=0)
    interest_rate_monthly: float = Field(ge=0)
    max_lending_share_of_silver: float = Field(gt=0, le=1)

    relief_eligibility_unmet_ratio: float = Field(ge=0, le=1)
    relief_share_of_grain_stock: float = Field(ge=0, le=1)
    relief_carry_over_ratio_of_local_need: float = Field(ge=0)
    grain_sale_carry_over_ratio_of_local_need: float = Field(ge=0)

    tax_mediation_advance_share: float = Field(ge=0, le=1)

    provenance: DataProvenance


def core_default_market_parameters() -> MarketParameters:
    """Development-scale market assumptions for the toy dataset."""
    return MarketParameters(
        reference_price_tael_per_shi=0.6,
        price_elasticity=0.8,
        target_cover_months=6.0,
        price_floor_ratio=0.5,
        price_ceiling_ratio=6.0,
        transport_cost_tael_per_cost_unit_per_shi=0.35,
        capacity_unit_shi_per_month=1.0,
        risk_loss_fraction_scale=1.0,
        minimum_trade_margin_tael_per_shi=0.1,
        max_export_share_of_stock=0.5,
        provenance=DataProvenance.assumption(
            "development-scale price rule, transport conversion and trade margin; grade S, to "
            "be replaced by sourced parameter cards in P08"
        ),
    )


def core_default_elite_parameters() -> EliteParameters:
    """Development-scale elite assumptions for the toy dataset."""
    return EliteParameters(
        land_purchase_price_tael_per_mu=2.5,
        loan_to_value=0.5,
        interest_rate_monthly=0.005,
        max_lending_share_of_silver=0.8,
        relief_eligibility_unmet_ratio=0.05,
        relief_share_of_grain_stock=0.05,
        relief_carry_over_ratio_of_local_need=1.0,
        grain_sale_carry_over_ratio_of_local_need=1.0,
        tax_mediation_advance_share=0.5,
        provenance=DataProvenance.assumption(
            "development-scale lending, land price, relief and mediation rules; grade S, to be "
            "replaced by sourced parameter cards in P08"
        ),
    )


class FiscalParameters(BaseModel):
    """Assessment, collection, treasury and official-relief rules for county governments.

    The tax ledger is decomposed the way M3 requires — quota, effort, cost, receipts, arrears —
    and every rate here is a grade ``S`` assumption. ``assessed_value_tael_per_mu`` is the value
    the county assesses a mu of taxable land at, not a market price.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    version: str = FISCAL_PARAMETERS_VERSION

    assessed_value_tael_per_mu: float = Field(gt=0)
    collection_cost_per_effort_tael: float = Field(gt=0)
    collection_cost_logistics_floor: float = Field(gt=0, le=1)

    elite_hidden_land_share: float = Field(
        ge=0, le=1, description="share of elite land the county cannot see at full information"
    )

    relief_eligibility_unmet_ratio: float = Field(ge=0, le=1)
    relief_share_of_need: float = Field(ge=0, le=1)
    relief_logistics_cost_per_shi_tael: float = Field(ge=0)
    granary_target_cover_months: float = Field(ge=0)
    granary_purchase_share_of_silver: float = Field(ge=0, le=1)

    provenance: DataProvenance

    @model_validator(mode="after")
    def _bounded_rules(self) -> FiscalParameters:
        if self.collection_cost_logistics_floor <= 0.0:
            raise ValueError("logistics capacity cannot divide by zero")
        return self

    def hidden_land_share(self, *, information_capacity: float) -> float:
        """Land the county cannot see: elites hide more of it when information is weak."""
        if not 0.0 <= information_capacity <= 1.0:
            raise ValueError("information capacity must lie in [0, 1]")
        return self.elite_hidden_land_share * (1.0 - information_capacity)

    def collection_cost_tael(
        self, *, effort: float, quota_tael: float, logistics_capacity: float
    ) -> float:
        """What the effort costs: effort against the quota, dearer with worse logistics."""
        logistics = max(logistics_capacity, self.collection_cost_logistics_floor)
        return effort * quota_tael * self.collection_cost_per_effort_tael / logistics

    def relief_cost_tael(self, *, released_shi: float, logistics_capacity: float) -> float:
        logistics = max(logistics_capacity, self.collection_cost_logistics_floor)
        return released_shi * self.relief_logistics_cost_per_shi_tael / logistics


def core_default_fiscal_parameters() -> FiscalParameters:
    """Development-scale fiscal assumptions for the toy counties."""
    return FiscalParameters(
        assessed_value_tael_per_mu=0.35,
        collection_cost_per_effort_tael=0.02,
        collection_cost_logistics_floor=0.1,
        elite_hidden_land_share=0.6,
        relief_eligibility_unmet_ratio=0.05,
        relief_share_of_need=0.5,
        relief_logistics_cost_per_shi_tael=0.02,
        granary_target_cover_months=1.0,
        granary_purchase_share_of_silver=0.5,
        provenance=DataProvenance.assumption(
            "development-scale assessment value, collection and relief costs, elite hiding and "
            "granary rules; grade S, to be replaced by sourced parameter cards in P08"
        ),
    )


class MilitaryParameters(BaseModel):
    """Garrison finance and desertion rules.

    All of it is grade ``S``: what a soldier is paid, what he eats, and how likely he is to leave
    when he is neither paid nor fed. There is no tactical content here, on purpose.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    version: str = MILITARY_PARAMETERS_VERSION

    pay_tael_per_soldier_month: float = Field(gt=0)
    pay_share_of_treasury: float = Field(gt=0, le=1)
    food_shi_per_soldier_month: float = Field(gt=0)
    ration_purchase_share_of_silver: float = Field(
        gt=0,
        le=1,
        description="share of the treasury a county will spend buying rations for its garrison",
    )

    desertion_base_rate: float = Field(ge=0, le=1)
    desertion_pay_weight: float = Field(ge=0)
    desertion_food_weight: float = Field(ge=0)
    desertion_morale_weight: float = Field(ge=0)
    desertion_max_rate: float = Field(gt=0, le=1)

    deserter_home_share: float = Field(ge=0, le=1)
    deserter_band_share: float = Field(ge=0, le=1)

    morale_pay_weight: float = Field(ge=0)
    morale_food_weight: float = Field(ge=0)
    morale_recovery: float = Field(ge=0)
    cohesion_food_weight: float = Field(ge=0)

    suppression_effectiveness: float = Field(ge=0, le=1)
    suppression_arms_mitigation: float = Field(
        ge=0,
        le=1,
        description="share of suppression losses a fully armed band can avoid",
    )
    suppression_food_cost_per_troop_shi: float = Field(ge=0)
    suppression_cohesion_cost: float = Field(ge=0, le=1)

    garrison_target_troops: float = Field(ge=0)
    levy_rate_of_eligible_adults: float = Field(ge=0, le=1)

    provenance: DataProvenance

    @model_validator(mode="after")
    def _shares_fit(self) -> MilitaryParameters:
        if self.deserter_home_share + self.deserter_band_share > 1.0 + 1e-9:
            raise ValueError(
                "home and band shares cannot together exceed every deserter; the rest disperse"
            )
        return self


class BandParameters(BaseModel):
    """Armed-band rules: formation, recruitment, food, movement, raids, split and merge."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    version: str = BAND_PARAMETERS_VERSION

    minimum_formation_troops: float = Field(gt=0)
    formation_unmet_ratio: float = Field(ge=0, le=1)
    formation_recruitment_months: float = Field(
        gt=0,
        description="months of distressed recruitment a forming band is assumed to concentrate",
    )
    recruitment_rate_of_eligible_adults: float = Field(ge=0, le=1)

    food_shi_per_member_month: float = Field(gt=0)
    raid_extraction_multiple: float = Field(
        gt=0,
        description="grain a band takes each month, in multiples of its own monthly food need",
    )
    raid_asset_share_per_month: float = Field(ge=0, le=1)
    arms_per_asset_valuation: float = Field(ge=0)
    arms_per_member_for_full_capability: float = Field(gt=0)

    movement_mobility_floor: float = Field(gt=0, le=1)
    movement_avoidance_ratio: float = Field(
        ge=0,
        le=1,
        description="monthly losses as a share of its own size at which a band prefers to move",
    )
    mobility_gain_from_move: float = Field(ge=0, le=1)
    mobility_decay_per_month: float = Field(ge=0, le=1)
    cohesion_gain_per_month: float = Field(ge=0, le=1)
    cohesion_decay_per_month: float = Field(ge=0, le=1)
    network_gain_per_month: float = Field(ge=0, le=1)
    network_loss_from_raid_per_month: float = Field(ge=0, le=1)

    split_troops_threshold: float = Field(gt=0)
    split_cohesion_below: float = Field(ge=0, le=1)
    merge_cohesion_above: float = Field(ge=0, le=1)
    dissolve_troops_below: float = Field(gt=0)

    provenance: DataProvenance


def core_default_military_parameters() -> MilitaryParameters:
    """Development-scale garrison rules: pay, rations and the desertion that follows."""
    return MilitaryParameters(
        pay_tael_per_soldier_month=0.25,
        pay_share_of_treasury=0.5,
        food_shi_per_soldier_month=0.3,
        ration_purchase_share_of_silver=0.3,
        desertion_base_rate=0.002,
        desertion_pay_weight=0.05,
        desertion_food_weight=0.04,
        desertion_morale_weight=0.02,
        desertion_max_rate=0.08,
        deserter_home_share=0.4,
        deserter_band_share=0.3,
        morale_pay_weight=0.08,
        morale_food_weight=0.1,
        morale_recovery=0.1,
        cohesion_food_weight=0.1,
        suppression_effectiveness=0.02,
        suppression_arms_mitigation=0.5,
        suppression_food_cost_per_troop_shi=0.02,
        suppression_cohesion_cost=0.02,
        garrison_target_troops=300.0,
        levy_rate_of_eligible_adults=0.002,
        provenance=DataProvenance.assumption(
            "development-scale pay, rations, desertion and suppression rules; grade S, to be "
            "replaced by sourced parameter cards in P08"
        ),
    )


def core_default_band_parameters() -> BandParameters:
    """Development-scale band rules: how bands form, eat, move and consolidate."""
    return BandParameters(
        minimum_formation_troops=40.0,
        formation_unmet_ratio=0.15,
        formation_recruitment_months=6.0,
        recruitment_rate_of_eligible_adults=0.01,
        food_shi_per_member_month=0.3,
        raid_extraction_multiple=1.5,
        raid_asset_share_per_month=0.05,
        arms_per_asset_valuation=0.02,
        arms_per_member_for_full_capability=0.05,
        movement_mobility_floor=0.3,
        movement_avoidance_ratio=0.05,
        mobility_gain_from_move=0.05,
        mobility_decay_per_month=0.02,
        cohesion_gain_per_month=0.04,
        cohesion_decay_per_month=0.02,
        network_gain_per_month=0.03,
        network_loss_from_raid_per_month=0.1,
        split_troops_threshold=400.0,
        split_cohesion_below=0.45,
        merge_cohesion_above=0.6,
        dissolve_troops_below=40.0,
        provenance=DataProvenance.assumption(
            "development-scale band formation, food, movement, raid and consolidation rules; "
            "grade S, to be replaced by sourced parameter cards in P08"
        ),
    )
