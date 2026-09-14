"""The declared policies: what they must always do, and what they must never do.

The runtime model is not the only decision source, and the rest of them have to be boring. Whatever
the observation, a policy answers inside the action space it was handed, with an intensity the
schema accepts, a rationale short enough to store, and the same answer every time it is asked. The
tables themselves are argued in each module's docstring; these tests defend the lines, the caps, the
gates and the fallbacks that a reader of those tables was promised.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final

import pytest

from late_ming_lab.policies.base import (
    MAX_RATIONALE_CHARS,
    ROLE_ACTIONS,
    ActorRole,
    DecisionRejectedError,
    InstitutionalAction,
    InstitutionalDecision,
    InstitutionalPolicy,
    PolicyObservation,
    Priority,
)
from late_ming_lab.policies.random_policy import RandomPolicy
from late_ming_lab.policies.rules import RulePolicy
from late_ming_lab.policies.utility import UtilityPolicy

#: The county's space, as the role table declares it: full extraction and relief, in that order.
COUNTY_ACTIONS: Final[tuple[InstitutionalAction, ...]] = ROLE_ACTIONS[ActorRole.COUNTY]

#: The three declared policies, under one contract and one seed, so a property asked of one of them
#: is asked of all three.
POLICIES: Final[tuple[InstitutionalPolicy, ...]] = (
    RulePolicy(),
    UtilityPolicy(),
    RandomPolicy(seed=17),
)

#: Spaces a policy can be handed: the full one, a single action, and one that holds no MAINTAIN.
SPACES: Final[tuple[tuple[InstitutionalAction, ...], ...]] = (
    COUNTY_ACTIONS,
    (InstitutionalAction.MAINTAIN,),
    (InstitutionalAction.RELIEF_TRANSFER,),
    (InstitutionalAction.BLOCK_LINK, InstitutionalAction.REOPEN_LINK),
)

#: A reading in which every measure has moved: what a policy has to answer when nothing is quiet.
STORM: Final[Mapping[str, float]] = {
    "tax_arrears_months": 9.0,
    "receipts_over_quota": 0.1,
    "unmet_need_share": 0.6,
    "armed_share_of_adults": 0.05,
    "out_migration_share": 0.2,
    "largest_band_share": 0.7,
}

#: The action space a policy's own observation carries. Every test hands the policy its space as an
#: argument instead, because the argument is what a decision has to stay inside.
DECLARED_SPACE: Final[tuple[InstitutionalAction, ...]] = COUNTY_ACTIONS


def _observation(
    measures: Mapping[str, float] | None = None, *, tick: int = 0
) -> PolicyObservation:
    """One actor's reading of the world: the measures a test names, and no others."""
    return PolicyObservation(
        actor="actor-0",
        role=ActorRole.COUNTY,
        region="region-a",
        tick=tick,
        measures=tuple((measures or {}).items()),
        action_space=DECLARED_SPACE,
    )


def _sequence(policy: InstitutionalPolicy, ticks: int) -> tuple[InstitutionalDecision, ...]:
    """One decision per tick, for a run long enough that a draw can repeat or diverge."""
    return tuple(
        policy.choose_action(_observation({"unmet_need_share": 0.4}, tick=tick), COUNTY_ACTIONS)
        for tick in range(ticks)
    )


def test_each_policy_satisfies_the_institutional_contract() -> None:
    assert isinstance(RulePolicy(), InstitutionalPolicy)
    assert isinstance(UtilityPolicy(), InstitutionalPolicy)
    assert isinstance(RandomPolicy(seed=1), InstitutionalPolicy)
    assert [policy.name for policy in POLICIES] == ["rule-v1", "utility-v1", "random-v1"]


@pytest.mark.parametrize("policy", POLICIES, ids=[policy.name for policy in POLICIES])
@pytest.mark.parametrize("space", SPACES)
def test_a_decision_stays_inside_the_space_it_was_handed(
    policy: InstitutionalPolicy, space: tuple[InstitutionalAction, ...]
) -> None:
    decision = policy.choose_action(_observation(STORM), space)

    assert decision.action in space
    assert 0.0 <= decision.intensity <= 1.0
    assert 0 < len(decision.rationale) <= MAX_RATIONALE_CHARS


@pytest.mark.parametrize("policy", POLICIES, ids=[policy.name for policy in POLICIES])
def test_the_same_situation_gets_the_same_decision(policy: InstitutionalPolicy) -> None:
    observation = _observation({"unmet_need_share": 0.4, "out_migration_share": 0.09})

    assert policy.choose_action(observation, COUNTY_ACTIONS) == policy.choose_action(
        observation, COUNTY_ACTIONS
    )


@pytest.mark.parametrize("policy", POLICIES, ids=[policy.name for policy in POLICIES])
def test_an_empty_action_space_is_refused(policy: InstitutionalPolicy) -> None:
    with pytest.raises(DecisionRejectedError):
        policy.choose_action(_observation({"unmet_need_share": 0.6}), ())


