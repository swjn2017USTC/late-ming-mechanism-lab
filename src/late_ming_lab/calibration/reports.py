"""The calibration reports: what was frozen, what the posterior says, and where the model fails.

Four documents, each generated from the batch artifact rather than written by hand:

```text
docs/calibration/objective.md    the frozen registry, the bounds, the checks, the tolerance
docs/calibration/posterior.md    identifiability, equifinality, and the target patterns
docs/calibration/mismatch.md     the checks the model cannot satisfy in the window it was fitted to
docs/calibration/prediction.md   the reserved windows: what was predicted, and where it failed
```

Every table is computed from files on disk — the ensemble's draws, the predictive tables, the P08
cards and patterns — so a reader can regenerate the report and check it against the artifact.
Nothing here recomputes a statistic from a live model, and nothing here fits anything: the reports
are the phase's own description of what happened, including the parts that did not work.

The magnitude note in ``mismatch.md`` is the one place a historical number is printed beside a model
number. It is printed to be seen, not to be matched: P08 recorded the 1631 Shangzhou price and the
model's ceiling, and the report states the gap rather than closing it by tuning.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Final

import polars as pl

from late_ming_lab.calibration.ensemble import Ensemble
from late_ming_lab.calibration.freeze import frozen_file_digests
from late_ming_lab.calibration.prediction import (
    CHECKS as PREDICTION_CHECKS,
)
from late_ming_lab.calibration.prediction import UNCHECKED, PosteriorPredictive
from late_ming_lab.calibration.priors import (
    PriorTable,
    card_free_parameters,
    centres_outside_range,
    excluded_parameters,
)
from late_ming_lab.calibration.summary_stats import scalar
from late_ming_lab.calibration.targets import CHECKS, Objective
from late_ming_lab.calibration.windows import WHOLE_RUN_WINDOW, WINDOWS
from late_ming_lab.evidence.cards import ParameterCards
from late_ming_lab.evidence.ledger import CalibrationRole, PatternRegistry

#: The card whose recorded magnitude the report compares against the gazetteer, and the recorded
#: value it is compared with. Both are named so a reader can find them; neither is used in a fit.
PRICE_CARD_ID: Final[str] = "reference_price_tael_per_shi"
RECORDED_PRICE_TAEL_PER_SHI: Final[float] = 40.0

#: A check is reported as *systematically unsatisfied* when this share of the posterior draws fail
#: it. Half is the natural line: the ensemble agrees with the check's negation more often than not.
SYSTEMATIC_FAILURE_SHARE: Final[float] = 0.5


@dataclass(frozen=True, slots=True)
class CalibrationReportInputs:
    """Everything the four reports are generated from."""

    root: Path
    cards: ParameterCards
    patterns: PatternRegistry
    priors: PriorTable
    objective: Objective
    ensemble: Ensemble
    predictive: PosteriorPredictive
    diagnostics: dict[str, object] | None = None
    #: A second batch at the same settings and a different sampler seed, when one was run. The
    #: stability report is written only from it, because a single batch cannot show whether its own
    #: narrow marginals are information or a resampling collapse.
    comparison: Ensemble | None = None


def objective_report(inputs: CalibrationReportInputs) -> str:
    """The frozen registry, the declared bounds, the declared checks and the sampler's settings."""
    lines: list[str] = [
        "# P09 objective: what was frozen before anything was fitted",
        "",
        "Generated from the registry, the cards and the ensemble's manifest. Every bound below is",
        "the range a P08 parameter card already declared; nothing here widened or narrowed one.",
        "",
        "## Windows",
        "",
        "| role | ticks | calendar | months | note |",
        "| --- | --- | --- | --- | --- |",
    ]
    for window in WINDOWS:
        lines.append(
            f"| `{window.role.value}` | {window.first_tick}-{window.last_tick} | {window.calendar} "
            f"| {window.tick_count} | {window.note} |"
        )
    lines += [
        f"| `{WHOLE_RUN_WINDOW.role.value}` | {WHOLE_RUN_WINDOW.first_tick}-"
        f"{WHOLE_RUN_WINDOW.last_tick} | {WHOLE_RUN_WINDOW.calendar} | "
        f"{WHOLE_RUN_WINDOW.tick_count} | {WHOLE_RUN_WINDOW.note} |",
        "",
        "## The frozen registry",
        "",
        f"Ensemble batch: `{inputs.ensemble.provenance.batch_id}`  ",
        f"Evidence digest: `{inputs.ensemble.provenance.evidence_digest}`  ",
        f"Pattern schema: `{inputs.patterns.schema_version}`  ",
        f"Prior digest: `{inputs.ensemble.provenance.prior_digest}`  ",
        f"Objective digest: `{inputs.ensemble.provenance.objective_digest}`  ",
        f"Configuration hash: `{inputs.ensemble.provenance.simulation_config_hash}`  ",
        f"Root seed: `{inputs.ensemble.provenance.root_seed}`  ",
        "",
        "| file | digest |",
        "| --- | --- |",
    ]
    for name, digest in frozen_file_digests(inputs.root):
        lines.append(f"| `{name}` | `{digest[:16]}` |")

    lines += [
        "",
        "## The calibrated parameters",
        "",
        "A parameter is calibrated when its card declares a numeric range, the field is a scalar",
        "the sandbox accepts, the card marks it a sensitivity priority, and at least one target",
        "check reaches its mechanism. The support is the card range, unadjusted.",
        "",
        "| parameter | set | range | central | class | grade | why this parameter |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for prior in inputs.priors:
        central = "—" if prior.central is None else f"{prior.central:g}"
        lines.append(
            f"| `{prior.name}` | {prior.parameter_set} | [{prior.low:g}, {prior.high:g}] "
            f"| {central} | {prior.support_class} | {prior.evidence_grade} | {prior.reason} |"
        )

    lines += [
        "",
        "### Range-carrying cards deliberately not calibrated",
        "",
        "| parameter | why not |",
        "| --- | --- |",
    ]
    for name, reason in excluded_parameters(inputs.cards):
        lines.append(f"| `{name}` | {reason} |")

    outside = centres_outside_range(inputs.cards)
    lines += [
        "",
        "### Recorded inconsistencies found in the registry",
        "",
        f"- Parameters whose card records a value in use outside its own range: {len(outside)}.",
    ]
    for name, note in outside:
        lines.append(
            f"  - `{name}`: {note}. The prior is the range, so this default lies outside the "
            "calibration support; the report says so instead of widening the band."
        )
    lines.append(
        f"- Cards with no range at all (not calibratable here): "
        f"{len(card_free_parameters(inputs.cards))}."
    )

    lines += [
        "",
        "## The target checks",
        "",
        "Each check reads a statistic or a pair of series and quotes the P08 signature whose",
        "wording fixes the comparison. A pattern's score is the share of its checks that failed.",
        "",
        "| pattern | check | kind | reads | question |",
        "| --- | --- | --- | --- | --- |",
    ]
    for check in CHECKS:
        partner = "" if check.against is None else f" vs {check.against}"
        reads = f"{check.statistic}{partner}"
        lines.append(
            f"| `{check.pattern_id}` | `{check.check_id}` | {check.kind.value} | `{reads}` "
            f"| {check.question} |"
        )

    lines += [
        "",
        "### The record's wording, per target pattern",
        "",
    ]
    for pattern_id in inputs.objective.pattern_ids:
        pattern = inputs.patterns.require(pattern_id)
        lines += [
            f"**`{pattern_id}`** — {pattern.name} ({pattern.evidence_grade} evidence, window "
            f"{pattern.window}, {pattern.geography})",
            "",
            f"> {pattern.statement}",
            "",
        ]
        for signature in pattern.signatures:
            lines += [
                f"- quantity: {signature.quantity}",
                f"  - the record shows: {signature.expected}",
                f"  - how to score it: {signature.scoring}",
            ]
        for falsifier in pattern.falsifiers:
            lines.append(f"- would count against the model: {falsifier}")
        lines.append("")

    provenance = inputs.ensemble.provenance
    lines += [
        "## Sampler settings",
        "",
        f"- particles: {provenance.particles}, chains: {provenance.chains}, "
        f"seed: {provenance.sampler_seed}",
        f"- Laplace tolerance per pattern: {provenance.tolerance:g} "
        "(a score is the share of a pattern's checks that failed; the target patterns carry two "
        "or three checks each, so this allows about one failed check before the kernel discounts)",
        f"- hold-out patterns reserved and never scored here: {len(provenance.hold_out_ids)} "
        f"(`{'`, `'.join(provenance.hold_out_ids)}`)",
        f"- PyMC {provenance.pymc_version}, ArviZ {provenance.arviz_version}, "
        f"engine {provenance.engine_version}",
    ]
    if inputs.diagnostics is not None:
        lines.append(
            f"- stages: {inputs.diagnostics.get('stages')}, accept rates: "
            f"{inputs.diagnostics.get('accept_rate')}, distinct draws simulated: "
            f"{inputs.diagnostics.get('distinct_draws')}"
        )
    lines.append("")
    return "\n".join(lines)


def posterior_report(inputs: CalibrationReportInputs) -> str:
    """Identifiability, equifinality and the target patterns' distance vectors."""
    ensemble = inputs.ensemble
    verdicts = ensemble.verdicts(inputs.priors)
    lines: list[str] = [
        "# P09 posterior: what the ensemble identifies, and what it cannot separate",
        "",
        f"Batch `{ensemble.provenance.batch_id}`: {len(ensemble.draws)} draws, "
        f"{ensemble.provenance.particles} particles, {ensemble.provenance.chains} chain(s).",
        "",
        "The verdicts follow the declared rules: the posterior interquartile range is compared",
        "with the prior's full range, at most half counts as *identified*, at least four fifths as",
        "*unresolved*, and the band between as *weak*; two parameters correlating at least 0.7 in",
        "absolute value are reported as a trade-off.",
        "",
        "## Identifiability",
        "",
        "| parameter | prior | posterior q1 | median | q3 | contraction | verdict |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for verdict in verdicts:
        lines.append(
            f"| `{verdict.name}` | [{verdict.prior_low:g}, {verdict.prior_high:g}] "
            f"| {verdict.posterior_q1:g} | {verdict.posterior_median:g} "
            f"| {verdict.posterior_q3:g} | {verdict.contraction:.3f} | {verdict.verdict.value} |"
        )
    counts: dict[str, int] = {}
    for verdict in verdicts:
        counts[verdict.verdict.value] = counts.get(verdict.verdict.value, 0) + 1
    lines += [
        "",
        "Counts: " + ", ".join(f"{name} {count}" for name, count in sorted(counts.items())) + ".",
        "",
        "## Equifinality",
        "",
    ]
    trades = ensemble.trade_offs(inputs.priors)
    if trades:
        lines += [
            "| left | right | weighted correlation |",
            "| --- | --- | --- |",
        ]
        for trade in trades:
            lines.append(f"| `{trade.left}` | `{trade.right}` | {trade.correlation:+.3f} |")
        lines.append(
            "A pair above the declared line means the calibration window cannot separate them: a "
            "draw that raises one and lowers the other scores the same, so neither may be read as "
            "an estimate on its own."
        )
    else:
        lines.append(
            "No pair reaches the declared 0.7 line at this batch size, so no trade-off is "
            "reported. That is a statement about this ensemble, not a claim that the parameters "
            "are separable in the model."
        )

    lines += [
        "",
        f"Distinct parameter vectors in the particle set: {ensemble.distinct_parameter_vectors()} "
        f"of {len(ensemble.draws)}. Fewer distinct vectors than particles means the sampler "
        "resampled copies; the weighted distribution is unchanged by the copies, but a reader "
        "should not read a count of rows as a count of independent draws.",
        "",
        "## The target patterns across the ensemble",
        "",
        "| pattern | draws fully consistent | mean score | worst score |",
        "| --- | --- | --- | --- |",
    ]
    for pattern_verdict in ensemble.pattern_verdicts():
        lines.append(
            f"| `{pattern_verdict.pattern_id}` | {pattern_verdict.consistent_share:.2f} "
            f"| {pattern_verdict.mean_score:.3f} | {pattern_verdict.worst_score:.3f} |"
        )
    lines.append("")
    return "\n".join(lines)


def stability_report(inputs: CalibrationReportInputs) -> str:
    """The same experiment under two sampler seeds: whether the ensemble's location reproduces.

    This is the phase's check on its own identifiability table. SMC resamples, and a particle cloud
    can collapse around a few ancestors while each marginal looks narrow; the fix is not a wider
    prior but a second, differently seeded run. A parameter whose median moves by a large share of
    its prior range between the two was not pinned by the calibration window, whatever the first
    batch's interquartile range said.
    """
    if inputs.comparison is None:
        raise ValueError("the stability report needs a second batch to compare against")
    comparisons = inputs.ensemble.compare_with(inputs.comparison, inputs.priors)
    lines: list[str] = [
        "# P09 stability: the same experiment, two sampler seeds",
        "",
        f"Batch A `{inputs.ensemble.provenance.batch_id}` "
        f"({len(inputs.ensemble.draws)} particles, seed {inputs.ensemble.provenance.sampler_seed}, "
        f"{inputs.ensemble.distinct_parameter_vectors()} distinct parameter vectors) against "
        f"batch B `{inputs.comparison.provenance.batch_id}` "
        f"({len(inputs.comparison.draws)} particles, "
        f"seed {inputs.comparison.provenance.sampler_seed}, "
        f"{inputs.comparison.distinct_parameter_vectors()} distinct parameter vectors).",
        "",
        "Both batches run the same priors, the same objective, the same scenario and the same",
        "root seed for the sandbox — they differ only in the sampler's random seed. The declared",
        "rule: a parameter is *reproducible* when the two medians differ by less than a quarter of",
        "its prior range. A parameter that fails that test is reported as unpinned regardless of",
        "how narrow its marginal is in either batch.",
        "",
        "| parameter | prior | A median | B median | shift (share of range) | verdict |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for comparison in comparisons:
        verdict = "reproducible" if comparison.reproducible else "unpinned"
        lines.append(
            f"| `{comparison.name}` | [{comparison.prior_low:g}, {comparison.prior_high:g}] "
            f"| {comparison.first_median:g} | {comparison.second_median:g} "
            f"| {comparison.shift:.3f} | {verdict} |"
        )
    stable = sum(1 for comparison in comparisons if comparison.reproducible)
    lines += [
        "",
        f"Reproducible in {stable} of {len(comparisons)} parameters.",
        "",
    ]
    unpinned = [comparison for comparison in comparisons if not comparison.reproducible]
    if unpinned:
        lines += [
            "Unpinned parameters, with the two batches' locations for a reader to judge:",
            "",
        ]
        for comparison in sorted(unpinned, key=lambda item: item.shift, reverse=True):
            lines.append(
                f"- `{comparison.name}`: {comparison.first_median:g} against "
                f"{comparison.second_median:g}, a shift of {comparison.shift:.3f} of the range "
                f"[{comparison.prior_low:g}, {comparison.prior_high:g}]."
            )
    else:
        lines.append(
            "Every parameter's location reproduces across the two seeds, which is the minimum a "
            "batch has to pass before its own marginals are worth reading."
        )
    lines += [
        "",
        "## What this does and does not establish",
        "",
        "- It does establish that the ensemble's *location* is a property of the objective and the",
        "  prior rather than of one sampling run.",
        "- It does not establish that the calibration window identifies these parameters",
        "  individually: the equifinality table in `posterior.md` shows which pairs trade off, and",
        "  a reproducible ridge is still a ridge.",
        "- Two seeds are the cheapest version of this check, not a convergence study. A third seed",
        "  would strengthen it, and a regional-scale batch would test whether it holds beyond the",
        "  toy fixture.",
        "",
    ]
    return "\n".join(lines)


def mismatch_report(inputs: CalibrationReportInputs) -> str:
    """Which checks the model cannot satisfy in the window it was calibrated on."""
    checks = inputs.predictive.checks.filter(pl.col("window") == "calibration")
    totals = _check_totals(checks)
    lines: list[str] = [
        "# P09 mismatch: the checks the model does not satisfy",
        "",
        "Read from the posterior predictive runs, in the calibration window — the window the",
        "objective scored. A check whose failure share is at or above "
        f"{SYSTEMATIC_FAILURE_SHARE:g} is called systematically unsatisfied: the ensemble's own",
        "runs contradict it more often than not, at every draw inside the declared bounds.",
        "",
        "| pattern | check | satisfied share | median value |",
        "| --- | --- | --- | --- |",
    ]
    for row in totals:
        lines.append(
            f"| `{row['pattern_id']}` | `{row['check_id']}` | {row['satisfied_share']:.2f} "
            f"| {row['median_value']:.4f} |"
        )

    failing_patterns = sorted(
        {
            str(row["pattern_id"])
            for row in totals
            if scalar(row["satisfied_share"]) < SYSTEMATIC_FAILURE_SHARE
        }
    )
    lines += [
        "",
        "## Patterns the model cannot match, and what would count against it",
        "",
    ]
    if not failing_patterns:
        lines.append(
            "No target pattern is contradicted by most draws in the calibration window at this "
            "batch size."
        )
    for pattern_id in failing_patterns:
        pattern = inputs.patterns.require(pattern_id)
        broken = [
            str(row["check_id"])
            for row in totals
            if row["pattern_id"] == pattern_id
            and scalar(row["satisfied_share"]) < SYSTEMATIC_FAILURE_SHARE
        ]
        lines += [
            f"**`{pattern_id}`** — checks systematically unsatisfied: "
            f"{', '.join(f'`{check}`' for check in broken)}.",
            "",
            f"> {pattern.statement}",
            "",
        ]
        for falsifier in pattern.falsifiers:
            lines.append(f"- the record's own falsifier: {falsifier}")
        lines.append("")

    lines += [
        "## The one place a historical magnitude is printed",
        "",
        "P08 recorded a local famine price that the model's ceiling does not reach. That gap is a",
        "known limitation of the mechanism, recorded here rather than closed by calibration:",
        "",
    ]
    card = inputs.cards.require("MarketParameters", PRICE_CARD_ID)
    upper = None if card.range is None else card.range.high
    lines += [
        f"- recorded: the 1631 Shangzhou price, 4 tael per dou, i.e. "
        f"{RECORDED_PRICE_TAEL_PER_SHI:g} tael per shi (`famine-local-price-extremes`).",
        f"- the card `{PRICE_CARD_ID}` declares a band up to {upper:g} tael per shi, and the model "
        "cannot post more than its ceiling allows.",
        "- consequence: a famine-price comparison can test direction and timing, never magnitude, "
        "until the mechanism is revisited on evidence.",
        "",
    ]
    return "\n".join(lines)


def prediction_report(inputs: CalibrationReportInputs) -> str:
    """What the ensemble predicts in the reserved windows, and where it fails."""
    checks = inputs.predictive.checks.filter(pl.col("window") != "calibration")
    totals = _check_totals(checks, group=("window",))
    statistics = inputs.predictive.statistics
    provenance = inputs.ensemble.provenance
    lines: list[str] = [
        "# P09 prediction: the reserved windows, scored after the ensemble was frozen",
        "",
        f"The {len(provenance.hold_out_ids)} patterns P08 marked `hold-out` were never part of the",
        "objective. The objective refuses any window but the calibration window and the predictive",
        "checks refuse the calibration window, so the two surfaces are disjoint by construction",
        "and a test asserts it both ways. Everything below is read from runs made afterwards.",
        "",
        "| window | ticks | role in the split |",
        "| --- | --- | --- |",
    ]
    for window in (WHOLE_RUN_WINDOW, *WINDOWS):
        lines.append(
            f"| `{window.role.value}` | {window.first_tick}-{window.last_tick} | {window.note} |"
        )

    lines += [
        "",
        "## Reserved patterns, by window",
        "",
        "| window | pattern | check | satisfied share | median value |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in totals:
        lines.append(
            f"| `{row['window']}` | `{row['pattern_id']}` | `{row['check_id']}` "
            f"| {row['satisfied_share']:.2f} | {row['median_value']:.4f} |"
        )

    whole_run = [row for row in totals if row["window"] == "whole-run"]
    failed = sorted(
        {
            str(row["pattern_id"])
            for row in whole_run
            if scalar(row["satisfied_share"]) < SYSTEMATIC_FAILURE_SHARE
        }
    )
    lines += [
        "",
        "## Reserved claims the ensemble contradicts over the whole run",
        "",
    ]
    if not failed:
        lines.append("No reserved pattern is contradicted over the whole run at this batch size.")
    for pattern_id in failed:
        pattern = inputs.patterns.require(pattern_id)
        broken = [
            str(row["check_id"])
            for row in whole_run
            if row["pattern_id"] == pattern_id
            and scalar(row["satisfied_share"]) < SYSTEMATIC_FAILURE_SHARE
        ]
        lines += [
            f"**`{pattern_id}`** — {pattern.name}. Checks failing in most draws: "
            f"{', '.join(f'`{check}`' for check in broken)}.",
            "",
            f"- the record: {pattern.statement}",
        ]
        for signature in pattern.signatures:
            lines.append(f"- the record shows: {signature.expected}")
        for falsifier in pattern.falsifiers:
            lines.append(f"- the record's own falsifier: {falsifier}")
        lines.append("")

    lines += [
        "## Where the ensemble lands, in the hold-out window",
        "",
        "| statistic | hold-out median | hold-out q1 | hold-out q3 | calibration median |",
        "| --- | --- | --- | --- | --- |",
    ]
    for column in _interval_columns(statistics):
        hold = statistics.filter(pl.col("window") == "hold-out")[column]
        calibration = statistics.filter(pl.col("window") == "calibration")[column]
        lines.append(
            f"| `{column}` | {scalar(hold.median()):.4f} | {scalar(hold.quantile(0.25)):.4f} "
            f"| {scalar(hold.quantile(0.75)):.4f} | {scalar(calibration.median()):.4f} |"
        )

    lines += [
        "",
        "## Patterns this scale cannot check",
        "",
    ]
    if UNCHECKED:
        for pattern_id, reason in UNCHECKED:
            lines.append(f"- `{pattern_id}`: {reason}")
    else:
        lines.append(
            "None: every reserved pattern has at least one check that reads a quantity this model "
            "reports. Where a check's quantity is only available per node or per band, the check "
            "reads the run-level aggregate and the report says so in the check's question."
        )
    lines.append("")
    return "\n".join(lines)


def _check_totals(checks: pl.DataFrame, *, group: tuple[str, ...] = ()) -> list[dict[str, object]]:
    """Per check: how often the posterior draws satisfy it, and the median measured value."""
    if checks.is_empty():
        return []
    keys = [*group, "pattern_id", "check_id"]
    aggregated = checks.group_by(keys).agg(
        [
            pl.col("satisfied").cast(pl.Float64).mean().alias("satisfied_share"),
            pl.col("value").median().alias("median_value"),
        ]
    )
    return aggregated.sort(keys).to_dicts()


def _interval_columns(statistics: pl.DataFrame) -> tuple[str, ...]:
    """The statistic columns of the predictive table, in their declared order."""
    reserved = {"draw", "window"}
    return tuple(column for column in statistics.columns if column not in reserved)


def checked_pattern_ids() -> tuple[str, ...]:
    """Every pattern the prediction path scores, so a report can state its coverage."""
    return tuple(sorted({check.pattern_id for check in PREDICTION_CHECKS}))


def predictive_coverage(registry: PatternRegistry) -> tuple[int, int]:
    """How many reserved patterns are checked, and how many are reserved in total."""
    reserved = tuple(pattern.id for pattern in registry.by_role(CalibrationRole.HOLD_OUT))
    return len(checked_pattern_ids()), len(reserved)


def write_reports(inputs: CalibrationReportInputs, directory: str | Path) -> tuple[Path, ...]:
    """Write the four reports into a directory and return the paths."""
    target = Path(directory)
    target.mkdir(parents=True, exist_ok=True)
    documents: list[tuple[str, str]] = [
        ("objective.md", objective_report(inputs)),
        ("posterior.md", posterior_report(inputs)),
        ("mismatch.md", mismatch_report(inputs)),
        ("prediction.md", prediction_report(inputs)),
    ]
    if inputs.comparison is not None:
        documents.append(("stability.md", stability_report(inputs)))
    written: list[Path] = []
    for name, text in documents:
        path = target / name
        path.write_text(text, encoding="utf-8")
        written.append(path)
    return tuple(written)
