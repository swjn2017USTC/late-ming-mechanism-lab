"""The migration rules themselves: who may move, where they go, what they carry, when they return.

Each test drives `MigrationSystem` over a small hand-built world with a real tick context, so the
rules are exercised exactly as the kernel exercises them. The interesting assertions are about
conservation and gatekeeping: a move that no cohort received, a move that ignored cost, capacity or
eligibility, or a seasonal group that never came home would all show up here.
"""

from __future__ import annotations

import polars as pl
import pytest

from late_ming_lab.actors.fixtures import (
    toy_cohort_population,
    toy_merchant_layer,
)
from late_ming_lab.actors.households import (
    CohortClass,
    HouseholdCohortAgent,
    HouseholdPopulation,
)
from late_ming_lab.core.clock import Clock
from late_ming_lab.core.config import SimulationConfig
from late_ming_lab.core.events import EventLogger
from late_ming_lab.core.rng import RngStreams
from late_ming_lab.core.tick import TickContext
from late_ming_lab.evidence.parameters import (
    core_default_household_parameters,
    core_default_migration_parameters,
)
from late_ming_lab.networks.fixtures import toy_spatial_dataset
from late_ming_lab.networks.graphs import SpatialGraphs
from late_ming_lab.systems.markets import MarketBook
from late_ming_lab.systems.migration import (
    EXIT_EVENT,
    MIGRATION_RULE_VERSION,
    SETTLEMENT_EVENT,
    TEMPORARY_EVENT,
    MigrationSystem,
)

MIGRATION = core_default_migration_parameters()


def _toy_households(cohort_id: str) -> float:
    """The opening weight of a fixture cohort, for comparing against a run's arrivals."""
    graphs = toy_spatial_dataset().build()
    return toy_cohort_population(graphs.nodes).require(cohort_id).households


HOUSEHOLDS = core_default_household_parameters()
ORIGIN = "toy-sx-a"
CHEAP = "toy-sx-b"
EXIT_NODE = "toy-ext-shanxi"


def _context(tick: int = 0, tick_count: int = 48) -> TickContext:
    config = SimulationConfig.model_validate({"tick_count": tick_count, "warmup_ticks": 0})
    clock = Clock.from_config(config)
    return TickContext(
        config=config,
        clock=clock,
        tick=tick,
        month=clock.month_at(tick),
        period=clock.period_at(tick),
        rng=RngStreams(config.root_seed),
        logger=EventLogger(tick_count=tick_count),
    )


def _world(
    *, prices: dict[str, float] | None = None
) -> tuple[MigrationSystem, HouseholdPopulation, SpatialGraphs]:
    graphs = toy_spatial_dataset().build()
    population = toy_cohort_population(graphs.nodes)
    merchants = toy_merchant_layer(graphs)
    book = MarketBook(
        prices
        or {
            ORIGIN: 8.0,
            CHEAP: 2.0,
            "toy-sx-c": 5.0,
            "toy-hn-a": 4.0,
            "toy-hn-b": 6.0,
            EXIT_NODE: 9.0,
        }
    )
    system = MigrationSystem(
        graphs=graphs,
        population=population,
        merchants=merchants,
        book=book,
        parameters=MIGRATION,
        household_parameters=HOUSEHOLDS,
    )
    return system, population, graphs


def _eligible(
    population: HouseholdPopulation, cohort_id: str, *, permanent: bool, temporary: bool
) -> HouseholdCohortAgent:
    cohort = population.require(cohort_id)
    cohort.permanent_migration_eligible = permanent
    cohort.temporary_migration_eligible = temporary
    return cohort


def test_the_destination_is_the_cheapest_reachable_priced_node() -> None:
    system, _, _ = _world()

    assert system.destination_for(ORIGIN) == CHEAP
    assert system.is_exit(EXIT_NODE)
    assert not system.is_exit(CHEAP)


def test_a_county_is_preferred_to_the_exit_until_no_county_is_better() -> None:
    """The exit is a last resort, not the default: boundary prices never respond to scarcity."""
    system, _, _ = _world(prices={ORIGIN: 5.0, CHEAP: 1.0, EXIT_NODE: 0.5})
    assert system.destination_for(ORIGIN) == CHEAP, "a cheaper county beats leaving the region"

    desperate, _, _ = _world(prices={ORIGIN: 0.5, CHEAP: 4.0, EXIT_NODE: 1.0})
    assert desperate.destination_for(ORIGIN) == EXIT_NODE, (
        "with nothing better inside, people leave"
    )

    stranded, _, _ = _world(prices={ORIGIN: 0.5, CHEAP: 4.0})
    assert stranded.destination_for(ORIGIN) == CHEAP, "with no exit in reach, they still move"