@pytest.mark.parametrize(
    ("measures", "action", "priority"),
    [
        (
            {"tax_arrears_months": 6.0},
            InstitutionalAction.RELAX_EXTRACTION,
            Priority.STABILIZE_TAX_BASE,
        ),
        (
            {"receipts_over_quota": 0.30},
            InstitutionalAction.RELAX_EXTRACTION,
            Priority.STABILIZE_TAX_BASE,
        ),
        (
            {"unmet_need_share": 0.35},
            InstitutionalAction.RELIEF_TRANSFER,
            Priority.RELIEVE_DISTRESS,
        ),
        (
            {"armed_share_of_adults": 0.02},
            InstitutionalAction.INTENSIFY_EXTRACTION,
            Priority.PRESERVE_ORDER,
        ),
        (
            {"out_migration_share": 0.05},
            InstitutionalAction.RELAX_EXTRACTION,
            Priority.STABILIZE_TAX_BASE,
        ),
    ],
)
def test_a_rule_fires_at_its_line(
    measures: Mapping[str, float], action: InstitutionalAction, priority: Priority
) -> None:
    decision = RulePolicy().choose_action(_observation(measures), COUNTY_ACTIONS)

    assert decision.action == action
    assert decision.priority == priority


@pytest.mark.parametrize(
    "measures",
    [
        {"tax_arrears_months": 5.9},
        {"receipts_over_quota": 0.31},
        {"unmet_need_share": 0.34},
        {"armed_share_of_adults": 0.019},
        {"out_migration_share": 0.049},
    ],
)
def test_a_rule_does_not_fire_below_its_line(measures: Mapping[str, float]) -> None:
    decision = RulePolicy().choose_action(_observation(measures), COUNTY_ACTIONS)

    assert decision.action == InstitutionalAction.MAINTAIN
    assert decision.intensity == 0.0
    assert decision.priority == Priority.MAINTAIN


@pytest.mark.parametrize(
    ("measures", "cap"),
    [
        ({"tax_arrears_months": 120.0}, 0.6),
        ({"receipts_over_quota": 0.0}, 0.6),
        ({"unmet_need_share": 1.0}, 0.8),
        ({"armed_share_of_adults": 0.5}, 0.5),
        ({"out_migration_share": 0.5}, 0.6),
    ],
)
def test_each_row_stops_at_its_cap(measures: Mapping[str, float], cap: float) -> None:
    decision = RulePolicy().choose_action(_observation(measures), COUNTY_ACTIONS)

    assert decision.intensity == pytest.approx(cap)


def test_a_response_grows_with_the_distance_past_the_line() -> None:
    policy = RulePolicy()

    near = policy.choose_action(_observation({"tax_arrears_months": 6.5}), COUNTY_ACTIONS)
    further = policy.choose_action(_observation({"tax_arrears_months": 9.0}), COUNTY_ACTIONS)

    assert near.action == further.action == InstitutionalAction.RELAX_EXTRACTION
    assert near.intensity == pytest.approx(0.05)
    assert further.intensity == pytest.approx(0.30)


def test_relief_is_chosen_before_order_when_both_readings_have_crossed() -> None:
    decision = RulePolicy().choose_action(
        _observation({"unmet_need_share": 0.5, "armed_share_of_adults": 0.06}), COUNTY_ACTIONS
    )

    assert decision.action == InstitutionalAction.RELIEF_TRANSFER
    assert decision.intensity == pytest.approx(0.30)


def test_a_gated_rule_is_skipped_when_its_action_is_not_in_the_space() -> None:
    without_relief = (
        InstitutionalAction.MAINTAIN,
        InstitutionalAction.RELAX_EXTRACTION,
        InstitutionalAction.INTENSIFY_EXTRACTION,
    )

    decision = RulePolicy().choose_action(_observation({"unmet_need_share": 0.6}), without_relief)

    assert decision.action == InstitutionalAction.MAINTAIN, "an actor that cannot relieve, waits"


def test_an_action_the_space_does_not_hold_falls_back_inside_the_space() -> None:
    observation = _observation({"tax_arrears_months": 12.0})

    with_maintain = RulePolicy().choose_action(
        observation, (InstitutionalAction.MAINTAIN, InstitutionalAction.RELIEF_TRANSFER)
    )
    without_maintain = RulePolicy().choose_action(
        observation, (InstitutionalAction.RELIEF_TRANSFER,)
    )

    assert with_maintain.action == InstitutionalAction.MAINTAIN
    assert with_maintain.intensity == 0.0
    assert without_maintain.action == InstitutionalAction.RELIEF_TRANSFER
    assert without_maintain.intensity == 0.0


def test_the_rationale_quotes_the_rule_that_fired() -> None:
    decision = RulePolicy().choose_action(_observation({"tax_arrears_months": 9.0}), COUNTY_ACTIONS)

    assert "tax_arrears_months" in decision.rationale
    assert "RELAX_EXTRACTION" in decision.rationale


def test_an_oversized_prefix_is_clipped_rather_than_the_quote() -> None:
    policy = RulePolicy(rationale_prefix="rule " * 200)

    decision = policy.choose_action(_observation({"tax_arrears_months": 9.0}), COUNTY_ACTIONS)

    assert len(decision.rationale) == MAX_RATIONALE_CHARS
    assert "tax_arrears_months" in decision.rationale


