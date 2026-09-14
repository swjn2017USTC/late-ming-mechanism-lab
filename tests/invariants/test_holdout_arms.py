"""V2-P04: the arms intervene, the chains are recorded, the instrumentation changed no behaviour.

Three properties the phase's acceptance turns on, each checked against a real run rather than
argued:

```text
no-op detection    an arm that declares a structure and moves nothing is refused, and an ablation
                   that moves something is refused too
behaviour          the instrumentation added no behaviour: the behavioural event counts on the
                   historical core are exactly what the pre-instrumentation run recorded, and the
                   only difference is the three new event types
granularity        each chain event is one row per node-month, county-month and cohort-tick, so a
                   chain cannot be silently thinned
```

The behavioural counts below were read from the stored pre-instrumentation run of
`historical-core-v1` (V2-P02's) and from the reference arm of this phase; they are the row-level
evidence the phase report records, pinned here so a later change cannot quietly move them.
"""

from __future__ import annotations

import polars as pl
import pytest

from late_ming_lab.analysis.chains import chain_summary
from late_ming_lab.experiments.historical_core import HISTORICAL_SCENARIO
from late_ming_lab.experiments.holdout import (
    REFERENCE_ARM,
    Arm,
    ArmFacts,
    ArmRun,
    HoldoutError,
    declared_arms,
    detect_no_op,
    run_arm,
)

#: Where the reference arm's run is written for this module.
OUTPUT_ROOT = "outputs/v2/p04-regression"

#: One seed: these tests are about a declaration and a vocabulary, not about a distribution.
SEED = 20_260_915

#: The behavioural counts on twelve counties over 240 ticks, as the pre-instrumentation run recorded
#: them. None of them mentions a chain event: the instrumentation is additive by construction, and
#: this is what that means in numbers.
BEHAVIOURAL_COUNTS = {
    "DESERTER_RETURN": 15_125,
    "CONSUMPTION": 14_400,
    "LABOUR_INCOME": 14_400,
    "COHORT_STATE": 14_400,
    "RECRUITMENT_LEVY": 14_394,
    "MILITARY_STANDING": 4_483,
    "MARKET_STATE": 3_360,
    "OFFICIAL_RELIEF": 878,
    "BAND_STATE": 1_450,
}

#: The instrumentation's own counts, which are one row per unit per tick by declaration.
INSTRUMENTED_COUNTS = {
    "MARKET_CONSTRAINT": 3_360,  # 14 priced nodes x 240 ticks
    "RELIEF_CONSTRAINT": 2_880,  # 12 counties x 240 ticks
    "MIGRATION_GATE": 14_400,  # 60 cohorts x 240 ticks
}


@pytest.fixture(scope="module")
def reference_run() -> ArmRun:
    return run_arm(
        Arm(
            label=REFERENCE_ARM,
            description="the V1 structure on the historical core",
            expects_effect=False,
        ),
        root=".",
        root_seed=SEED,
        output_root=OUTPUT_ROOT,
    )


def test_the_instrumentation_added_rows_and_nothing_else(reference_run: ArmRun) -> None:
    """Every behavioural count is what it was, and the new rows are exactly the three chains."""
    counts = reference_run.facts.event_counts
    drifted = {
        name: (expected, counts.get(name, 0))
        for name, expected in BEHAVIOURAL_COUNTS.items()
        if counts.get(name, 0) != expected
    }
    assert drifted == {}, f"behavioural event counts moved: {drifted}"
    for name, expected in INSTRUMENTED_COUNTS.items():
        assert counts.get(name, 0) == expected, name


def test_each_chain_records_one_row_per_unit_per_tick(reference_run: ArmRun) -> None:
    """A chain event per unit per tick, so no month is missing and none is doubled."""
    events = reference_run.events
    price = events.filter(pl.col("event_type") == "MARKET_CONSTRAINT")
    relief = events.filter(pl.col("event_type") == "RELIEF_CONSTRAINT")
    gate = events.filter(pl.col("event_type") == "MIGRATION_GATE")
    assert price["tick"].n_unique() == 240
    assert price.group_by("tick").len()["len"].n_unique() == 1
    assert relief.group_by("tick").len()["len"].n_unique() == 1
    assert gate.group_by("tick").len()["len"].n_unique() == 1


def test_the_chain_summary_is_reproducible_for_the_same_log(reference_run: ArmRun) -> None:
    """Two readings of one log agree exactly; a summary that drifted would fabricate a contrast."""
    first = chain_summary(reference_run.events)
    second = chain_summary(reference_run.events)
    assert first == second
    assert first["price_wanted_shi"] >= first["price_unaffordable_demand_shi"]


def test_a_variant_that_moves_nothing_is_refused(reference_run: ArmRun) -> None:
    """The no-op the phase's acceptance says must fail it: a declared structure, no difference."""
    silent = Arm(
        label="declared-but-silent",
        description="declares a structure and changes no parameter",
        expects_effect=True,
        market={"demand_pressure_weight": 0.0},
    )
    facts = ArmFacts(
        arm=silent.label,
        run_id="declared-but-silent",
        root_seed=SEED,
        simulation_digest=reference_run.facts.simulation_digest,
        event_total=reference_run.facts.event_total,
        event_counts=dict(reference_run.facts.event_counts),
        chains=dict(reference_run.facts.chains),
    )
    with pytest.raises(HoldoutError, match=r"no parameter|no-op"):
        detect_no_op(
            (
                ArmRun(arm=silent, facts=facts, events=reference_run.events),
                reference_run,
            )
        )


def test_an_ablation_that_moves_something_is_refused(reference_run: ArmRun) -> None:
    """The other direction: if the neutral arm differs, the parameter is not the intervention."""
    moved = ArmFacts(
        arm="ablation-that-moves",
        run_id="ablation-that-moves",
        root_seed=SEED,
        simulation_digest="0" * 64,
        event_total=reference_run.facts.event_total + 1,
        event_counts=dict(reference_run.facts.event_counts),
        chains=dict(reference_run.facts.chains),
    )
    ablation = Arm(
        label="ablation-that-moves",
        description="declares no effect and moves something",
        expects_effect=False,
    )
    with pytest.raises(HoldoutError, match="ablation"):
        detect_no_op(
            (
                ArmRun(arm=ablation, facts=moved, events=reference_run.events),
                reference_run,
            )
        )


def test_every_declared_arm_says_what_it_must_move() -> None:
    """A variant moves a parameter; an ablation moves none. Both directions are declarations."""
    for arm in declared_arms():
        diff = arm.configuration_diff()
        if arm.expects_effect:
            assert diff, f"{arm.label}: a variant with an empty configuration diff is a no-op"
        else:
            assert not diff, f"{arm.label}: an ablation must sit at the reference's values"


def test_the_reference_arm_runs_the_declared_scenario(reference_run: ArmRun) -> None:
    """The reference is the V1 structure on the V2 input, not a variant of it."""
    assert reference_run.arm.configuration_diff() == {}
    assert reference_run.facts.event_total > 0
    assert HISTORICAL_SCENARIO.dataset == "historical-core-v1"