def test_a_group_of_migrants_leaves_the_cohort_and_returns_when_the_term_ends() -> None:
    system, population, _ = _world()
    cohort = _eligible(population, f"{ORIGIN}:poor-smallholder", permanent=False, temporary=True)
    adults_before = cohort.adults
    silver_before = cohort.silver_tael
    ctx = _context(tick=0)

    system.step(ctx)

    away = system.migrants.at(cohort.cohort_id)
    assert away is not None
    assert away.destination_node == CHEAP
    assert away.adults == pytest.approx(
        adults_before * MIGRATION.temporary_share_of_adults_per_month
    )
    assert cohort.adults == pytest.approx(adults_before - away.adults), (
        "adults away are off the cohort's books while they are away"
    )
    assert silver_before - cohort.silver_tael == pytest.approx(
        away.adults * MIGRATION.cost_tael_per_adult, rel=1e-9
    ), "the season away costs the declared silver per adult, and the cohort pays it"
    assert ctx.logger.to_frame().filter(pl.col("event_type") == TEMPORARY_EVENT).height == 1

    # The term ends: the same adults come home, and a cohort still in distress sends the next
    # season's group in the same tick - so the book holds a group again, dated to this tick.
    later = _context(tick=MIGRATION.temporary_term_months + 1)
    system.step(later)
    returned = later.logger.to_frame().filter(pl.col("event_type") == "TEMPORARY_RETURN")
    assert returned.height == 1
    assert returned["outcome"].item() == "term-ended"
    assert (
        float(
            returned["trigger_json"]
            .str.json_path_match("$.adults_returned")
            .cast(pl.Float64)
            .item()
        )
        == away.adults
    ), "every adult sent away is an adult brought home"
    second_season = system.migrants.at(cohort.cohort_id)
    assert second_season is not None and second_season.departed_tick == later.tick
    assert cohort.adults == pytest.approx(adults_before - second_season.adults)


def test_migrants_come_home_early_when_the_money_runs_out() -> None:
    system, population, _ = _world()
    cohort = _eligible(population, f"{ORIGIN}:poor-smallholder", permanent=False, temporary=True)
    system.step(_context(tick=0))
    away = system.migrants.at(cohort.cohort_id)
    assert away is not None

    if cohort.silver_tael > 0.0:
        cohort.record_migrant_subsistence(
            silver_tael=cohort.silver_tael,
            destination=away.destination_node,
            rule_version="temporary-migration-v1",
        )
    cohort.check_balances()
    ctx = _context(tick=1)
    system.step(ctx)

    assert system.migrants.at(cohort.cohort_id) is None, "no money and no market means coming home"
    returned = ctx.logger.to_frame().filter(pl.col("event_type") == "TEMPORARY_RETURN")
    assert returned.height == 1
    assert returned["outcome"].item() == "out-of-money"


def test_an_ineligible_cohort_stays_where_it_is() -> None:
    system, population, _ = _world()
    cohort = _eligible(population, f"{ORIGIN}:poor-smallholder", permanent=False, temporary=False)
    before = (cohort.adults, cohort.households, cohort.land_mu)

    system.step(_context())

    assert (cohort.adults, cohort.households, cohort.land_mu) == before
    assert len(system.migrants) == 0


def test_a_permanent_move_settles_the_households_and_abandons_the_land() -> None:
    system, population, _ = _world()
    cohort = _eligible(population, f"{ORIGIN}:poor-smallholder", permanent=True, temporary=False)
    arrival = population.require(f"{CHEAP}:poor-smallholder")
    before = {
        "households": cohort.households,
        "arrival": arrival.households,
        "land": cohort.land_mu,
        "land_per_household": cohort.land_per_household_mu,
        "arrival_land": arrival.land_mu,
    }
    ctx = _context()

    system.step(ctx)

    expected_movers = min(
        before["households"] * MIGRATION.permanent_share_of_households_per_month,
        system.edge_capacity(ORIGIN, CHEAP),
    )
    assert cohort.households == pytest.approx(before["households"] - expected_movers)
    assert arrival.households == pytest.approx(before["arrival"] + expected_movers)
    assert cohort.land_mu == pytest.approx(
        before["land"] - before["land"] * (expected_movers / before["households"])
    ), "the movers' fields are abandoned at the origin"
    assert arrival.land_mu == pytest.approx(before["arrival_land"]), "arrivals bring no land"
    assert cohort.land_per_household_mu == pytest.approx(before["land_per_household"])
    settled = ctx.logger.to_frame().filter(pl.col("event_type") == SETTLEMENT_EVENT)
    assert settled.height == 1
    assert settled["region"].item() == CHEAP


