"""The arms: one declared baseline, and the nine mechanisms the phase removes from it.

P10 asks what a mechanism is *for*. The answer is a comparison, so the comparison has to be one
declared configuration plus nine declared differences from it — not nine hand-built models. This
module holds both: :data:`BASELINE` is the single declaration of everything an arm may vary, and
each :class:`Intervention` is a function from the baseline to one arm. A report can therefore print
the *computed* difference between an arm and the baseline instead of a hand-written description that
drifts.

Two of the nine ablations are only meaningful against a baseline that has the mechanism switched on,
and the baseline says so explicitly rather than hiding it:

- *Extraction escalation* is off in the P07 sandbox (the default policy is a fixed rate), and the
  P05 experiment already declared the escalating policy with its own numbers. The P10 baseline uses
  that declared escalating policy — `ArrearsEscalation(base_effort=0.5, arrears_weight=0.5,
  effort_ceiling=1.0)` — so the ablation that removes escalation compares against escalation.
- *Trade disruption* has no endogenous driver in the model: `TradeDisruption` is a bounded interface
  that nothing yet feeds from armed-group activity. The baseline therefore installs a declared
  regime (`ScaledDisruption(risk_scale=1.5, capacity_scale=0.5)`: half the capacity, half again the
  risk, the smallest round manipulation that is plainly not the identity), and the ablation removes
  it. Both facts — that escalation and disruption are on by declaration, and that neither is
  endogenous — are printed in the reports and repeated in the phase report.

No value here is a historical estimate. Every one is either the model's own declared default, or a
declared scenario value with the reason stated beside it. The `note` on each intervention says how
the mechanism is expressed, including the case where a mechanism has no clean switch and the arm is
the closest declared manipulation of the parameters that drive it.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass, fields, is_dataclass, replace
from typing import Final

from pydantic import BaseModel

from late_ming_lab.actors.fixtures import toy_capacity
from late_ming_lab.actors.government import StateCapacity
from late_ming_lab.core.hashing import canonical_json, hash_text
from late_ming_lab.evidence.parameters import (
    BandParameters,
    CropParameters,
    EliteParameters,
    FiscalParameters,
    HouseholdParameters,
    MarketParameters,
    MigrationParameters,
    MilitaryParameters,
    core_default_band_parameters,
    core_default_crop_parameters,
    core_default_elite_parameters,
    core_default_fiscal_parameters,
    core_default_household_parameters,
    core_default_market_parameters,
    core_default_migration_parameters,
    core_default_military_parameters,
)
from late_ming_lab.experiments.integrated import IntegratedScenario
from late_ming_lab.networks.disruption import CalmTrade, ScaledDisruption, TradeDisruption
from late_ming_lab.policies.fiscal import ArrearsEscalation, ExtractionPolicy, FixedExtraction

#: The arm every other arm is compared against.
BASELINE: Final[str] = "BASELINE"

#: The declared disruption regime of the baseline. A scenario value, not an estimate: the model has
#: no endogenous link from armed activity to transport, so a constant regime is what "disrupted"
#: can mean here, and the ablation against it is read as conditional on this declaration.
BASELINE_DISRUPTION: Final[ScaledDisruption] = ScaledDisruption(
    name="p10-baseline", risk_scale=1.5, capacity_scale=0.5
)

#: The declared escalating extraction policy of the baseline, with the numbers the P05 experiment
#: already uses for its escalating scenario (`experiments/extraction.py`).
BASELINE_EXTRACTION: Final[ArrearsEscalation] = ArrearsEscalation(
    base_effort=0.5, arrears_weight=0.5, effort_ceiling=1.0
)

#: The ablation target for the escalation arm: the P05 default policy, which never escalates.
NO_ESCALATION_POLICY: Final[FixedExtraction] = FixedExtraction(effort=0.5)


@dataclass(frozen=True, slots=True)
class ArmConfiguration:
    """One arm: the scenario, the environment regimes, state capacity and every parameter set."""

    scenario: IntegratedScenario
    disruption: TradeDisruption
    extraction_policy: ExtractionPolicy
    capacity: StateCapacity
    crop: CropParameters
    household: HouseholdParameters
    market: MarketParameters
    elite: EliteParameters
    fiscal: FiscalParameters
    military: MilitaryParameters
    band: BandParameters
    migration: MigrationParameters

    def with_updates(self, **changes: object) -> ArmConfiguration:
        """A copy with the named fields replaced; an unknown name raises."""
        unknown = set(changes) - {field.name for field in fields(self)}
        if unknown:
            raise ValueError(f"unknown arm field(s): {', '.join(sorted(unknown))}")
        return replace(self, **changes)  # type: ignore[arg-type]


def baseline_configuration() -> ArmConfiguration:
    """The one declaration of the P10 baseline: the P07 sandbox plus two declared regimes."""
    return ArmConfiguration(
        scenario=IntegratedScenario(
            label=BASELINE,
            dataset="toy",
            monthly_event_probability=0.4,
            severity_floor=0.6,
            nominal_pressure=0.02,
            pay_share_of_treasury=0.5,
            garrison_troops=300.0,
        ),
        disruption=BASELINE_DISRUPTION,
        extraction_policy=BASELINE_EXTRACTION,
        capacity=toy_capacity(),
        crop=core_default_crop_parameters(),
        household=core_default_household_parameters(),
        market=core_default_market_parameters(),
        elite=core_default_elite_parameters(),
        fiscal=core_default_fiscal_parameters(),
        military=core_default_military_parameters(),
        band=core_default_band_parameters(),
        migration=core_default_migration_parameters(),
    )


@dataclass(frozen=True, slots=True)
class Intervention:
    """One named ablation: a function from the baseline to the arm, with its question stated."""

    name: str
    question: str
    apply: Callable[[ArmConfiguration], ArmConfiguration]
    note: str


def _no_drought(config: ArmConfiguration) -> ArmConfiguration:
    return config.with_updates(
        scenario=replace(config.scenario, monthly_event_probability=0.0, severity_floor=0.0)
    )


def _no_extraction_escalation(config: ArmConfiguration) -> ArmConfiguration:
    return config.with_updates(extraction_policy=NO_ESCALATION_POLICY)


def _full_military_pay(config: ArmConfiguration) -> ArmConfiguration:
    return config.with_updates(scenario=replace(config.scenario, pay_share_of_treasury=1.0))


def _high_relief(config: ArmConfiguration) -> ArmConfiguration:
    capacity = config.capacity.model_copy(update={"relief": 1.0})
    fiscal = config.fiscal.model_copy(
        update={"relief_share_of_need": 1.0, "relief_eligibility_unmet_ratio": 0.1}
    )
    elite = config.elite.model_copy(
        update={"relief_share_of_grain_stock": 0.2, "relief_eligibility_unmet_ratio": 0.1}
    )
    return config.with_updates(capacity=capacity, fiscal=fiscal, elite=elite)


def no_elite_credit_updates() -> dict[str, float]:
    """The declared update that closes the credit channel: ``EliteParameters``, by name.

    Declared as data rather than inside the arm function so that a second phase applying the same
    intervention — V2.1-P11 does, on the historical core — reads one declaration instead of copying
    the numbers, which is how two arms that say they are the same arm stop being the same arm.
    """
    return {"loan_to_value": 0.0}


def _no_elite_credit(config: ArmConfiguration) -> ArmConfiguration:
    return config.with_updates(elite=config.elite.model_copy(update=no_elite_credit_updates()))


def open_migration_exit_updates() -> tuple[dict[str, float], dict[str, float]]:
    """The declared opening of the mobility gate: ``(MigrationParameters, HouseholdParameters)``.

    Two sets move together because the gate has two leaves in this model and opening one alone
    leaves the gate shut: a cohort becomes eligible when its rolling unmet ratio passes the
    household line, and it still cannot leave while it cannot pay the road. The declaration is one
    thing, and a caller that took half of it would be running a different arm under this name.
    """
    return (
        {
            "cost_tael_per_household": 0.0,
            "cost_tael_per_adult": 0.0,
            "transit_loss_share": 0.0,
            "minimum_households_to_move": 1.0,
        },
        {
            "permanent_migration_unmet_ratio": 0.0,
            "temporary_migration_unmet_ratio": 0.0,
        },
    )


def _no_trade_disruption(config: ArmConfiguration) -> ArmConfiguration:
    return config.with_updates(disruption=CalmTrade())


def _no_band_merger(config: ArmConfiguration) -> ArmConfiguration:
    return config.with_updates(band=config.band.model_copy(update={"merge_cohesion_above": 1.0}))


def _low_repression(config: ArmConfiguration) -> ArmConfiguration:
    return config.with_updates(
        military=config.military.model_copy(update={"suppression_effectiveness": 0.0})
    )


def _open_migration_exit(config: ArmConfiguration) -> ArmConfiguration:
    migration_updates, household_updates = open_migration_exit_updates()
    migration = config.migration.model_copy(update=migration_updates)
    household = config.household.model_copy(update=household_updates)
    return config.with_updates(migration=migration, household=household)


#: The nine ablations the phase is required to run, in the order the plan lists them.
INTERVENTIONS: Final[tuple[Intervention, ...]] = (
    Intervention(
        "NO_DROUGHT",
        "does the crisis need the climate shocks at all?",
        _no_drought,
        "the scenario's synthetic climate is replaced by the baseline climate: no shock month is "
        "ever drawn, so every difference is attributable to the forcing.",
    ),
    Intervention(
        "NO_EXTRACTION_ESCALATION",
        "does the fiscal apparatus need to escalate against arrears?",
        _no_extraction_escalation,
        "the escalating policy is replaced by the fixed one (the P07 sandbox's own default): the "
        "assessment rate and the collection effort no longer respond to the arrears stock.",
    ),
    Intervention(
        "FULL_MILITARY_PAY",
        "is the army's crisis fiscal or military?",
        _full_military_pay,
        "the pay claim's call on the treasury goes from half to all of it. What that buys is "
        "emergent: any shortfall that remains is a fiscal result, not a policy choice, which is "
        "the point of the arm.",
    ),
    Intervention(
        "HIGH_RELIEF",
        "does relief capacity change the trajectory?",
        _high_relief,
        "every relief channel is raised towards its declared ceiling: the county's relief capacity "
        "0.5 → 1.0, its release share of measured need 0.5 → 1.0, eligibility 0.05 → 0.1, and "
        "the elite channel's grain share 0.05 → 0.2 with the same wider eligibility.",
    ),
    Intervention(
        "NO_ELITE_CREDIT",
        "does household survival depend on borrowed silver?",
        _no_elite_credit,
        "the loan-to-value rule goes to zero, so the lender's credit limit is zero whatever the "
        "collateral: no elite loan is ever made.",
    ),
    Intervention(
        "NO_TRADE_DISRUPTION",
        "does the market need the transport regime to be harsh?",
        _no_trade_disruption,
        "the declared disruption regime is replaced by calm trade: full link capacity and unit "
        "risk. Conditional on the baseline regime's declaration, not on any measured blockade.",
    ),
    Intervention(
        "NO_BAND_MERGER",
        "is consolidation, rather than band numbers, what concentrates armed force?",
        _no_band_merger,
        "the cohesion bar for merging two bands is raised to its declared maximum, 1.0, so a merge "
        "requires both bands at exactly full cohesion — a state the clamp reaches only for a fully "
        "fed band in a month with no intake. The arm is reported with the merge counts it actually "
        "produced, because whether it binds is a measurement here, not a proof.",
    ),
    Intervention(
        "LOW_REPRESSION",
        "is suppression load-bearing, and in which direction?",
        _low_repression,
        "suppression effectiveness goes to zero — the strongest reading of *low*, so the arm is "
        "the full removal of the state's coercive reach against armed groups rather than a graded "
        "reduction.",
    ),
    Intervention(
        "OPEN_MIGRATION_EXIT",
        "is the mobility gate, rather than distress itself, what decides who leaves?",
        _open_migration_exit,
        "movement becomes free and ungated: both move costs and the transit loss go to zero, the "
        "minimum group falls to a single household, and the distress lines that qualify a "
        "household to leave go to zero.",
    ),
)

#: The two-way arms, so an interaction can be measured rather than assumed. Each composes two
#: ablations; the report compares the joint arm's effect with the sum of the two single arms'.
JOINT_ARMS: Final[tuple[Intervention, ...]] = (
    Intervention(
        "JOINT_NO_DROUGHT+FULL_MILITARY_PAY",
        "is fiscal capacity for the army worth anything without the climate shocks?",
        lambda config: _full_military_pay(_no_drought(config)),
        "the composition of two declared ablations; its difference from the baseline is the "
        "computed union of the two.",
    ),
    Intervention(
        "JOINT_NO_DROUGHT+HIGH_RELIEF",
        "does relief matter in a year with no harvest failure?",
        lambda config: _high_relief(_no_drought(config)),
        "the composition of two declared ablations.",
    ),
    Intervention(
        "JOINT_NO_EXTRACTION_ESCALATION+NO_ELITE_CREDIT",
        "do extraction pressure and credit access substitute for one another?",
        lambda config: _no_elite_credit(_no_extraction_escalation(config)),
        "the composition of two declared ablations.",
    ),
)


def arm_configuration(name: str) -> ArmConfiguration:
    """The configuration of one declared arm, by name."""
    if name == BASELINE:
        return baseline_configuration()
    for intervention in (*INTERVENTIONS, *JOINT_ARMS):
        if intervention.name == name:
            return intervention.apply(baseline_configuration())
    raise KeyError(f"unknown arm {name!r}")


def declared_arms() -> tuple[str, ...]:
    """The baseline followed by every ablation and joint arm, in declaration order."""
    return (BASELINE, *(item.name for item in INTERVENTIONS), *(item.name for item in JOINT_ARMS))


def question_for(name: str) -> str:
    """The question an arm asks; the baseline's is stated here rather than implied."""
    for intervention in (*INTERVENTIONS, *JOINT_ARMS):
        if intervention.name == name:
            return intervention.question
    if name == BASELINE:
        return (
            "the declared reference condition: escalation and disruption on, everything else the "
            "P07 sandbox's own defaults"
        )
    raise KeyError(f"unknown arm {name!r}")


