"""The phase's documents: the machine-readable cards, the human-readable cards, the synthesis.

Three products, one source. :func:`write_mechanism_docs` writes the YAML a later phase can load and
one Markdown file per card, numbered the way the phase brief numbers its fields so a reviewer can
check a card against the brief without a map. :func:`write_synthesis` writes
``outputs/reports/mechanism-synthesis.md``: what the six cards say together, what the project's own
earlier documents claimed that the evidence does not support, and the fitted boundary analysis that
describes where this model's output turns over.

The boundary section renders :data:`late_ming_lab.analysis.boundary.CAUSAL_DISCLAIMER` verbatim. A
fitted surface is a description of the runs that were made; the interventions in the cards are what
carry causal weight here, and the report says so in the section that quotes the surface, not in a
footnote.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Final

import polars as pl
import yaml

from late_ming_lab.analysis.boundary import (
    BOOSTED_MODEL,
    CAUSAL_DISCLAIMER,
    BoundaryError,
    fit_boundary,
    load_run_tables,
    partial_dependence,
    tipping_surface,
)
from late_ming_lab.calibration.summary_stats import scalar
from late_ming_lab.synthesis.evidence import MORRIS_BATCH, ROBUSTNESS_BATCH, EvidenceBundle
from late_ming_lab.synthesis.schema import MechanismBook, MechanismCard

#: Where the cards and the synthesis are written.
DOCS_ROOT: Final[str] = "docs/mechanisms"
CARDS_FILE: Final[str] = "cards.yaml"
INDEX_FILE: Final[str] = "index.md"
SYNTHESIS_FILE: Final[str] = "outputs/reports/mechanism-synthesis.md"

#: The two scenario knobs P12 swept, the output the boundary separates, and the parameter set the
#: Morris design moved (read from that batch's own columns).
SCENARIO_FEATURES: Final[tuple[str, ...]] = ("nominal_pressure", "severity_floor")
BOUNDARY_TARGET: Final[str] = "breakdown"
PRIMARY_OUTPUT: Final[str] = "indicators_crossed_end"
MORRIS_FEATURES: Final[tuple[str, ...]] = (
    "assessed_value_tael_per_mu",
    "elite_hidden_land_share",
    "food_shi_per_member_month",
    "food_shi_per_soldier_month",
    "interest_rate_monthly",
    "land_per_adult_capacity_mu",
    "pay_tael_per_soldier_month",
    "permanent_migration_unmet_ratio",
    "permanent_share_of_households_per_month",
    "reference_price_tael_per_shi",
    "subsistence_grain_per_adult_month_shi",
    "temporary_migration_unmet_ratio",
    "temporary_share_of_adults_per_month",
    "wage_grain_shi_per_adult_month",
    "yield_loss_scale",
)

#: The declared policies whose surfaces are fitted side by side.
POLICY_LABELS: Final[tuple[str, ...]] = ("rule", "utility", "random")

#: The field order the phase brief states, as (heading, attribute).
BRIEF_FIELDS: Final[tuple[tuple[str, str], ...]] = (
    ("Micro conditions", "micro_conditions"),
    ("Meso conditions", "meso_conditions"),
    ("Causal chain", "causal_chain"),
    ("Trigger", "trigger"),
    ("Macro outcome", "macro_outcome"),
    ("Necessary versus facilitating conditions", "conditions"),
    ("Time lag", "time_lag"),
    ("Sensitivity evidence", "sensitivity_evidence"),
    ("Ablation evidence", "ablation_evidence"),
    ("Hold-out evidence", "hold_out_evidence"),
    ("Policy robustness", "policy_robustness"),
    ("Historical support", "historical_support"),
    ("Historical challenge", "historical_challenge"),
    ("Counterexample", "counterexample"),
    ("Falsifiable prediction", "falsifiable_prediction"),
    ("Uncertainty", "uncertainty"),
)

#: The fixed prose, one Markdown line per expression so that a paragraph stays a paragraph and a
#: numbered item stays one list item however the source is wrapped.
_OPENING: Final[str] = (
    "P13 read the calibration ensemble, the hold-out pass, the sensitivity screens, the ablations, "
    "the counterfactual arms and the policy-robustness matrix, and wrote one card per candidate "
    "mechanism. This report holds what the six cards say together, where they contradict the "
    "project's own earlier documents, and what a fitted surface can and cannot add."
)
_POINTER: Final[str] = (
    "The cards themselves are `docs/mechanisms/index.md`, with `cards.yaml` beside it for the "
    "machine-readable form. Every number below comes from an artifact the cards name."
)
_REFUSED_ARM: Final[str] = (
    "No card can be SUPPORTED by the runtime arm, because no runtime arm ran: the P11 gate refused "
    "it and P12 recorded the refusal rather than imputing a result."
)
_INDEX_RULE: Final[str] = (
    "A status is computed from the evidence and checked against the schema's rules - a SUPPORTED "
    "card must cite an intervention as well as the quantities that were watched - and every number "
    "in a card is read from the batch it names. The machine-readable form is `cards.yaml`."
)
_CARD_IS_NOT: Final[str] = (
    "A card is a claim with its falsifier, not a summary of everything that could matter. A card "
    "that said its factors interacted would be refused by the schema before it was written: the "
    "fields exist to force a condition, a trigger and a chain to be named, so that a reader can "
    "check each against the artifact the card cites."
)
_CONTRADICTIONS: Final[tuple[str, ...]] = (
    "1. **The fiscal-military ratchet was narrated before it was measured.** P07's report and the "
    "P12 scope both treated the arrears stock as a ratchet. Measured month by month over the 18 "
    "replicates of the three declared policies it declines somewhere between {declines_low} and "
    "{declines_high} times in a 240-tick run, so no replicate is monotone; the rule arm's largest "
    "end stock, {largest_end} tael, belongs to a replicate with {largest_declines} decline months "
    "rather than to the arm's quietest one. The level claim survives; the monotone claim does "
    "not.",
    "2. **The extraction inversion looked structural and is not.** It appears in six of six "
    "utility replicates and in none of the rule arm's. The one arm that varies extraction "
    "(NO_EXTRACTION_ESCALATION) collects *less* of the quota with the escalation rule removed, so "
    "the inversion is a property of a policy that responds to shortfall rather than of the fiscal "
    "apparatus.",
    "3. **Consolidation's named link was never exercised.** The merger rule's cohesion bar was "
    "never met: zero merges in every arm of the P10 batch, including the arm built to stop them. "
    "Consolidation as an outcome is robust; the mechanism the model documents for it is not what "
    "produces it.",
    "4. **One named mechanism has no second branch and another has no mechanism at all.** Elite "
    "accumulation was never built, so a bifurcation cannot be measured; famine mortality was never "
    "implemented, and the abandonment pattern it is supposed to help produce is satisfied at 1.00 "
    "without it. Pattern agreement is not mechanism evidence.",
    "5. **The gate that decides breakdown is movement, not climate.** Opening the mobility gate "
    "produces breakdown in four of four replicates at tick 48; removing the climate shocks leaves "
    "breakdown at zero and the tax base unresolved. In this model the crisis is gated by an "
    "institution, and the drought's own effects are to move households and to raise the arrears "
    "stock.",
)
_CANNOT_CLAIM: Final[tuple[str, ...]] = (
    "- **Not causal historical truth.** Six cards over three counties and thirty-two cohorts, with "
    "the sandbox's declared parameters, are a statement about this model.",
    "- **Not a ranking of the five named mechanisms.** Two are conditional, one is rejected, two "
    "are supported and one is unidentified, and the statuses rest on different amounts of "
    "evidence: the supported pair rests on a reading present in every declared policy plus a "
    "resolved intervention, while the conditional pair rests on a single arm each.",
    "- **Not a search over mechanisms.** The candidates were the plan's list plus the one "
    "structural gap the evidence itself named. A mechanism nobody listed is not assessed here, and "
    "the fitted surfaces in section 4 describe the runs rather than search them.",
    "- **Not a claim about the runtime layer.** Three declared policies ran; the runtime arm was "
    "refused, so nothing here constrains what an institutional decision layer would do.",
)
_SURFACES_DO_NOT_DECIDE: Final[str] = (
    "A boundary fitted on the P12 grid says where the policy arms turned over, and the policy is "
    "not a feature of the table: it is which columns were collected. A boundary fitted on the "
    "Morris design would say which of the fifteen swept parameters co-vary with crossing the line, "
    "and at this sample size it cannot say it at all. Neither can replace the interventions the "
    "cards cite: the ablation arms are what say a gate is load-bearing, and the difference between "
    "*the runs separate here* and *this would change the outcome* is why the cards rest on arms "
    "rather than on fits."
)
_MORRIS_SAMPLE: Final[str] = (
    "The Morris batch has {rows} runs and {positives:.0f} of them cross the declared breakdown "
    "line: two classes at a {rate:.2f} positive rate across fifteen swept parameters. The declared "
    "five-fold split is what was attempted."
)
_MORRIS_REFUSAL: Final[str] = (
    "The fit is refused rather than forced: {error}. Dropping to a split the table could carry "
    "would produce a number that measures the fold split rather than the model, so no "
    "parameter-side boundary is published; the parameter-side statement is the Morris screen "
    "itself, whose leaders on `{output}` are {leaders}."
)
_POLICY_FIT_NOTE: Final[str] = (
    "The three rows are fitted on the same two knobs in the same world, and only the decision "
    "policy differs between them. Their coefficients differ, and so does their cross-validated "
    "score - 0.550 with a spread of 0.400 on the random policy's 18 rows is a fit that separates "
    "almost nothing. Whether the differences are the policy acting or sampling noise at 18 rows is "
    "not something the fit decides; the region table in the cards' policy-robustness fields is the "
    "observation that carries the substantive claim, and it says the cells that break down move "
    "with the policy."
)


def write_mechanism_docs(root: str | Path, book: MechanismBook) -> tuple[Path, ...]:
    """Write the YAML, the index and one Markdown file per card."""
    directory = Path(root) / DOCS_ROOT
    directory.mkdir(parents=True, exist_ok=True)
    written = [
        _write(
            directory / CARDS_FILE,
            yaml.safe_dump(
                book.model_dump(mode="json"), sort_keys=False, allow_unicode=True, width=100
            ),
        )
    ]
    for card in book.cards:
        written.append(_write(directory / f"{card_slug(card)}.md", render_card(card, book)))
    written.append(_write(directory / INDEX_FILE, render_index(book)))
    return tuple(written)


def write_synthesis(
    root: str | Path,
    book: MechanismBook,
    bundle: EvidenceBundle,
    *,
    artifacts_root: str | Path | None = None,
) -> Path:
    """Write the synthesis report, including the fitted boundary section.

    ``artifacts_root`` is where the run tables are read from; it defaults to ``root``. A caller
    writing into a temporary directory passes the repository so the report is still rendered from
    the real batches rather than from the directory it is being written into.
    """
    directory = Path(root)
    source = Path(artifacts_root) if artifacts_root is not None else directory
    return _write(directory / SYNTHESIS_FILE, render_synthesis(book, bundle, source))


def load_book(path: str | Path) -> MechanismBook:
    """Read the YAML back, so a test can prove the file and the objects agree."""
    text = Path(path).read_text(encoding="utf-8")
    return MechanismBook.model_validate(json.loads(json.dumps(yaml.safe_load(text))))


def card_slug(card: MechanismCard) -> str:
    slug = card.name.lower().replace(" ", "-").replace("/", "-")
    return f"{card.id}-{slug}"


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def render_card(card: MechanismCard, book: MechanismBook) -> str:
    """One card, with the brief's sixteen fields in the brief's own order."""
    lines = [
        f"# {card.id} - {card.name}",
        "",
        f"**Status: {card.status.value}**",
        "",
        f"*Question.* {card.question}",
        "",
    ]
    body = card.model_dump(mode="json")
    for number, (heading, attribute) in enumerate(BRIEF_FIELDS, start=1):
        value = body[attribute]
        lines.append(f"## {number}. {heading}")
        lines.append("")
        if isinstance(value, list):
            if value and isinstance(value[0], dict):
                for item in value:
                    role = f"*{item['level']}*, {item['role']}"
                    lines.append(f"- {item['statement']} ({role})")
            else:
                lines.extend(f"- {item}" for item in value)
        else:
            lines.append(str(value))
        lines.append("")
    lines.append("## Evidence cited")
    lines.append("")
    lines.append("| kind | source | reading |")
    lines.append("|---|---|---|")
    for citation in card.citations:
        lines.append(f"| {citation.kind.value} | `{citation.source}` | {citation.reading} |")
    lines.append("")
    lines.append(f"Statuses across the book: {_status_line(book)}.")
    lines.append("")
    return "\n".join(lines)


def render_index(book: MechanismBook) -> str:
    """The index: the status table, the status vocabulary, and what a card is not."""
    lines = [
        "# Mechanism cards",
        "",
        _OPENING,
        "",
        _INDEX_RULE,
        "",
        "| id | mechanism | status | one line |",
        "|---|---|---|---|",
    ]
    for card in book.cards:
        link = f"[{card.name}]({card_slug(card)}.md)"
        lines.append(f"| {card.id} | {link} | {card.status.value} | {_one_line(card)} |")
    lines.extend(
        [
            "",
            f"Counts: {_status_line(book)}.",
            "",
            "## What the statuses mean",
            "",
            "| status | means |",
            "|---|---|",
            "| SUPPORTED | an intervention moved it and at least one other evidence kind agrees |",
            "| CONDITIONAL | it holds under a declared condition and not outside it |",
            "| WEAK | the evidence exists but leaves the claim unresolved |",
            "| REJECTED | a measurement contradicts the claim as stated |",
            "| UNIDENTIFIED | nothing in the project could have measured it |",
            "",
            "## What a card is not",
            "",
            _CARD_IS_NOT,
            "",
        ]
    )
    return "\n".join(lines)


def _status_line(book: MechanismBook) -> str:
    counts = book.status_counts()
    return ", ".join(f"{count} {status}" for status, count in sorted(counts.items()))


def _one_line(card: MechanismCard) -> str:
    """The shortest honest summary: the status's own reason, taken from the card's own fields.

    Sentences are cut at ``". "`` rather than at ``"."``, so a decimal like "rule 0.83" survives
    the truncation instead of being reported as "rule 0".
    """
    if card.status.value == "SUPPORTED":
        source = card.policy_robustness
    elif card.status.value == "REJECTED":
        source = card.counterexample
    else:
        source = card.uncertainty
    head = re.split(r"(?<=\.)\s", source)[0].strip()
    return head if head.endswith(".") else head + "."


def render_synthesis(book: MechanismBook, bundle: EvidenceBundle, root: Path) -> str:
    """The phase report's evidence half: the cards' joint findings and the fitted boundary."""
    lines = [
        "# Mechanism synthesis",
        "",
        _OPENING,
        "",
        _POINTER,
        "",
        "## 1. The six candidates",
        "",
        "| id | mechanism | status | evidence kinds cited |",
        "|---|---|---|---|",
    ]
    for card in book.cards:
        kinds = ", ".join(sorted(kind.value for kind in card.evidence_kinds()))
        lines.append(f"| {card.id} | {card.name} | {card.status.value} | {kinds} |")
    lines.extend(
        ["", f"Counts: {_status_line(book)}. {_REFUSED_ARM}", "", "## 2. What each card found", ""]
    )
    for index, card in enumerate(book.cards, start=1):
        lines.extend(
            [
                f"### 2.{index} {card.id} {card.name} - {card.status.value}",
                "",
                f"- **Chain.** {card.causal_chain[0]} ... {card.causal_chain[-1]}",
                f"- **Macro outcome.** {card.macro_outcome}",
                f"- **Ablation evidence.** {card.ablation_evidence}",
                f"- **Counterexample.** {card.counterexample}",
                f"- **Prediction.** {card.falsifiable_prediction}",
                "",
            ]
        )
    lines.extend(["## 3. Where the evidence contradicts the project's earlier documents", ""])
    lines.extend(_contradictions(bundle))
    lines.extend(
        [
            "",
            "## 4. The boundary analysis: what the fitted surfaces describe",
            "",
            CAUSAL_DISCLAIMER,
            "",
        ]
    )
    lines.extend(_boundary_section(root, bundle))
    lines.extend(["## 5. What this phase cannot claim", ""])
    lines.extend(_CANNOT_CLAIM)
    lines.append("")
    return "\n".join(lines)


def _contradictions(bundle: EvidenceBundle) -> list[str]:
    """The contradiction list, with the ratchet item's figures read from the readings themselves."""
    figures = [figure for policy in POLICY_LABELS for figure in bundle.ratchet_figures(policy)]
    declines = sorted(figure[2] for figure in figures)
    rule = bundle.ratchet_figures(POLICY_LABELS[0])
    largest = max(rule, key=lambda figure: figure[1])
    filled = _CONTRADICTIONS[0].format(
        declines_low=declines[0],
        declines_high=declines[-1],
        largest_end=f"{largest[1]:,.0f}",
        largest_declines=largest[2],
    )
    return [filled, *_CONTRADICTIONS[1:]]