def test_a_cohort_is_never_emptied_by_migration() -> None:
    system, population, _ = _world()
    cohort = _eligible(population, f"{ORIGIN}:poor-smallholder", permanent=True, temporary=False)
    shrinking = -(cohort.households - 2.0)
    cohort._apply(households=shrinking, impacts=(("households_delta_households", shrinking),))
    mover_parameters = MIGRATION.model_copy(
        update={"permanent_share_of_households_per_month": 1.0, "minimum_households_to_move": 1.0}
    )
    system._parameters = mover_parameters

    system.step(_context())

    assert cohort.households >= 1.0, "the last household stays"


def test_movers_leaving_the_region_are_an_outflow_not_a_transfer() -> None:
    """When nothing inside the region is better, movers leave the modelled population."""
    system, population, _ = _world(prices={ORIGIN: 1.0, CHEAP: 3.0, EXIT_NODE: 0.5})
    cohort = _eligible(population, f"{ORIGIN}:poor-smallholder", permanent=True, temporary=False)
    ctx = _context()

    system.step(ctx)

    assert system.destination_for(ORIGIN) == EXIT_NODE
    assert ctx.logger.to_frame().filter(pl.col("event_type") == EXIT_EVENT).height == 1
    assert ctx.logger.to_frame().filter(pl.col("event_type") == SETTLEMENT_EVENT).height == 0
    # Nobody in the modelled population gained them.
    for other in population:
        if other.cohort_id != cohort.cohort_id:
            assert other.households == _toy_households(other.cohort_id)


def test_a_cohort_with_no_silver_cannot_move() -> None:
    """Destitution is a gate, and the ledger has to agree: the cohort never had the silver."""
    graphs = toy_spatial_dataset().build()
    zone = graphs.nodes.require(ORIGIN).zone
    assert zone is not None
    destitute = HouseholdCohortAgent(
        cohort_id=f"{ORIGIN}:poor-smallholder",
        node_id=ORIGIN,
        cohort_class=CohortClass.POOR_SMALLHOLDER,
        zone=zone,
        households=200.0,
        adults=400.0,
        land_mu=800.0,
        grain_shi=0.0,
        silver_tael=0.0,
        debt_tael=0.0,
        movable_assets_tael=0.0,
    )
    destitute.permanent_migration_eligible = True
    destitute.temporary_migration_eligible = True
    population = HouseholdPopulation((destitute,))
    system = MigrationSystem(
        graphs=graphs,
        population=population,
        merchants=toy_merchant_layer(graphs),
        book=MarketBook({ORIGIN: 8.0, CHEAP: 2.0}),
        parameters=MIGRATION,
        household_parameters=HOUSEHOLDS,
    )
    before = (destitute.households, destitute.adults)

    system.step(_context())

    assert (destitute.households, destitute.adults) == before
    assert len(system.migrants) == 0
    destitute.check_balances()


def test_what_movers_carry_is_what_arrives_plus_what_the_road_took() -> None:
    system, population, _ = _world()
    _eligible(population, f"{ORIGIN}:poor-smallholder", permanent=True, temporary=False)
    ctx = _context()

    system.step(ctx)

    transit = ctx.logger.to_frame().filter(pl.col("event_type") == "MIGRATION_TRANSIT")
    assert transit.height == 1
    trigger = transit["trigger_json"].item()
    values = {
        key: float(pl.Series([trigger]).str.json_path_match(f"$.{key}").item())
        for key in (
            "grain_taken_shi",
            "grain_arrived_shi",
            "grain_lost_shi",
            "silver_taken_tael",
            "silver_arrived_tael",
            "silver_spent_or_lost_tael",
            "transit_risk",
        )
    }
    assert values["grain_taken_shi"] > 0.0
    assert values["grain_arrived_shi"] + values["grain_lost_shi"] == pytest.approx(
        values["grain_taken_shi"], rel=1e-9
    )
    assert values["silver_arrived_tael"] + values["silver_spent_or_lost_tael"] == pytest.approx(
        values["silver_taken_tael"], rel=1e-9
    )
    assert 0.0 <= values["transit_risk"] <= 1.0


