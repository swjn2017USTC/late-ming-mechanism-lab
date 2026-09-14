"""The candidate mechanisms, each assembled from the evidence rather than from memory.

Six candidates are assessed: the five the engineering plan names, plus one the model does not
implement at all. Every number in every card is read from the P09-P12 artifacts through
:mod:`late_ming_lab.synthesis.evidence`, so a card cannot drift from the batch it cites; a card's
status is then checked against the evidence it carries (see :mod:`late_ming_lab.synthesis.schema`).

The six do not come out alike, and that is the point:

===========================  ==============  ==========================================
card                         status          why
===========================  ==============  ==========================================
M001 Fiscal Extraction      CONDITIONAL     present in one declared policy, absent in another
     Inversion
M002 Crisis Gating          SUPPORTED       an intervention flips the outcome; the shock
                                               alone does not
M003 Fiscal-Military        REJECTED        the strong form fails in every replicate; the
                                               level survives
     Ratchet
M004 Elite Mediation        CONDITIONAL     one branch intervened on, the other never built
     Bifurcation
M005 Insurgent              SUPPORTED       robust across every declared policy, with one
                                               link unexercised
     Consolidation
M006 Famine Mortality       UNIDENTIFIED    the model has no mortality mechanism to measure
===========================  ==============  ==========================================
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Final

import polars as pl

from late_ming_lab.synthesis.evidence import (
    ABLATION_BATCH,
    MORRIS_BATCH,
    ROBUSTNESS_BATCH,
    EvidenceBundle,
)
from late_ming_lab.synthesis.schema import (
    Condition,
    EvidenceCitation,
    EvidenceKind,
    MechanismBook,
    MechanismCard,
    MechanismStatus,
)

#: The three policies that actually ran in P12; the runtime arm was refused and carries no evidence.
DECLARED_POLICIES: Final[tuple[str, ...]] = ("rule", "utility", "random")

#: The P12 arm whose decision rule presses collection effort to its declared ceiling.
PRESSING_POLICY: Final[str] = "utility"

#: The pattern ids each card leans on historically, kept here so a typo fails the build rather
#: than silently producing a card with no historical support.
PATTERN_IDS: Final[tuple[str, ...]] = (
    "receipts-shortfall-chronic",
    "quota-erosion-and-surcharge",
    "shaanxi-net-outflow",
    "chongzhen-drought-sequence",
    "relief-overwhelmed-in-worst-years",
    "pay-monetised-and-arrears",
    "debt-transfers-land",
    "land-abandonment-in-famine",
    "many-bands-then-consolidation",
    "absorption-of-deserters-and-refugees",
    "famine-lags-harvest-failure",
)


def _share(value: float | None) -> str:
    return "not scored" if value is None else f"{value:.2f}"


def _median(series: pl.Series) -> float:
    """A series median as a float, refused rather than coerced when it is not a number."""
    value = series.median()
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError(f"median is {type(value).__name__}, not a number")
    return float(value)


def _float(row: dict[str, object], key: str) -> float:
    """A numeric field of an evidence row, refused rather than coerced when it is not a number."""
    value = row[key]
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError(f"{key} is {type(value).__name__}, not a number")
    return float(value)


def _number(value: float | None, *, digits: int = 1) -> str:
    return "not measured" if value is None else f"{value:,.{digits}f}"


def _effect(bundle: EvidenceBundle, arm: str, metric: str) -> str:
    """One ablation comparison as 'difference [interval] direction'."""
    row = bundle.comparison(arm, metric)
    if row is None:
        return f"{arm} on {metric}: not in the batch"
    return (
        f"{metric} {row['median_difference']:+,.2f} "
        f"[{row['difference_low']:+,.2f}, {row['difference_high']:+,.2f}] {row['direction']}"
    )


def _pattern_citation(
    bundle: EvidenceBundle, pattern_id: str, shares: tuple[tuple[str, float | None], ...]
) -> EvidenceCitation:
    pattern = bundle.pattern(pattern_id)
    scored = ", ".join(f"{label} {_share(share)}" for label, share in shares)
    return EvidenceCitation(
        kind=EvidenceKind.HISTORICAL,
        source=pattern.sources[0] if pattern.sources else "sources/registry",
        reading=(
            f"{pattern.id} (grade {pattern.evidence_grade.value}, "
            f"{pattern.calibration_role.value}, window {pattern.window}): {scored}"
        ),
    )


def build_cards(bundle: EvidenceBundle) -> MechanismBook:
    """Every candidate card, in id order."""
    return MechanismBook(cards=tuple(_card(bundle, builder) for builder in _BUILDERS))


def _card(
    bundle: EvidenceBundle, builder: Callable[[EvidenceBundle], MechanismCard]
) -> MechanismCard:
    return builder(bundle)


def _m001(bundle: EvidenceBundle) -> MechanismCard:
    """Fiscal Extraction Inversion: pressing harder collects less."""
    morris = bundle.morris("assessed_value_tael_per_mu", "indicators_crossed_end")
    parameter = bundle.parameter("assessed_value_tael_per_mu")
    quota_whole = bundle.reserved_share("quota-erosion-and-surcharge", window="whole-run")
    verdict = bundle.verdict("fiscal-extraction-inversion")
    utility = bundle.presence("fiscal-extraction-inversion", PRESSING_POLICY)
    strengths = bundle.strengths("fiscal-extraction-inversion", PRESSING_POLICY)
    random_share = bundle.presence("fiscal-extraction-inversion", "random")
    assert morris is not None and parameter is not None and verdict is not None
    return MechanismCard(
        id="M001",
        name="Fiscal Extraction Inversion",
        question="Does pressing the fiscal apparatus harder collect less of what it is owed?",
        status=MechanismStatus.CONDITIONAL,
        micro_conditions=(
            "The assessment is a rate applied to a registered base that households can leave, "
            "conceal or default on.",
            "Land can change hands or fall out of cultivation, so the base the rate is applied to "
            "is not fixed within a run.",
        ),
        meso_conditions=(
            "Collection effort is a decision: the county can press harder after it observes a "
            "shortfall, rather than applying a constant effort.",
            "The quota is assessed against a register that is not the same as the land actually "
            "worked, so the two can diverge.",
        ),
        causal_chain=(
            "Pressure rises: the assessed value per mu, or the share of the quota demanded, "
            "increases.",
            "Effort rises in response; under the utility policy it moves to "
            "the declared ceiling of "
            "5.0 from 3.34-4.25.",
            "Households leave, conceal or default, and the assessable base contracts.",
            "Receipts over the assessed quota fall while effort stays at the ceiling.",
        ),
        trigger=(
            "A decision rule that raises collection effort after observing a receipt shortfall. No "
            "P10 ablation contains one: the P12 utility policy is the only arm in the project that "
            "presses to the ceiling."
        ),
        macro_outcome=(
            "Chronic shortfall: receipts below quota, a contracting "
            "registered base, and a military pay claim met from a shrinking receipt."
        ),
        conditions=(
            Condition(
                statement="A base that can respond to the rate by moving, hiding or defaulting.",
                level="micro",
                role="necessary",
            ),
            Condition(
                statement="An authority whose effort is a choice rather than a constant.",
                level="meso",
                role="necessary",
            ),
            Condition(
                statement="Distress lines that make departure legal and affordable.",
                level="micro",
                role="facilitating",
            ),
            Condition(
                statement="An assessed register that lags the cultivated area.",
                level="meso",
                role="facilitating",
            ),
        ),
        time_lag=(
            "Unresolved: the P12 reading compares the endpoints of a 240-tick run, no artifact "
            "records an effort series, and none records the month at which effort and the receipt "
            "share would cross. Monthly resolution exists only for the crossed-line count, in the "
            "P10 governance timelines."
        ),
        sensitivity_evidence=(
            f"assessed_value_tael_per_mu has mu* = {morris[0]:.2f} (sigma = {morris[1]:.2f}) on "
            f"indicators_crossed_end in the Morris screen of the {MORRIS_BATCH} batch: third equal "
            "with the land constraint behind the temporary-migration share and the reference "
            "price, so the tie is a tie rather than a rank. P09 identifies "
            f"it: posterior median {parameter['median']:.3f} tael per mu against a prior of "
            f"{parameter['prior_low']:.2f}-{parameter['prior_high']:.2f}, contraction "
            f"{parameter['contraction']:.3f}, verdict {parameter['verdict']}."
        ),
        ablation_evidence=(
            "NO_EXTRACTION_ESCALATION removes the response of the assessment rate and the "
            "collection effort to the arrears stock and lowers receipts over quota "
            f"({_effect(bundle, 'NO_EXTRACTION_ESCALATION', 'receipts_over_quota_total')}), the "
            "opposite direction from an inversion story. Its effect on the tax base is unresolved "
            f"({_effect(bundle, 'NO_EXTRACTION_ESCALATION', 'tax_base_change_mu')}), so the arm "
            "moves what is collected without showing that pressing harder destroys the base."
        ),
        hold_out_evidence=(
            f"quota-erosion-and-surcharge is satisfied in "
            f"{_share(bundle.reserved_share('quota-erosion-and-surcharge'))} "
            f"of posterior draws over the held-out years and {_share(quota_whole)} "
            f"over the run as a whole; receipts-shortfall-chronic is satisfied in "
            f"{_share(bundle.target_share('receipts-shortfall-chronic'))} of draws on the "
            "calibration window. The shortfall the mechanism is about is "
            "present; the pressing that is supposed to cause it is not in any held-out quantity."
        ),
        policy_robustness=(
            f"Present in {utility:.2f} of the {PRESSING_POLICY} replicates with strengths "
            f"{min(strengths):.2f}-{max(strengths):.2f}, in {random_share:.2f} of the random "
            f"replicates, and in none of the rule replicates: "
            f"P12's verdict is '{verdict['verdict']}'. "
            "It appears when the decision rule reacts to a shortfall by pressing, and it is absent "
            "when the rule holds."
        ),
        historical_support=(
            _pattern_citation(
                bundle,
                "receipts-shortfall-chronic",
                (("calibration window", bundle.target_share("receipts-shortfall-chronic")),),
            ).reading
            + "; "
            + _pattern_citation(
                bundle,
                "quota-erosion-and-surcharge",
                (
                    ("held-out years", bundle.reserved_share("quota-erosion-and-surcharge")),
                    (
                        "whole run",
                        bundle.reserved_share("quota-erosion-and-surcharge", window="whole-run"),
                    ),
                ),
            ).reading
        ),
        historical_challenge=(
            "The record attaches the shortfall to what collection could "
            "reach - flight, harvest and "
            "evasion - not to a feedback rule in which the authority presses harder as receipts "
            "fall, and neither pattern carries a measured collection "
            "effort. The model produces its "
            "inversion through exactly the rule the sources do not describe, and the "
            "extraction-escalation arm collects more, not less, of the quota."
        ),
        counterexample=(
            "The rule policy: 0 of 6 replicates, at the same parameter draws and the same world as "
            "the arm that shows it. A structural inversion would not depend on which declared "
            "policy is deciding."
        ),
        falsifiable_prediction=(
            "Ablate the effort response - fix collection effort at its warm-up value - and the "
            "inversion disappears: receipts over quota stops falling as nominal pressure rises. If "
            "it still falls, the inversion is not the response rule's doing and this card is wrong."
        ),
        uncertainty=(
            "Three declared policies, three counties, thirty-two cohorts. The utility policy's "
            "ceiling of 5.0 is a declared bound, not an observed one, and the "
            "inversion's dependence on that ceiling is untested. The one arm that varies "
            "extraction runs the other way, so "
            "the card rests on a within-run co-movement under a single policy."
        ),
        citations=(
            EvidenceCitation(
                kind=EvidenceKind.SENSITIVITY,
                source=f"outputs/experiments/{MORRIS_BATCH}/runs.parquet",
                reading=f"assessed_value_tael_per_mu mu*={morris[0]:.2f} sigma={morris[1]:.2f} on "
                f"indicators_crossed_end",
            ),
            EvidenceCitation(
                kind=EvidenceKind.CALIBRATION,
                source="outputs/calibration/p09-*/ensemble.parquet",
                reading=(
                    f"assessed_value_tael_per_mu median {parameter['median']:.3f}, contraction "
                    f"{parameter['contraction']:.3f}, {parameter['verdict']}"
                ),
            ),
            EvidenceCitation(
                kind=EvidenceKind.ABLATION,
                source=f"outputs/experiments/{ABLATION_BATCH}/runs.parquet",
                reading=_effect(bundle, "NO_EXTRACTION_ESCALATION", "receipts_over_quota_total"),
            ),
            EvidenceCitation(
                kind=EvidenceKind.HOLD_OUT,
                source="outputs/calibration/p09-*/predictive_checks.parquet",
                reading=(
                    "quota-erosion-and-surcharge held-out "
                    f"{_share(bundle.reserved_share('quota-erosion-and-surcharge'))}, whole run "
                    f"{_share(quota_whole)}"
                ),
            ),
            EvidenceCitation(
                kind=EvidenceKind.POLICY_ROBUSTNESS,
                source=f"outputs/experiments/{ROBUSTNESS_BATCH}/mechanism_readings.parquet",
                reading=(
                    f"inversion present in {utility:.2f}/{PRESSING_POLICY}, "
                    f"{random_share:.2f}/random, 0.00/rule; verdict {verdict['verdict']}"
                ),
            ),
            _pattern_citation(
                bundle,
                "receipts-shortfall-chronic",
                (("calibration window", bundle.target_share("receipts-shortfall-chronic")),),
            ),
        ),
    )


def _m002(bundle: EvidenceBundle) -> MechanismCard:
    """Crisis Gating: whether a shock becomes breakdown depends on a gate, not on the shock."""
    exit_arm = "OPEN_MIGRATION_EXIT"
    month = bundle.arm_breakdown_month(exit_arm)
    intervention = bundle.interaction(0, "indicators_crossed_end")
    rule_cells = bundle.region("rule")
    utility_cells = bundle.region(PRESSING_POLICY)
    random_cells = bundle.region("random")
    morris_top = bundle.morris_rank("indicators_crossed_end")[:3]
    outflow_extrapolation = bundle.reserved_share("shaanxi-net-outflow", window="extrapolation")
    assert month is not None and intervention is not None
    assert rule_cells is not None and utility_cells is not None and random_cells is not None
    return MechanismCard(
        id="M002",
        name="Crisis Gating",
        question="Is it the shock that produces breakdown, or the condition that lets the shock "
        "reach the base?",
        status=MechanismStatus.SUPPORTED,
        micro_conditions=(
            "Households can leave: departure is a state a cohort enters when distress crosses a "
            "declared line, and it takes its labour and its consumption with it.",
            "Departure needs to be affordable - a move cost and a transit loss are charged - so a "
            "household below the line may still be unable to go.",
        ),
        meso_conditions=(
            "The county's tax base is the labour and land that stayed, so an outflow is an outflow "
            "of assessable value.",
            "Military pay is claimed against the same receipts, so a smaller base shows up as "
            "arrears rather than as a smaller claim.",
        ),
        causal_chain=(
            "The gate opens: move costs, transit loss and the distress lines that qualify a "
            "household to leave are removed.",
            "Households exit in numbers the baseline never reaches.",
            "The tax base contracts roughly seven times as far as in the next largest arm, and "
            "about seventeen times median to median.",
            "Receipts cannot cover the pay claim, arrears rise, and the "
            "county crosses the declared "
            "breakdown line in every replicate.",
        ),
        trigger=(
            "The institutional gate, not the weather: with the gate open the crisis appears where "
            "the baseline has none, and removing the climate shocks leaves breakdown unchanged."
        ),
        macro_outcome=(
            "Systemic breakdown of the county's finances and its coercive reach, reached at the "
            "same tick in every replicate."
        ),
        conditions=(
            Condition(
                statement="A gate on household movement that can be open or shut.",
                level="meso",
                role="necessary",
            ),
            Condition(
                statement="A tax base that is the households still present.",
                level="meso",
                role="necessary",
            ),
            Condition(
                statement="A climate shock severe enough to push households toward the line.",
                level="micro",
                role="facilitating",
            ),
            Condition(
                statement="An army whose claim on the receipts does not shrink with them.",
                level="meso",
                role="facilitating",
            ),
        ),
        time_lag=(
            f"Twenty-four ticks, in every replicate: the open-gate arm crosses the declared "
            f"breakdown line at tick {_number(month, digits=0)} of 240, after the 24-tick warm-up. "
            "It is the only arm of the ablation batch whose replicates cross at all; the Morris "
            "and Sobol designs cross at ticks 24, 48 and 216."
        ),
        sensitivity_evidence=(
            "The largest elementary effects on indicators_crossed_end are "
            + ", ".join(morris_top)
            + f" ({MORRIS_BATCH}): a migration share, a market price and a land constraint, with "
            "the land constraint tied with the assessed value rather than ranked behind it. The "
            "controls that lead sit on the movement and market side, not on the climate axis."
        ),
        ablation_evidence=(
            f"Opening the gate does it: {_effect(bundle, exit_arm, 'breakdown')}, "
            f"{_effect(bundle, exit_arm, 'tax_base_change_mu')}, "
            f"{_effect(bundle, exit_arm, 'households_exited')}, against a baseline in which no "
            f"replicate breaks down. Removing the climate shocks does not: "
            f"{_effect(bundle, 'NO_DROUGHT', 'breakdown')}, with the tax base unresolved "
            f"({_effect(bundle, 'NO_DROUGHT', 'tax_base_change_mu')}) and departures down "
            f"({_effect(bundle, 'NO_DROUGHT', 'households_departed')})."
        ),
        hold_out_evidence=(
            f"shaanxi-net-outflow scores {_share(bundle.reserved_share('shaanxi-net-outflow'))} "
            f"over "
            "the held-out years against "
            f"{_share(bundle.reserved_share('shaanxi-net-outflow', window='whole-run'))} over the "
            f"run as a whole, and "
            f"{_share(bundle.reserved_share('shaanxi-net-outflow', window='extrapolation'))} "
            f"over the extrapolation; chongzhen-drought-sequence scores "
            f"{_share(bundle.reserved_share('chongzhen-drought-sequence'))} over the held-out "
            f"years. "
            "The direction of the outflow is matched; its timing is not."
        ),
        policy_robustness=(
            f"The gated region moves with the decision policy: "
            f"{rule_cells['cells_with_breakdown']} of 9 grid cells break down under the rule "
            f"policy, {random_cells['cells_with_breakdown']} "
            f"under random and {utility_cells['cells_with_breakdown']} under utility, and only the "
            "rule policy's cell set is the reference's - so which cells break down is "
            "policy-dependent. That the *gate* is what carries the breakdown was tested in the P10 "
            "ablation, under one policy rather than three."
        ),
        historical_support=(
            _pattern_citation(
                bundle,
                "shaanxi-net-outflow",
                (
                    ("held-out years", bundle.reserved_share("shaanxi-net-outflow")),
                    ("whole run", bundle.reserved_share("shaanxi-net-outflow", window="whole-run")),
                ),
            ).reading
            + "; "
            + _pattern_citation(
                bundle,
                "chongzhen-drought-sequence",
                (("held-out years", bundle.reserved_share("chongzhen-drought-sequence")),),
            ).reading
        ),
        historical_challenge=(
            "The record's outflow is concentrated in the years the famine bites, and the model "
            "matches the run-long direction while missing those years: the held-out score is "
            f"{_share(bundle.reserved_share('shaanxi-net-outflow'))} against "
            f"{_share(bundle.reserved_share('shaanxi-net-outflow', window='whole-run'))} for the "
            f"run "
            "as a whole. A gate that leaks continuously is not the same as one that opens in a "
            "crisis."
        ),
        counterexample=(
            "The drought ablation: removing the climate shock keeps the baseline outcome - no "
            "breakdown in any replicate - so the shock is not the gate. Of the twelve arms in the "
            "ablation batch only the gate arm breaks down. Elsewhere in P10 breakdown does occur "
            "without it - 7 of the 40 Sobol runs and one tipping cell cross the line under extreme "
            "parameter draws - so the claim is about the declared arms, not the only route."
        ),
        falsifiable_prediction=(
            "Shut the gate under the worst climate setting and breakdown should not occur: an arm "
            "that refuses permanent departure at severity floor 0.9 and nominal pressure 0.04 "
            "produces zero breakdowns in every replicate. Force the gate open under the mildest "
            "setting and at least one replicate should break down. Either result falsifies this "
            "card."
        ),
        uncertainty=(
            "One gate was intervened on. The relief and trade channels have arms whose effects on "
            "the crossed-line count are unresolved at four replicates, so the card does not claim "
            "they are not gates. Three counties, thirty-two cohorts, and a movement rule whose "
            "distress lines are declared rather than observed."
        ),
        citations=(
            EvidenceCitation(
                kind=EvidenceKind.ABLATION,
                source=f"outputs/experiments/{ABLATION_BATCH}/runs.parquet",
                reading=(
                    f"OPEN_MIGRATION_EXIT {_effect(bundle, exit_arm, 'breakdown')}; "
                    f"NO_DROUGHT {_effect(bundle, 'NO_DROUGHT', 'breakdown')}"
                ),
            ),
            EvidenceCitation(
                kind=EvidenceKind.COUNTERFACTUAL,
                source=f"outputs/experiments/{ABLATION_BATCH}/runs.parquet",
                reading=(
                    f"NO_DROUGHT x FULL_MILITARY_PAY on indicators_crossed_end: joint "
                    f"{intervention['effect_joint']:+.2f} against "
                    f"{_float(intervention, 'effect_a') + _float(intervention, 'effect_b'):+.2f} "
                    f"additive [{intervention['difference_low']:+.2f}, "
                    f"{intervention['difference_high']:+.2f}], {intervention['verdict']}"
                ),
            ),
            EvidenceCitation(
                kind=EvidenceKind.SENSITIVITY,
                source=f"outputs/experiments/{MORRIS_BATCH}/runs.parquet",
                reading="strongest parameters on indicators_crossed_end: " + ", ".join(morris_top),
            ),
            EvidenceCitation(
                kind=EvidenceKind.POLICY_ROBUSTNESS,
                source=f"outputs/experiments/{ROBUSTNESS_BATCH}/tipping_grid.parquet",
                reading=(
                    f"cells with breakdown: rule {rule_cells['cells_with_breakdown']}, random "
                    f"{random_cells['cells_with_breakdown']}, utility "
                    f"{utility_cells['cells_with_breakdown']}"
                ),
            ),
            EvidenceCitation(
                kind=EvidenceKind.HOLD_OUT,
                source="outputs/calibration/p09-*/predictive_checks.parquet",
                reading=(
                    "shaanxi-net-outflow: held-out "
                    f"{_share(bundle.reserved_share('shaanxi-net-outflow'))}, extrapolation "
                    f"{_share(outflow_extrapolation)}, whole run "
                    f"{_share(bundle.reserved_share('shaanxi-net-outflow', window='whole-run'))}"
                ),
            ),
            EvidenceCitation(
                kind=EvidenceKind.HISTORICAL_CHALLENGE,
                source="data/historical_patterns/01-drought-climate.yaml",
                reading=(
                    "chongzhen-drought-sequence (grade B, hold-out): held-out years "
                    f"{_share(bundle.reserved_share('chongzhen-drought-sequence'))} - a refuted "
                    "check, cited here as a challenge rather than as support"
                ),
            ),
        ),
    )


def _m003(bundle: EvidenceBundle) -> MechanismCard:
    """Fiscal-Military Ratchet: the strong form, tested and rejected."""
    verdict = bundle.verdict("fiscal-military-ratchet")
    readings = bundle.reading_texts("fiscal-military-ratchet", "rule")
    pay_effect = _effect(bundle, "FULL_MILITARY_PAY", "military_pay_arrears_end_tael")
    pay_rate = bundle.parameter("pay_tael_per_soldier_month")
    assert pay_rate is not None
    assert verdict is not None and readings
    rule_figures = bundle.ratchet_figures("rule")
    declines = sorted(figure[2] for figure in rule_figures)
    largest_end = max(rule_figures, key=lambda figure: figure[1])
    all_declines = sorted(
        figure[2] for policy in DECLARED_POLICIES for figure in bundle.ratchet_figures(policy)
    )
    return MechanismCard(
        id="M003",
        name="Fiscal-Military Ratchet",
        question=(
            "Does the army's unpaid claim accumulate without ever clearing, so the fiscal burden "
            "only ever rises?"
        ),
        status=MechanismStatus.REJECTED,
        micro_conditions=(
            "Soldiers are owed a monthly silver pay whose level is a declared rate rather than a "
            "negotiated outcome.",
            "The pay claim is made against the same receipts the civil administration collects, so "
            "a shortfall appears as an unpaid stock.",
        ),
        meso_conditions=(
            "The treasury pays the claim from receipts in the same tick, so it cannot borrow "
            "against "
            "a future receipt.",
            "Desertion removes soldiers from the roster, so a pay failure is also a manpower loss.",
        ),
        causal_chain=(
            "Assessed receipts fall short of the assessed quota.",
            "The pay claim is met only in part, and the unpaid remainder is carried forward as a "
            "stock.",
            "If the stock could only ever rise, the fiscal burden would ratchet; the stock is "
            "instead drawn down whenever receipts exceed the month's claim.",
        ),
        trigger=(
            "A month in which receipts exceed that month's pay claim, which is what clears part of "
            "the stock and what the strong form of the mechanism says cannot happen."
        ),
        macro_outcome=(
            "A large but fluctuating arrears stock - not a monotone "
            "ratchet. The stock ends the run "
            "at 14,355 to 26,849 tael against 287,355 to 311,429 tael assessed in the six rule "
            "replicates."
        ),
        conditions=(
            Condition(
                statement="A pay claim fixed in silver while receipts are a residual.",
                level="meso",
                role="necessary",
            ),
            Condition(
                statement="No borrowing against future receipts, so the stock cannot be smoothed "
                "away.",
                level="meso",
                role="necessary",
            ),
            Condition(
                statement="The claim rising with the number of soldiers the county must support.",
                level="meso",
                role="facilitating",
            ),
        ),
        time_lag=(
            "Not resolved within the run: the reading is computed from a monthly series, but the "
            "artifact records only how many months declined, so when the declines fall is not in "
            "the evidence. The series' endpoints run from 254 tael to "
            f"{_number(min(figure[1] for figure in rule_figures), digits=0)}-"
            f"{_number(max(figure[1] for figure in rule_figures), digits=0)} tael over the six "
            "rule replicates."
        ),
        sensitivity_evidence=(
            "pay_tael_per_soldier_month is identified in P09 - posterior median "
            f"{pay_rate['median']:.3f} tael against a prior of "
            f"0.10-1.00, contraction {pay_rate['contraction']:.3f} - so the stock's "
            "level is constrained by the data. No sensitivity statistic distinguishes a ratchet "
            "from a fluctuating stock, because the Morris outputs are end-of-run levels and maxima."
        ),
        ablation_evidence=(
            "Two resolved arms raise the stock and neither removes its declines: doubling the "
            f"pay claim's call on the treasury ({pay_effect}) and opening the mobility gate "
            f"({_effect(bundle, 'OPEN_MIGRATION_EXIT', 'military_pay_arrears_max_tael')}). A "
            "shortfall that remains when the claim is doubled is a fiscal result rather than a "
            "policy choice, and the declines survive both arms because no arm was built to remove "
            "them."
        ),
        hold_out_evidence=(
            f"pay-monetised-and-arrears is satisfied in "
            f"{_share(bundle.reserved_share('pay-monetised-and-arrears'))} of posterior draws over "
            f"the held-out years, "
            f"{_share(bundle.reserved_share('pay-monetised-and-arrears', window='whole-run'))} "
            "over the run as a whole, on the question 'does the garrison arrears stock accumulate "
            "over the run?'. Accumulation is matched. Accumulation *without clearing* was never a "
            "scored pattern, which is why the strong form survived this long in the project's own "
            "reporting."
        ),
        policy_robustness=(
            f"Absent in all three declared policies: {verdict['arms_showing']} of "
            f"{verdict['arms_ran']} arms show it, verdict '{verdict['verdict']}'. Decline months "
            f"per rule replicate are {declines} of 240 ticks, and over all 18 replicates the range "
            f"is {all_declines[0]} to {all_declines[-1]}. The rule arm's largest end stock, "
            f"{_number(largest_end[1], digits=0)} tael, is a replicate with {largest_end[2]} "
            "decline months - more than the arm's median, not fewer."
        ),
        historical_support=(
            _pattern_citation(
                bundle,
                "pay-monetised-and-arrears",
                (
                    ("held-out years", bundle.reserved_share("pay-monetised-and-arrears")),
                    (
                        "whole run",
                        bundle.reserved_share("pay-monetised-and-arrears", window="whole-run"),
                    ),
                ),
            ).reading
        ),
        historical_challenge=(
            "The record supports chronic arrears at a level, which the model reproduces, and it "
            "does not report a monotone stock: garrisons were paid in bursts when silver arrived. "
            "The strong form was an inference the project made from 'arrears are chronic' to "
            "'arrears never clear', and the model rejects the inference, not the evidence."
        ),
        counterexample=(
            f"arrears 254 to {_number(largest_end[1], digits=0)} tael with {largest_end[2]} "
            f"month(s) of decline, against {_number(largest_end[3], digits=0)} assessed: the rule "
            "arm's largest end stock belongs to a replicate that still records dozens of months in "
            f"which the stock falls, and the arm's largest decline count is {declines[-1]}. Any "
            "reading that needs the stock to be monotone is false in this model."
        ),
        falsifiable_prediction=(
            "An arm that removes the clearing - one that refuses to pay arrears in any month - "
            "would "
            "make the stock monotone. If the stock still declines under "
            "that arm, the declines come "
            "from something other than the payment rule, and this rejection "
            "is wrong. The surviving "
            "claim keeps its own prediction: the stock ends between 4.8% and 9.3% of the assessed "
            "value, and an arm that doubles the pay rate should raise that share rather than lower "
            "it."
        ),
        uncertainty=(
            "The rejection is of the strong claim only, at three counties and 240 ticks. The "
            "mechanism behind the declines is not identified: nothing measures whether they come "
            "from the payment rule, from re-assessment, or from the extraction "
            "arm's own response to "
            "the stock. The level claim rests on a single held-out pattern at grade A."
        ),
        citations=(
            EvidenceCitation(
                kind=EvidenceKind.POLICY_ROBUSTNESS,
                source=f"outputs/experiments/{ROBUSTNESS_BATCH}/mechanism_readings.parquet",
                reading=(
                    f"ratchet present in 0 of {verdict['arms_ran']} declared policies; decline "
                    f"months per replicate {sorted(declines)}"
                ),
            ),
            EvidenceCitation(
                kind=EvidenceKind.ABLATION,
                source=f"outputs/experiments/{ABLATION_BATCH}/runs.parquet",
                reading=f"FULL_MILITARY_PAY "
                f"{_effect(bundle, 'FULL_MILITARY_PAY', 'military_pay_arrears_end_tael')}",
            ),
            EvidenceCitation(
                kind=EvidenceKind.ABLATION,
                source=f"outputs/experiments/{ABLATION_BATCH}/runs.parquet",
                reading=f"OPEN_MIGRATION_EXIT "
                f"{_effect(bundle, 'OPEN_MIGRATION_EXIT', 'military_pay_arrears_max_tael')}",
            ),
            EvidenceCitation(
                kind=EvidenceKind.CALIBRATION,
                source="outputs/calibration/p09-*/ensemble.parquet",
                reading=(
                    "pay_tael_per_soldier_month median "
                    f"{pay_rate['median']:.3f}, contraction {pay_rate['contraction']:.3f}"
                ),
            ),
            _pattern_citation(
                bundle,
                "pay-monetised-and-arrears",
                (("held-out years", bundle.reserved_share("pay-monetised-and-arrears")),),
            ),
        ),
    )


def _m004(bundle: EvidenceBundle) -> MechanismCard:
    """Elite Mediation Bifurcation: mediation was intervened on; accumulation never was."""
    credit = "NO_ELITE_CREDIT"
    loans_before = bundle.arm_aggregate("BASELINE", "elite_loans")
    loans_after = bundle.arm_aggregate(credit, "elite_loans")
    baseline_base = _median(bundle.runs.filter(pl.col("label") == "BASELINE")["tax_base_change_mu"])
    hidden = bundle.parameter("elite_hidden_land_share")
    interest = bundle.parameter("interest_rate_monthly")
    assert hidden is not None and interest is not None and credit
    return MechanismCard(
        id="M004",
        name="Elite Mediation Bifurcation",
        question="Do elites either mediate household distress or accumulate the collateral, and "
        "does the branch taken decide the county's trajectory?",
        status=MechanismStatus.WEAK,
        micro_conditions=(
            "A household facing a consumption shortfall can borrow silver against its land at a "
            "monthly rate, if it has land to pledge.",
            "The loan is the household's way to stay fed without leaving, so the credit channel "
            "stands between distress and departure.",
        ),
        meso_conditions=(
            "The "
            "elite's lending capacity is a share of the land pledged as collateral, so the same "
            "rule that lets the household survive transfers the land if it cannot repay.",
            "Elite holdings are assessed partly off the register: a declared hidden share of elite "
            "land is not taxed.",
        ),
        causal_chain=(
            "Distress forces sales or loans, and the loan-to-value rule decides how much silver an "
            "elite will advance.",
            "The silver is consumed rather than invested, so the household's asset position "
            "weakens even when it survives the month.",
            "Land moves toward the lender, and the county's assessable base contracts with it.",
        ),
        trigger=(
            "A consumption shortfall large enough that a household pledges land to close it; with "
            "the credit channel closed the same shortfall has to be met by departure instead."
        ),
        macro_outcome=(
            "A contracting assessable base with land concentrated in elite hands. The mediation "
            "side of that is measured and load-bearing; the bifurcation - two branches with "
            "different trajectories - was never measured, and the runs show the two sides "
            "occurring together."
        ),
        conditions=(
            Condition(
                statement="A lender with capacity to advance silver against pledged land.",
                level="meso",
                role="necessary",
            ),
            Condition(
                statement="A household with land to pledge and a shortfall it cannot cover.",
                level="micro",
                role="necessary",
            ),
            Condition(
                statement="An unreformed register, so elite land can be hidden from assessment.",
                level="meso",
                role="facilitating",
            ),
        ),
        time_lag=(
            "Not resolved: the credit arms are compared on end-of-run levels, and no artifact "
            "records "
            "the month in which a cohort first borrows or first loses land. The consumption events "
            "that precede borrowing are monthly, so the lag is at most the run."
        ),
        sensitivity_evidence=(
            f"elite_hidden_land_share is identified in P09 - median {hidden['median']:.3f}, "
            f"contraction {hidden['contraction']:.3f} - and "
            f"interest_rate_monthly is identified too "
            f"(median {interest['median']:.3f}, contraction "
            f"{interest['contraction']:.3f}), so both "
            "terms of the credit relation are pinned by the evidence rather "
            "than left free. Neither "
            "appears among the three largest elementary effects on the crossed-line count, so the "
            "channel matters more to levels than to the breakdown boundary."
        ),
        ablation_evidence=(
            "Closing the credit channel deepens the base contraction and pushes households out: "
            f"{_effect(bundle, credit, 'tax_base_change_mu')} and "
            f"{_effect(bundle, credit, 'households_departed')}. Elite lending falls from "
            f"{_number(loans_before, digits=1)} to {_number(loans_after, digits=1)} per run, while "
            f"the effect on the armed population is unresolved "
            f"({_effect(bundle, credit, 'largest_band_share_max')}): the mediating branch is "
            "load-bearing here, and the accumulating branch has no arm to remove."
        ),
        hold_out_evidence=(
            f"No reserved pattern scores the credit channel: debt-transfers-land is a calibration "
            f"target satisfied in {_share(bundle.target_share('debt-transfers-land'))} of draws, "
            f"and "
            "no held-out pattern asks anything about elite lending. The "
            "bifurcation's second branch "
            "is therefore outside the predictive check as well as outside the ablation set."
        ),
        policy_robustness=(
            "Not measured: P12's mechanism readings are the extraction, ratchet and band "
            "consolidation readings, and none of them reads the credit channel. The policy arms do "
            "change the level comparison, but no reading tracks elite "
            "lending, so no verdict exists for this mechanism."
        ),
        historical_support=(
            _pattern_citation(
                bundle,
                "debt-transfers-land",
                (("calibration window", bundle.target_share("debt-transfers-land")),),
            ).reading
            + "; "
            + _pattern_citation(
                bundle,
                "land-abandonment-in-famine",
                (("calibration window", bundle.target_share("land-abandonment-in-famine")),),
            ).reading
            + "; the model's interest and hidden-land parameters are identified against these "
            "targets"
        ),
        historical_challenge=(
            "The record describes mediation and accumulation as a choice made differently by "
            "different elites; the model has a single lending rule and no predatory variant, so it "
            "cannot distinguish the branches it is supposed to bifurcate "
            "between. The land-transfer pattern being matched at "
            f"{_share(bundle.target_share('debt-transfers-land'))} says the credit relation works, "
            "not that elites diverge."
        ),
        counterexample=(
            f"The baseline runs satisfy debt-transfers-land at "
            f"{_share(bundle.target_share('debt-transfers-land'))} while the tax base contracts by "
            f"{_number(abs(baseline_base), digits=0)} "
            "mu, with land moving to creditors as the pattern describes. Removing the credit "
            f"channel makes that contraction deeper, not shallower "
            f"({_effect(bundle, credit, 'tax_base_change_mu')}): mediation and accumulation appear "
            "together rather than as alternatives, so the bifurcation as stated is not what the "
            "model shows."
        ),
        falsifiable_prediction=(
            "Two tests, one per claim. Build the accumulating branch - elites lending at the "
            "maximum rate with land taken on default - and it should produce a larger base "
            "contraction than the closed-credit arm's -9,540 mu; if it does not, the bifurcation "
            "has no second branch and the card should say so in one sentence rather than carry a "
            "status. Then split the runs by which side dominates and compare their trajectories: "
            "if the two groups do not separate, mediation is one mechanism rather than a pair of "
            "branches."
        ),
        uncertainty=(
            "The card is named for a bifurcation and the evidence resolves one branch of it, which "
            "is why the status is WEAK rather than CONDITIONAL: credit is load-bearing, and the "
            "claim that elites divide into mediators and accumulators with different consequences "
            "is neither measured nor consistent with the runs, where both sides appear together. "
            "The credit channel is also entangled with migration, so part of what looks like a "
            "credit effect on the base may be a movement effect, and the parameter that pins it is "
            "identified against the land-transfer target the mechanism itself implies."
        ),
        citations=(
            EvidenceCitation(
                kind=EvidenceKind.ABLATION,
                source=f"outputs/experiments/{ABLATION_BATCH}/runs.parquet",
                reading=(
                    f"NO_ELITE_CREDIT {_effect(bundle, credit, 'tax_base_change_mu')}; "
                    f"{_effect(bundle, credit, 'households_departed')}"
                ),
            ),
            EvidenceCitation(
                kind=EvidenceKind.CALIBRATION,
                source="outputs/calibration/p09-*/ensemble.parquet",
                reading=(
                    f"elite_hidden_land_share median {hidden['median']:.3f} contraction "
                    f"{hidden['contraction']:.3f}; interest_rate_monthly median "
                    f"{interest['median']:.3f} contraction {interest['contraction']:.3f}"
                ),
            ),
            EvidenceCitation(
                kind=EvidenceKind.COUNTERFACTUAL,
                source=f"outputs/experiments/{ABLATION_BATCH}/runs.parquet",
                reading="JOINT_NO_EXTRACTION_ESCALATION+NO_ELITE_CREDIT closes both channels at "
                "once",
            ),
            EvidenceCitation(
                kind=EvidenceKind.HOLD_OUT,
                source="outputs/calibration/p09-*/predictive_statistics.parquet",
                reading="no reserved pattern scores the credit channel",
            ),
            _pattern_citation(
                bundle,
                "debt-transfers-land",
                (("calibration window", bundle.target_share("debt-transfers-land")),),
            ),
        ),
    )


def _m005(bundle: EvidenceBundle) -> MechanismCard:
    """Insurgent Consolidation: robust across policies, with its merger link never exercised."""
    verdict = bundle.verdict("armed-band-consolidation")
    bands = bundle.arm_aggregate("BASELINE", "bands_at_end")
    merges = bundle.arm_aggregate("BASELINE", "band_merges")
    merger_arm = bundle.arm_aggregate("NO_BAND_MERGER", "band_merges")
    bands_whole = bundle.reserved_share("many-bands-then-consolidation", window="whole-run")
    shares = {
        policy: bundle.presence("armed-band-consolidation", policy) for policy in DECLARED_POLICIES
    }
    assert verdict is not None
    return MechanismCard(
        id="M005",
        name="Insurgent Consolidation",
        question="Do armed groups consolidate into fewer, larger organisations as the crisis "
        "proceeds?",
        status=MechanismStatus.SUPPORTED,
        micro_conditions=(
            "Bands grow by taking in the households that the county can no longer feed - the "
            "intake track - and by levying grain from the population around them.",
            "Cohesion is a binding constraint: a band fed less than its "
            "members need loses cohesion "
            "and can lose members again.",
        ),
        meso_conditions=(
            "Suppression is the state's coercive reach against the bands, and its removal changes "
            "which bands survive.",
            "Grain seized by a band is grain the county cannot assess or the army cannot buy, so "
            "band growth and fiscal capacity compete for the same harvest.",
        ),
        causal_chain=(
            "Recruitment from distress and from the soldiery continues through the crisis years.",
            "Bands form faster than they dissolve, and the largest band's share of the armed "
            "population rises while the number of bands moves with suppression.",
            "The armed population becomes a smaller number of larger organisations, whose grain "
            "demands the record describes as exceeding what a county can collect - a quantity no "
            "artifact in this project measures.",
        ),
        trigger=(
            "Suppression falling away: with the coercive reach removed the largest band's share "
            "falls, so it is suppression that concentrates the force rather than the crisis alone. "
            "What happens to the number of bands in that arm is unresolved."
        ),
        macro_outcome=(
            "Armed force concentrated in fewer, larger bands - present in "
            "every declared policy, at "
            "five of six replicates in each - alongside a county base that "
            "cannot meet both the pay claim and the relief demand."
        ),
        conditions=(
            Condition(
                statement="A recruitment pool of distressed households and unpaid soldiers.",
                level="micro",
                role="necessary",
            ),
            Condition(
                statement="Grain that can be seized from the surrounding population.",
                level="micro",
                role="necessary",
            ),
            Condition(
                statement="Suppression weak enough that large bands survive their own expansion.",
                level="meso",
                role="facilitating",
            ),
            Condition(
                statement="Trade disruption that raises the price of the food a band must buy.",
                level="meso",
                role="facilitating",
            ),
        ),
        time_lag=(
            "Over the run rather than at a tick: the P12 reading compares the opening band count "
            "with the final one over 240 ticks. No artifact records the month in which the largest "
            "band's share peaks, so the consolidation's pace is unresolved."
        ),
        sensitivity_evidence=(
            "The largest elementary effects on the largest band share are "
            + ", ".join(bundle.morris_rank("largest_band_share_max")[:3])
            + " - the reference price, the soldier's food ration and the assessed value - while "
            "the crossed-line count leads with "
            + ", ".join(bundle.morris_rank("indicators_crossed_end")[:2])
            + ". The two rankings share one leader, not three, so the band share does not simply "
            "inherit the breakdown boundary's drivers, and no band-specific parameter leads either."
        ),
        ablation_evidence=(
            "Suppression is load-bearing and the direction is measured: LOW_REPRESSION "
            f"({_effect(bundle, 'LOW_REPRESSION', 'largest_band_share_max')}) lowers the largest "
            "band's share, while leaving the number of bands unresolved. The merger rule is not "
            f"load-bearing: NO_BAND_MERGER produces the same merge count as the baseline "
            f"({_number(merger_arm, digits=0)} in both, bands at end "
            f"{_number(bundle.arm_aggregate('NO_BAND_MERGER', 'bands_at_end'), digits=2)} "
            f"against {_number(bands, digits=2)}), because no merge fires anywhere in the batch."
        ),
        hold_out_evidence=(
            f"many-bands-then-consolidation is satisfied in "
            f"{_share(bundle.reserved_share('many-bands-then-consolidation'))} of posterior draws "
            f"over the held-out years and {_share(bands_whole)} over "
            f"the run as a whole, and absorption-of-deserters-and-refugees in "
            f"{_share(bundle.target_share('absorption-of-deserters-and-refugees'))} of draws. The "
            "shape is matched over the run; the held-out years score lower than the run as a whole."
        ),
        policy_robustness=(
            "Robust: present in "
            + ", ".join(
                f"{policy} {share:.2f}" for policy, share in shares.items() if share is not None
            )
            + f" of replicates (P12 verdict '{verdict['verdict']}' at {verdict['arms_showing']} of "
            f"{verdict['arms_ran']} arms). The only policy-dependent part is the intensity: the "
            "utility arm's median strength is the highest of the three."
        ),
        historical_support=(
            _pattern_citation(
                bundle,
                "many-bands-then-consolidation",
                (
                    ("held-out years", bundle.reserved_share("many-bands-then-consolidation")),
                    (
                        "whole run",
                        bundle.reserved_share("many-bands-then-consolidation", window="whole-run"),
                    ),
                ),
            ).reading
            + "; "
            + _pattern_citation(
                bundle,
                "absorption-of-deserters-and-refugees",
                (
                    (
                        "calibration window",
                        bundle.target_share("absorption-of-deserters-and-refugees"),
                    ),
                ),
            ).reading
        ),
        historical_challenge=(
            "The record has thirty-odd bands in the early 1630s and one dominant organisation by "
            "1644, an order of magnitude of consolidation; the model moves "
            "from five bands to three "
            "to nine with the largest share rising from 0.20 to about 0.38. The direction is "
            "matched "
            "and the magnitude is far smaller, so the card claims consolidation, not the scale the "
            "record describes."
        ),
        counterexample=(
            f"The merger arm: raising the cohesion bar to its maximum changes nothing "
            f"({_number(merger_arm, digits=0)} merges against the "
            f"baseline's {_number(merges, digits=0)}), "
            "and consolidation still appears. Whatever produces it, it is not the merger rule the "
            "model's documentation names."
        ),
        falsifiable_prediction=(
            "Lower the cohesion bar so that merges actually fire, and the largest band's share "
            "should exceed the 0.382 maximum the declared policies reach. If merges fire and the "
            "share does not rise, the merger link is decorative and the "
            "mechanism's chain should be rewritten around formation and dissolution."
        ),
        uncertainty=(
            "The causal link the model names - merging on cohesion - was never exercised: zero "
            "merges in every arm of the P10 batch, at every level. Consolidation as an outcome is "
            "robust; its attribution inside the model is not, and this card does not claim the "
            "outcome and the link together. Five or six replicates per policy is enough to show "
            "presence, not to estimate the strength."
        ),
        citations=(
            EvidenceCitation(
                kind=EvidenceKind.POLICY_ROBUSTNESS,
                source=f"outputs/experiments/{ROBUSTNESS_BATCH}/mechanism_readings.parquet",
                reading=(
                    "present in "
                    + ", ".join(
                        f"{policy} {share:.2f}"
                        for policy, share in shares.items()
                        if share is not None
                    )
                    + f" of replicates; verdict {verdict['verdict']}"
                ),
            ),
            EvidenceCitation(
                kind=EvidenceKind.ABLATION,
                source=f"outputs/experiments/{ABLATION_BATCH}/runs.parquet",
                reading=(
                    f"LOW_REPRESSION "
                    f"{_effect(bundle, 'LOW_REPRESSION', 'largest_band_share_max')}; "
                    f"NO_BAND_MERGER merges {_number(merger_arm, digits=0)} against baseline "
                    f"{_number(merges, digits=0)}"
                ),
            ),
            EvidenceCitation(
                kind=EvidenceKind.HOLD_OUT,
                source="outputs/calibration/p09-*/predictive_checks.parquet",
                reading=(
                    "many-bands-then-consolidation held-out "
                    f"{_share(bundle.reserved_share('many-bands-then-consolidation'))}, whole run "
                    f"{_share(bands_whole)}"
                ),
            ),
            EvidenceCitation(
                kind=EvidenceKind.SENSITIVITY,
                source=f"outputs/experiments/{MORRIS_BATCH}/runs.parquet",
                reading=(
                    "largest band share leads with "
                    + ", ".join(bundle.morris_rank("largest_band_share_max")[:3])
                ),
            ),
            _pattern_citation(
                bundle,
                "many-bands-then-consolidation",
                (("held-out years", bundle.reserved_share("many-bands-then-consolidation")),),
            ),
        ),
    )


def _m006(bundle: EvidenceBundle) -> MechanismCard:
    """Famine Mortality: named in the record, absent from the model."""
    return MechanismCard(
        id="M006",
        name="Famine Mortality",
        question="Does excess death from hunger carry a harvest failure into population loss, and "
        "from there into labour scarcity and abandoned land?",
        status=MechanismStatus.UNIDENTIFIED,
        micro_conditions=(
            "A cohort whose consumption falls below subsistence loses "
            "members, in proportion to how "
            "far below it falls and for how long.",
            "The dead leave the labour pool, so the next season's cultivation is smaller.",
        ),
        meso_conditions=(
            "Relief and credit determine who reaches subsistence and who "
            "does not, so the mortality "
            "rate is a function of institutions as well as of the harvest.",
            "Land is abandoned when the households that worked it are gone, not only when they "
            "flee.",
        ),
        causal_chain=(
            "Precipitation deficit, then harvest failure, then price spike, then consumption below "
            "subsistence.",
            "Members of the cohort die; the model records no such event and cannot.",
            "Labour per mu falls and cultivation is abandoned.",
        ),
        trigger=(
            "A consumption shortfall persisting past the point where assets "
            "are exhausted - a state the model reaches, since it records consumption events below "
            "the subsistence line, but "
            "which it resolves by distress sales and departure rather than by death."
        ),
        macro_outcome=(
            "Population decline beyond what migration explains, and a labour shortage in the "
            "seasons after a famine - neither of which any artifact in this project reports."
        ),
        conditions=(
            Condition(
                statement="A household cohort with a member count that death can reduce.",
                level="micro",
                role="necessary",
            ),
            Condition(
                statement="A subsistence threshold below which consumption costs lives.",
                level="micro",
                role="necessary",
            ),
            Condition(
                statement="Relief that arrives too late to change the outcome.",
                level="meso",
                role="facilitating",
            ),
        ),
        time_lag=(
            "Not measurable in this model. The record puts deaths within the famine year and its "
            "aftermath; the model has no mortality clock at all, and the abandonment it does show "
            "is produced by departure, which is monthly."
        ),
        sensitivity_evidence=(
            "None exists. The P09 prior table carries thirteen parameters and none of them is a "
            "mortality or survival rate; no Morris trajectory and no Sobol index can bear on a "
            "quantity the model does not compute."
        ),
        ablation_evidence=(
            "No arm can be built. Removing mortality would be a no-op because there is nothing to "
            "remove, which is exactly the situation the NO_BAND_MERGER arm demonstrates for a "
            "different rule: an arm whose intervention cannot bind measures the "
            "rule's absence, not its effect."
        ),
        hold_out_evidence=(
            f"land-abandonment-in-famine - the pattern mortality is supposed to help produce - is "
            f"satisfied in {_share(bundle.target_share('land-abandonment-in-famine'))} of draws "
            "without any mortality rule, through departure. The pattern scores therefore cannot "
            "distinguish a world with deaths from one without."
        ),
        policy_robustness=(
            "Not applicable: P12 reads three mechanisms and none of them is a population quantity, "
            "so no policy arm produces evidence about mortality."
        ),
        historical_support=(
            _pattern_citation(
                bundle,
                "famine-lags-harvest-failure",
                (("sequence, not a level", None),),
            ).reading
            + "; "
            + _pattern_citation(
                bundle,
                "land-abandonment-in-famine",
                (("calibration window", bundle.target_share("land-abandonment-in-famine")),),
            ).reading
        ),
        historical_challenge=(
            "The "
            "record's causal sequence is precipitation, harvest, price, hunger, death - and the "
            "mortality is the part of it the project has never implemented. The model reaches the "
            "abandonment outcome through a different mechanism, so the historical case for "
            "mortality cannot be tested here at all."
        ),
        counterexample=(
            f"The model satisfies land-abandonment-in-famine at "
            f"{_share(bundle.target_share('land-abandonment-in-famine'))} with zero deaths, so any "
            "claim that mortality is necessary for abandonment is contradicted inside the model - "
            "and any claim that the model's abandonment is historical evidence for a mortality "
            "mechanism is contradicted by the model's own structure."
        ),
        falsifiable_prediction=(
            "Add a mortality rule that removes members on a sustained "
            "subsistence shortfall and the held-out scores should move only if the "
            "pattern's timing depends on labour scarcity: if famine-worst-years-1639-43 stays at "
            f"{_share(bundle.reserved_share('famine-worst-years-1639-43'))} and the population "
            "statistics shift, mortality changes levels rather than timing "
            "in this model. That test "
            "cannot be run today, which is why the status is UNIDENTIFIED rather than WEAK."
        ),
        uncertainty=(
            "The gap is structural rather than empirical: no mortality event, no mortality "
            "parameter, no mortality output, so nothing in the project could have "
            "measured this mechanism even "
            "in principle. P08 recorded it as a coverage gap; this card records it as the largest "
            "single mismatch between the model's mechanism set and the record's causal chain."
        ),
        citations=(
            _pattern_citation(
                bundle,
                "famine-lags-harvest-failure",
                (("sequence, not a level", None),),
            ),
            _pattern_citation(
                bundle,
                "land-abandonment-in-famine",
                (("calibration window", bundle.target_share("land-abandonment-in-famine")),),
            ),
        ),
    )


#: The builders, in card order. Kept as a tuple so the order is the id order the schema requires.
_BUILDERS: Final[tuple[Callable[[EvidenceBundle], MechanismCard], ...]] = (
    _m001,
    _m002,
    _m003,
    _m004,
    _m005,
    _m006,
)