def note_for(name: str) -> str:
    """How an arm's mechanism is expressed, for the report."""
    for intervention in (*INTERVENTIONS, *JOINT_ARMS):
        if intervention.name == name:
            return intervention.note
    if name == BASELINE:
        return "the baseline itself"
    raise KeyError(f"unknown arm {name!r}")


def configuration_diff(
    baseline: ArmConfiguration, arm: ArmConfiguration
) -> tuple[tuple[str, str, str], ...]:
    """Every field that differs, as ``(dotted name, baseline value, arm value)``.

    The difference is computed, so a report can never describe an arm as changing something it does
    not change, or miss something it does. Pydantic parameter sets are compared field by field, the
    scenario attribute by attribute, and the environment regimes as whole objects.
    """
    differences: list[tuple[str, str, str]] = []
    for field in fields(baseline):
        before = getattr(baseline, field.name)
        after = getattr(arm, field.name)
        if before == after:
            continue
        if isinstance(before, BaseModel) and type(before) is type(after):
            for name in type(before).model_fields:
                left, right = getattr(before, name), getattr(after, name)
                if left != right:
                    differences.append((f"{field.name}.{name}", str(left), str(right)))
        elif isinstance(before, BaseModel) or isinstance(after, BaseModel):
            # Two different regimes: the classes themselves are the difference, so the whole value
            # is recorded rather than a field-by-field comparison that has no common fields.
            differences.append((field.name, repr(before), repr(after)))
        elif is_dataclass(before) and not isinstance(before, type):
            for nested in fields(before):
                left, right = getattr(before, nested.name), getattr(after, nested.name)
                if left != right:
                    differences.append((f"{field.name}.{nested.name}", str(left), str(right)))
        else:
            differences.append((field.name, str(before), str(after)))
    return tuple(differences)