def test_the_capacity_of_the_road_bounds_how_many_leave() -> None:
    system, population, graphs = _world()
    cohort = _eligible(population, f"{ORIGIN}:poor-smallholder", permanent=True, temporary=False)
    generous = MIGRATION.model_copy(
        update={"permanent_share_of_households_per_month": 1.0, "minimum_households_to_move": 1.0}
    )
    system = MigrationSystem(
        graphs=graphs,
        population=population,
        merchants=toy_merchant_layer(graphs),
        book=MarketBook({ORIGIN: 8.0, CHEAP: 2.0}),
        parameters=generous,
        household_parameters=HOUSEHOLDS,
    )
    capacity = system.edge_capacity(ORIGIN, CHEAP)
    before = cohort.households

    system.step(_context())

    assert before - cohort.households <= capacity + 1e-9


def test_a_household_that_cannot_pay_its_own_way_stays() -> None:
    """The affordability gate is silver per household, so it cannot be paid out of what stays."""
    graphs = toy_spatial_dataset().build()
    zone = graphs.nodes.require(ORIGIN).zone
    assert zone is not None
    cashless = HouseholdCohortAgent(
        cohort_id=f"{ORIGIN}:poor-smallholder",
        node_id=ORIGIN,
        cohort_class=CohortClass.POOR_SMALLHOLDER,
        zone=zone,
        households=1_000.0,
        adults=2_000.0,
        land_mu=4_000.0,
        grain_shi=0.0,
        silver_tael=100.0,  # 0.1 tael per household, against a declared 0.5 to move
        debt_tael=0.0,
        movable_assets_tael=0.0,
    )
    cashless.permanent_migration_eligible = True
    system = MigrationSystem(
        graphs=graphs,
        population=HouseholdPopulation((cashless,)),
        merchants=toy_merchant_layer(graphs),
        book=MarketBook({ORIGIN: 8.0, CHEAP: 2.0}),
        parameters=MIGRATION,
        household_parameters=HOUSEHOLDS,
    )

    system.step(_context())

    assert cashless.households == 1_000.0, "no household leaves on silver it does not have"
    cashless.check_balances()


def test_a_move_is_refused_when_the_destination_cannot_receive_that_class() -> None:
    """An internal node with no cohort of the movers' class is not a destination, not an exit."""
    graphs = toy_spatial_dataset().build()
    zone = graphs.nodes.require(ORIGIN).zone
    assert zone is not None
    mover = HouseholdCohortAgent(
        cohort_id=f"{ORIGIN}:wealthy-farmer",
        node_id=ORIGIN,
        cohort_class=CohortClass.WEALTHY_FARMER,
        zone=zone,
        households=400.0,
        adults=800.0,
        land_mu=12_000.0,
        grain_shi=4_000.0,
        silver_tael=4_000.0,
        debt_tael=0.0,
        movable_assets_tael=2_000.0,
    )
    mover.permanent_migration_eligible = True
    system = MigrationSystem(
        graphs=graphs,
        population=HouseholdPopulation((mover,)),
        merchants=toy_merchant_layer(graphs),
        book=MarketBook({ORIGIN: 8.0, CHEAP: 2.0}),
        parameters=MIGRATION,
        household_parameters=HOUSEHOLDS,
    )
    ctx = _context()

    system.step(ctx)

    assert mover.households == 400.0, "there is nobody of that class at the destination"
    events = ctx.logger.to_frame()
    assert events.filter(pl.col("event_type") == EXIT_EVENT).height == 0, (
        "a missing receiving cohort is not a regional exit"
    )
    mover.check_balances()


def test_the_rule_version_travels_with_every_migration_event() -> None:
    system, population, _ = _world()
    _eligible(population, f"{ORIGIN}:poor-smallholder", permanent=True, temporary=True)
    ctx = _context()

    system.step(ctx)

    events = ctx.logger.to_frame().filter(
        pl.col("event_type").is_in(
            [
                "MIGRATION_DEPARTURE",
                "MIGRATION_TRANSIT",
                "MIGRATION_ARRIVAL",
                SETTLEMENT_EVENT,
                TEMPORARY_EVENT,
            ]
        )
    )
    assert events.height >= 3
    assert set(events["rule_version"].unique()) == {
        MIGRATION_RULE_VERSION,
        "temporary-migration-v1",
    }