UNINFORMATIVE: Final[tuple[Mapping[str, float], ...]] = (
    {},
    {"harvest_index": 0.4, "price_ratio": 1.3},
    {"tax_arrears_months": 0.0, "unmet_need_share": 0.0},
)


@pytest.mark.parametrize("policy", POLICIES[:2], ids=["rule-v1", "utility-v1"])
@pytest.mark.parametrize("measures", UNINFORMATIVE)
def test_an_uninformative_observation_maintains(
    policy: InstitutionalPolicy, measures: Mapping[str, float]
) -> None:
    decision = policy.choose_action(_observation(measures), COUNTY_ACTIONS)

    assert decision.action == InstitutionalAction.MAINTAIN
    assert decision.intensity == 0.0
    assert decision.priority == Priority.MAINTAIN


@pytest.mark.parametrize("space", SPACES)
def test_the_control_still_answers_an_observation_with_no_measures(
    space: tuple[InstitutionalAction, ...],
) -> None:
    decision = RandomPolicy(seed=3).choose_action(_observation(), space)

    assert decision.action in space
    assert 0.0 <= decision.intensity <= 1.0


def test_the_utility_policy_prefers_the_action_its_weights_favour() -> None:
    policy = UtilityPolicy()

    receipts = policy.choose_action(_observation({"receipts_over_quota": 0.8}), COUNTY_ACTIONS)
    arrears = policy.choose_action(_observation({"tax_arrears_months": 6.0}), COUNTY_ACTIONS)
    distress = policy.choose_action(
        _observation({"out_migration_share": 0.3, "armed_share_of_adults": 0.5}), COUNTY_ACTIONS
    )

    assert receipts.action == InstitutionalAction.RELAX_EXTRACTION
    assert receipts.intensity == pytest.approx(0.8)
    assert "receipts_over_quota" in receipts.rationale
    assert arrears.action == InstitutionalAction.INTENSIFY_EXTRACTION
    assert distress.action == InstitutionalAction.RELIEF_TRANSFER


def test_a_caller_weight_replaces_the_declared_one_for_that_reading() -> None:
    observation = _observation({"receipts_over_quota": 0.8, "tax_arrears_months": 0.5})

    declared = UtilityPolicy().choose_action(observation, COUNTY_ACTIONS)
    reweighted = UtilityPolicy(weights={"receipts_over_quota": 0.0}).choose_action(
        observation, COUNTY_ACTIONS
    )

    assert declared.action == InstitutionalAction.RELAX_EXTRACTION
    assert reweighted.action == InstitutionalAction.INTENSIFY_EXTRACTION


def test_a_tie_goes_to_the_earlier_action_in_the_space() -> None:
    policy = UtilityPolicy()
    observation = _observation({"unmet_need_share": 0.5})

    forward = policy.choose_action(
        observation, (InstitutionalAction.RELAX_EXTRACTION, InstitutionalAction.RELIEF_TRANSFER)
    )
    reversed_space = policy.choose_action(
        observation, (InstitutionalAction.RELIEF_TRANSFER, InstitutionalAction.RELAX_EXTRACTION)
    )

    assert forward.action == InstitutionalAction.RELAX_EXTRACTION
    assert reversed_space.action == InstitutionalAction.RELIEF_TRANSFER
    assert forward.intensity == pytest.approx(reversed_space.intensity)


def test_the_utility_policy_does_not_press_an_action_that_hurts() -> None:
    decision = UtilityPolicy().choose_action(
        _observation({"unmet_need_share": 0.5, "out_migration_share": 0.4}),
        (InstitutionalAction.BLOCK_LINK,),
    )

    assert decision.action == InstitutionalAction.BLOCK_LINK
    assert decision.intensity == 0.0


def test_the_random_policy_repeats_from_its_seed() -> None:
    policy = RandomPolicy(seed=7)
    observation = _observation({"unmet_need_share": 0.4})

    same_instance = policy.choose_action(observation, COUNTY_ACTIONS)

    assert policy.choose_action(observation, COUNTY_ACTIONS) == same_instance
    assert RandomPolicy(seed=7).choose_action(observation, COUNTY_ACTIONS) == same_instance


def test_two_seeds_diverge_over_a_long_enough_sequence() -> None:
    one = _sequence(RandomPolicy(seed=1), 64)
    two = _sequence(RandomPolicy(seed=2), 64)

    assert tuple(decision.action for decision in one) != tuple(decision.action for decision in two)
    assert len({decision.action for decision in one}) > 1, "a draw over four actions varies"


def test_a_drawn_maintain_spends_nothing() -> None:
    maintains = [
        decision
        for decision in _sequence(RandomPolicy(seed=11), 64)
        if decision.action == InstitutionalAction.MAINTAIN
    ]

    assert maintains, "a uniform draw over four actions reaches MAINTAIN within 64 ticks"
    assert {decision.intensity for decision in maintains} == {0.0}