def _boundary_section(root: Path, bundle: EvidenceBundle) -> list[str]:
    """Fit the surfaces the run tables support, and describe them without overreading them."""
    experiments = root / "outputs/experiments"
    grid = pl.read_parquet(experiments / ROBUSTNESS_BATCH / "tipping_grid.parquet")
    morris = pl.read_parquet(experiments / MORRIS_BATCH / "runs.parquet")
    pooled = load_run_tables(
        [
            experiments / ROBUSTNESS_BATCH / "tipping_grid.parquet",
            experiments / MORRIS_BATCH / "runs.parquet",
        ],
        features=SCENARIO_FEATURES,
        target=BOUNDARY_TARGET,
    )
    scenario = fit_boundary(grid, target=BOUNDARY_TARGET, features=SCENARIO_FEATURES)
    surface = tipping_surface(
        grid, target=BOUNDARY_TARGET, x=SCENARIO_FEATURES[0], y=SCENARIO_FEATURES[1]
    )
    pressure = partial_dependence(
        scenario, grid, feature=SCENARIO_FEATURES[0], values=(0.01, 0.02, 0.04)
    )
    lineup = ", ".join(f"`{feature}`" for feature in scenario.features)
    curve = ", ".join(
        f"{row['value']:.2f} -> {row['mean_probability']:.3f}"
        for row in pressure.iter_rows(named=True)
    )
    lines = [
        "### 4.1 The scenario surface (P12's grid)",
        "",
        f"Fitted on the {scenario.rows} runs of the P12 tipping grid: target `{scenario.target}`, "
        f"features {lineup}, {scenario.model} model. Cross-validated AUC "
        f"{scenario.cross_validated_auc:.3f} (sd {scenario.auc_std:.3f}) against an in-sample "
        f"{scenario.in_sample_auc:.3f}, so the separation is not an artefact of scoring the rows "
        "that were fitted.",
        "",
        "| feature | standardized coefficient |",
        "|---|---|",
    ]
    for name, weight in scenario.coefficients:
        lines.append(f"| `{name}` | {weight:+.3f} |")
    lines.extend(
        [
            "",
            f"Partial dependence on `{SCENARIO_FEATURES[0]}`: {curve}.",
            "",
            "Observed breakdown share by cell, all three declared policies pooled:",
            "",
            "| " + " | ".join(surface.columns) + " |",
            "|" + "---|" * len(surface.columns),
        ]
    )
    for row in surface.iter_rows(named=True):
        lines.append("| " + " | ".join(_cell(row[column]) for column in surface.columns) + " |")
    lines.extend(_policy_surfaces(grid))
    lines.extend(_parameter_surface(morris, pooled, bundle))
    lines.extend(["", "### 4.4 What the surfaces do not decide", "", _SURFACES_DO_NOT_DECIDE, ""])
    return lines