def apply_parameter_draw(
    config: ArmConfiguration, draw: dict[str, float], names_by_set: dict[str, str]
) -> ArmConfiguration:
    """A copy of the arm with a parameter draw applied, by field name.

    `names_by_set` maps a parameter-set class name to the arm field holding it, so a design row can
    move parameters without the runner knowing which set each one lives in.
    """
    grouped: dict[str, dict[str, float]] = {}
    for name, value in draw.items():
        parameter_set = names_by_set.get(name)
        if parameter_set is None:
            raise KeyError(f"the draw names an unknown parameter: {name!r}")
        grouped.setdefault(parameter_set, {})[name] = float(value)
    updated: dict[str, object] = {}
    for field_name, values in grouped.items():
        current = getattr(config, field_name)
        updated[field_name] = current.model_copy(update=values)
    return config.with_updates(**updated)


def configuration_hash(config: ArmConfiguration) -> str:
    """A digest of everything about an arm that a run's outcome depends on.

    The scenario, the two environment regimes and every parameter set are dumped to canonical JSON
    and hashed together, so two arms that differ in nothing hash the same and an arm whose declared
    content changed cannot keep its old hash.
    """
    payload = {
        "scenario": asdict(config.scenario),
        "disruption": _dump(config.disruption),
        "extraction_policy": _dump(config.extraction_policy),
        "capacity": config.capacity.model_dump(mode="json"),
        **{
            field.name: getattr(config, field.name).model_dump(mode="json")
            for field in fields(config)
            if field.name not in {"scenario", "disruption", "extraction_policy", "capacity"}
        },
    }
    return hash_text(canonical_json(payload))


def _dump(value: object) -> object:
    """A regime's declared content as JSON-ready data; the regimes are pydantic models today."""
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    raise TypeError(f"a regime must be a pydantic model to be hashed, not {type(value).__name__}")


#: The arm field each parameter set lives in, so a draw by field name can find its set.
FIELD_BY_PARAMETER_SET: Final[dict[str, str]] = {
    "CropParameters": "crop",
    "HouseholdParameters": "household",
    "MarketParameters": "market",
    "EliteParameters": "elite",
    "FiscalParameters": "fiscal",
    "MilitaryParameters": "military",
    "BandParameters": "band",
    "MigrationParameters": "migration",
}