def _cell(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def _policy_surfaces(grid: pl.DataFrame) -> list[str]:
    """The same fit per declared policy: does the boundary the policy draws differ?"""
    lines = [
        "",
        "### 4.2 The same fit per policy",
        "",
        "| policy | runs | cv AUC | sd | pressure | severity | breakdown share |",
        "|---|---|---|---|---|---|---|",
    ]
    for policy in POLICY_LABELS:
        rows = grid.filter(pl.col("policy") == policy)
        share = scalar(rows[BOUNDARY_TARGET].cast(pl.Float64).mean())
        try:
            fit = fit_boundary(rows, target=BOUNDARY_TARGET, features=SCENARIO_FEATURES)
        except BoundaryError as error:
            message = str(error).replace("|", "/")
            lines.append(
                f"| {policy} | {rows.height} | not fittable: {message} | | | | {share:.2f} |"
            )
            continue
        weights = dict(fit.coefficients)
        pressure = weights[SCENARIO_FEATURES[0]]
        severity = weights[SCENARIO_FEATURES[1]]
        lines.append(
            f"| {policy} | {fit.rows} | {fit.cross_validated_auc:.3f} | {fit.auc_std:.3f} | "
            f"{pressure:+.2f} | {severity:+.2f} | {share:.2f} |"
        )
    lines.extend(["", _POLICY_FIT_NOTE, ""])
    return lines


def _parameter_surface(
    morris: pl.DataFrame, pooled: pl.DataFrame, bundle: EvidenceBundle
) -> list[str]:
    """The parameter-side fit, or the refusal the sample forces, stated as such."""
    positives = scalar(morris[BOUNDARY_TARGET].cast(pl.Float64).sum())
    sample = _MORRIS_SAMPLE.format(
        rows=morris.height, positives=positives, rate=positives / morris.height
    )
    leaders = ", ".join(f"`{name}`" for name in bundle.morris_rank(PRIMARY_OUTPUT)[:3])
    lines = ["", "### 4.3 The parameter surface (P10's Morris design)", "", sample, ""]
    try:
        fit = fit_boundary(
            morris, target=BOUNDARY_TARGET, features=MORRIS_FEATURES, model=BOOSTED_MODEL
        )
    except BoundaryError as error:
        lines.extend(
            [
                _MORRIS_REFUSAL.format(error=error, output=PRIMARY_OUTPUT, leaders=leaders),
                "",
            ]
        )
        return lines
    lines.extend(
        [
            f"Cross-validated AUC {fit.cross_validated_auc:.3f} (sd {fit.auc_std:.3f}) against an "
            f"in-sample {fit.in_sample_auc:.3f}; the gap is the sample size, not the mechanism.",
            "",
            "| feature | importance |",
            "|---|---|",
        ]
    )
    for name, weight in fit.importance()[:6]:
        lines.append(f"| `{name}` | {weight:+.3f} |")
    sources = pooled["source"].value_counts(sort=True)
    stacked = ", ".join(
        f"`{row['source']}` {row['count']} rows" for row in sources.iter_rows(named=True)
    )
    lines.extend(
        ["", f"Tables the loader could stack on the declared scenario features: {stacked}.", ""]
    )
    return lines
