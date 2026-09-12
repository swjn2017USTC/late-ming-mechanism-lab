"""The military rules themselves: desertion, suppression, raids, formation, split and merge.

Each test drives one system over a small hand-built world and asks what the rule does, rather than
what the run happens to produce. The systems are stepped directly with a real tick context, so the
rules are exercised exactly as the kernel exercises them, without the rest of the economy moving
underneath.
"""

from __future__ import annotations

import polars as pl
import pytest

from late_ming_lab.actors.elites import EliteLayer
from late_ming_lab.actors.fixtures import toy_elite_layer
from late_ming_lab.actors.households import (
    CohortClass,
    HouseholdCohortAgent,
    HouseholdPopulation,
)
from late_ming_lab.actors.military import (
    ArmedBand,
    BandLayer,
    GovernmentMilitaryUnit,
    MilitaryLayer,
)
from late_ming_lab.core.clock import Clock
from late_ming_lab.core.config import SimulationConfig
from late_ming_lab.core.events import EventLogger
from late_ming_lab.core.rng import RngStreams
from late_ming_lab.core.tick import TickContext
from late_ming_lab.evidence.parameters import (
    core_default_band_parameters,
    core_default_military_parameters,
)
from late_ming_lab.networks.fixtures import toy_spatial_dataset
from late_ming_lab.networks.graphs import SpatialGraphs
from late_ming_lab.networks.nodes import AgrarianZone
from late_ming_lab.systems.military import (
    BandActionSystem,
    BandRecruitmentSystem,
    DeserterPool,
    DesertionSystem,
    ViolenceSystem,
    eligible_adult_pool,
)

NODE = "toy-sx-a"
MILITARY = core_default_military_parameters()
BANDS = core_default_band_parameters()


def _band_action(
    bands: BandLayer, population: HouseholdPopulation, *, elites: EliteLayer | None = None
) -> BandActionSystem:
    return BandActionSystem(
        bands=bands,
        military=MilitaryLayer((_unit(),)),
        population=population,
        elites=elites or _elites(),
        governments=None,
        graphs=_graphs(),
        parameters=BANDS,
        military_parameters=MILITARY,
    )


def _context(tick: int = 0, tick_count: int = 24) -> TickContext:
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


def _zone(node_id: str = NODE) -> AgrarianZone:
    """The agrarian zone of a toy node; the fixture always has one."""
    zone = _graphs().nodes.require(node_id).zone
    assert zone is not None
    return zone


def _cohort(
    adults: float = 1_000.0, *, grain: float = 2_000.0, eligible: bool = True
) -> HouseholdCohortAgent:
    cohort = HouseholdCohortAgent(
        cohort_id=f"{NODE}:poor-smallholder",
        node_id=NODE,
        cohort_class=CohortClass.POOR_SMALLHOLDER,
        zone=_zone(),
        households=adults / 2.0,
        adults=adults,
        land_mu=adults * 4.0,
        grain_shi=grain,
        silver_tael=10.0,
        debt_tael=5.0,
        movable_assets_tael=1_000.0,
    )
    cohort.recruitment_eligible = eligible
    return cohort


def _unit(troops: float = 300.0, *, grain: float = 1_000.0) -> GovernmentMilitaryUnit:
    return GovernmentMilitaryUnit(node_id=NODE, troops=troops, grain_shi=grain)


def _band(
    troops: float,
    *,
    band_id: str = "band-0001",
    node_id: str = NODE,
    grain: float = 0.0,
    arms: float = 0.0,
    cohesion: float = 0.9,
    network: float = 0.0,
    mobility: float = 0.5,
) -> ArmedBand:
    return ArmedBand(
        band_id=band_id,
        node_id=node_id,
        troops=troops,
        grain_shi=grain,
        arms_units=arms,
        cohesion=cohesion,
        network=network,
        mobility=mobility,
        territorial_access=(node_id,),
    )


def _graphs() -> SpatialGraphs:
    return toy_spatial_dataset().build()


def _elites() -> EliteLayer:
    return toy_elite_layer(_graphs().nodes)


def _empty_elites() -> EliteLayer:
    """Elite houses with no grain at all, for tests about a band that cannot feed itself."""
    from late_ming_lab.actors.elites import LocalEliteAgent

    return EliteLayer(
        tuple(
            LocalEliteAgent(
                node_id=node_id, households=1.0, land_mu=0.0, grain_shi=0.0, silver_tael=0.0
            )
            for node_id in ("toy-sx-a",)
        )
    )


def _trigger(frame: pl.DataFrame, field: str) -> float:
    """Sum one trigger field over a frame; 0.0 when the frame is empty."""
    if frame.is_empty():
        return 0.0
    return float(
        frame["trigger_json"].str.json_path_match(f"$.{field}").cast(pl.Float64).sum() or 0.0
    )


# --------------------------------------------------------------------------- desertion


def test_desertion_rises_with_arrears_and_hunger_and_is_capped() -> None:
    system = DesertionSystem(
        military=MilitaryLayer((_unit(),)),
        population=HouseholdPopulation((_cohort(),)),
        parameters=MILITARY,
        pool=DeserterPool(),
    )
    paid_and_fed = _unit()
    paid_and_fed.pay_shortfall_share = 0.0
    paid_and_fed.grain_shi = 1_000.0
    paid_and_fed.morale = 1.0

    unpaid = _unit()
    unpaid.pay_shortfall_share = 1.0
    unpaid.morale = 1.0
    unpaid.grain_shi = 1_000.0

    starving = _unit()
    starving.pay_shortfall_share = 0.0
    starving.grain_shi = 0.0

    collapsed = _unit()
    collapsed.pay_shortfall_share = 1.0
    collapsed.grain_shi = 0.0
    collapsed.morale = 0.0

    rates = [system.desertion_rate(unit) for unit in (paid_and_fed, unpaid, starving, collapsed)]

    assert rates[0] < rates[1], "arrears must raise desertion"
    assert rates[0] < rates[2], "hunger must raise desertion"
    assert rates[0] < rates[3]
    assert rates[1] < rates[3], "a broke, hungry, demoralized garrison loses the most"
    assert all(0.0 <= rate <= MILITARY.desertion_max_rate for rate in rates)


def test_desertion_routes_deserters_home_to_the_pool_and_out() -> None:
    """The three destinations are the declared shares, and the pool keeps its count."""
    population = HouseholdPopulation((_cohort(adults=1_000.0),))
    unit = _unit(troops=1_000.0)
    unit.pay_shortfall_share = 1.0
    unit.morale = 0.0
    pool = DeserterPool()
    system = DesertionSystem(
        military=MilitaryLayer((unit,)), population=population, parameters=MILITARY, pool=pool
    )
    ctx = _context()

    system.step(ctx)

    leaving = 1_000.0 - unit.troops
    assert leaving > 0.0
    assert unit.troops == pytest.approx(1_000.0 - leaving)
    assert population.require(f"{NODE}:poor-smallholder").adults > 1_000.0, "deserters go home"
    assert pool.at(NODE) == pytest.approx(leaving * MILITARY.deserter_band_share, rel=1e-9)
    routed = ctx.logger.to_frame().filter(pl.col("event_type") == "DESERTION_ROUTED")
    assert routed.height == 1
    dispersed = float(
        routed["trigger_json"].str.json_path_match("$.deserters_dispersed").cast(pl.Float64).item()
    )
    assert dispersed == pytest.approx(
        leaving * (1.0 - MILITARY.deserter_home_share - MILITARY.deserter_band_share), rel=1e-9
    )


# --------------------------------------------------------------------------- suppression


def test_a_band_with_grain_eats_and_one_that_cannot_raid_goes_hungry() -> None:
    population = HouseholdPopulation((_cohort(adults=1_000.0, grain=0.0),))
    fed = _band(500.0, grain=1_000.0, band_id="band-0001")
    hungry = _band(500.0, grain=0.0, band_id="band-0002")
    bands = BandLayer((fed, hungry))
    system = _band_action(bands, population, elites=_empty_elites())
    ctx = _context()

    system.step(ctx)

    events = ctx.logger.to_frame()
    fed_eaten = _trigger(events.filter(pl.col("agent_id") == "band-0001"), "food_eaten_shi")
    hungry_shortfall = _trigger(
        events.filter(pl.col("agent_id") == "band-0002"), "food_shortfall_shi"
    )
    assert fed_eaten > 0.0
    assert fed.grain_shi < 1_000.0
    assert hungry_shortfall > 0.0, "with nothing to take and nothing stored, the band goes hungry"


def _suppression_loss(*, arms: float) -> float:
    """Members a 300-strong garrison removes from a 500-strong band in one month."""
    population = HouseholdPopulation((_cohort(adults=1_000.0),))
    band = _band(500.0, arms=arms)
    system = ViolenceSystem(
        bands=BandLayer((band,)),
        military=MilitaryLayer((_unit(),)),
        population=population,
        military_parameters=MILITARY,
        band_parameters=BANDS,
    )
    system.step(_context())
    return 500.0 - band.troops


def test_suppression_takes_less_from_a_better_armed_band() -> None:
    """The same garrison against the same band, once unarmed and once fully armed."""
    unarmed_loss = _suppression_loss(arms=0.0)
    armed_loss = _suppression_loss(arms=500.0 * BANDS.arms_per_member_for_full_capability)

    assert unarmed_loss > 0.0, "the garrison is a real threat"
    assert armed_loss < unarmed_loss, "arms must reduce what suppression takes"
    assert armed_loss == pytest.approx(
        unarmed_loss * (1.0 - MILITARY.suppression_arms_mitigation), rel=1e-6
    )


# --------------------------------------------------------------------------- raids


def test_a_raid_takes_hunger_into_account_and_the_victims_lose_what_the_band_gains() -> None:
    population = HouseholdPopulation((_cohort(adults=100.0, grain=40.0),))
    band = _band(200.0, grain=0.0)
    system = _band_action(BandLayer((band,)), population, elites=_empty_elites())
    ctx = _context()

    system.step(ctx)

    need = 200.0 * BANDS.food_shi_per_member_month
    allowance = need * BANDS.raid_extraction_multiple
    cohort = population.require(f"{NODE}:poor-smallholder")
    assert cohort.grain_shi == pytest.approx(0.0), "a small store is taken entirely"
    # 40 shi were available, so that is all there was to take; the band ate what it needed.
    taken = 40.0
    assert allowance > taken, "the allowance exceeds the store, which is the point of the cap"
    food = ctx.logger.to_frame().filter(pl.col("event_type") == "MILITARY_FOOD_CONSUMED")
    eaten = float(
        food["trigger_json"].str.json_path_match("$.food_eaten_shi").cast(pl.Float64).sum()
    )
    assert eaten == pytest.approx(taken)


def test_band_formations_and_splits_leave_the_people_and_the_food_with_someone() -> None:
    """A split conserves troops, grain and arms between parent and splinter."""
    parent = _band(500.0, grain=200.0, arms=10.0, cohesion=0.3)
    bands = BandLayer((parent,))
    system = ViolenceSystem(
        bands=bands,
        military=MilitaryLayer((_unit(troops=0.0),)),
        population=HouseholdPopulation((_cohort(),)),
        military_parameters=MILITARY,
        band_parameters=BANDS,
    )
    ctx = _context()
    before = (parent.troops, parent.grain_shi, parent.arms_units)

    system.step(ctx)

    survivors = tuple(bands)
    assert len(survivors) == 2, "a big, incoherent band fractures"
    assert sum(band.troops for band in survivors) == pytest.approx(before[0])
    assert sum(band.grain_shi for band in survivors) == pytest.approx(before[1])
    assert sum(band.arms_units for band in survivors) == pytest.approx(before[2])
    assert all(band.troops > 0.0 for band in survivors)


def test_two_cohesive_bands_in_one_place_become_one_without_losing_anyone() -> None:
    first = _band(300.0, grain=100.0, arms=5.0, cohesion=0.8, band_id="band-0001")
    second = _band(200.0, grain=50.0, arms=3.0, cohesion=0.8, band_id="band-0002")
    bands = BandLayer((first, second))
    system = ViolenceSystem(
        bands=bands,
        military=MilitaryLayer((_unit(troops=0.0),)),
        population=HouseholdPopulation((_cohort(),)),
        military_parameters=MILITARY,
        band_parameters=BANDS,
    )
    ctx = _context()
    troops, grain, arms = 500.0, 150.0, 8.0

    system.step(ctx)

    assert len(bands) == 1
    survivor = next(iter(bands))
    assert survivor.troops == pytest.approx(troops)
    assert survivor.grain_shi == pytest.approx(grain)
    assert survivor.arms_units == pytest.approx(arms)


def test_a_band_too_small_to_continue_is_disbanded_and_its_people_go_home() -> None:
    population = HouseholdPopulation((_cohort(adults=1_000.0),))
    band = _band(BANDS.dissolve_troops_below - 1.0, grain=25.0)
    bands = BandLayer((band,))
    system = ViolenceSystem(
        bands=bands,
        military=MilitaryLayer((_unit(),)),
        population=population,
        military_parameters=MILITARY,
        band_parameters=BANDS,
    )
    ctx = _context()
    before = population.require(f"{NODE}:poor-smallholder").adults

    system.step(ctx)

    assert len(bands) == 0
    disbanded = _trigger(
        ctx.logger.to_frame().filter(pl.col("event_type") == "BAND_DISSOLVED"),
        "troops_disbanded",
    )
    after = population.require(f"{NODE}:poor-smallholder").adults
    assert disbanded > 0.0, "the fixture must actually disband somebody"
    assert after - before == pytest.approx(disbanded), "every disbanded member goes home"


# ----------------------------------------------------------------- formation and recruitment


def test_no_band_forms_below_the_minimum_size_or_without_distress() -> None:
    calm = HouseholdPopulation((_cohort(adults=200.0),))
    pool = DeserterPool()
    pool.add(NODE, BANDS.minimum_formation_troops - 1.0)
    bands = BandLayer()
    system = BandRecruitmentSystem(
        military=MilitaryLayer((_unit(),)),
        bands=bands,
        population=calm,
        parameters=MILITARY,
        band_parameters=BANDS,
        pool=pool,
    )
    ctx = _context()

    system.step(ctx)

    assert len(bands) == 0, "too few deserters and no distress is not a band"
    assert pool.at(NODE) == pytest.approx(BANDS.minimum_formation_troops - 1.0), "but they wait"


def test_unorganized_deserters_form_a_band_once_they_are_enough() -> None:
    population = HouseholdPopulation((_cohort(adults=200.0),))
    pool = DeserterPool()
    pool.add(NODE, BANDS.minimum_formation_troops + 10.0)
    bands = BandLayer()
    system = BandRecruitmentSystem(
        military=MilitaryLayer((_unit(),)),
        bands=bands,
        population=population,
        parameters=MILITARY,
        band_parameters=BANDS,
        pool=pool,
    )
    ctx = _context()

    system.step(ctx)

    assert len(bands) == 1
    assert next(iter(bands)).troops == pytest.approx(BANDS.minimum_formation_troops + 10.0)
    assert pool.at(NODE) == 0.0
    assert population.require(f"{NODE}:poor-smallholder").adults == 200.0, (
        "deserters who were already off the books are not levied from households again"
    )


def test_the_garrison_levies_from_every_adult_and_a_band_only_from_the_distressed() -> None:
    """Two declared pools over the same households, checked on the pool function itself."""
    eligible = _cohort(adults=100.0, eligible=True)
    ineligible = _cohort(adults=100.0, eligible=False)
    ineligible.cohort_id = f"{NODE}:middle-smallholder"
    population = HouseholdPopulation((eligible, ineligible))

    assert eligible_adult_pool(population, NODE) == pytest.approx(100.0)
    assert eligible_adult_pool(population, NODE, distress_eligible=False) == pytest.approx(200.0)


def test_a_harassed_small_band_moves_and_a_large_fed_one_stays() -> None:
    population = HouseholdPopulation(
        (
            _cohort(adults=100.0, grain=100.0),
            _neighbour_cohort(grain=5_000.0),
        )
    )
    small = _band(60.0, grain=1_000.0, band_id="band-0001", network=0.0)
    large = _band(2_000.0, grain=1_000.0, band_id="band-0002", network=0.0)
    bands = BandLayer((small, large))
    system = _band_action(bands, population)
    ctx = _context()

    system.step(ctx)

    moved = ctx.logger.to_frame().filter(pl.col("event_type") == "BAND_MOVE")
    assert small.node_id == "toy-sx-b", "a band the garrison can wear down walks to more grain"
    assert large.node_id == NODE, "a band bigger than the threat stays where it feeds"
    assert set(moved["agent_id"].unique()) == {"band-0001"}


def _neighbour_cohort(*, grain: float) -> HouseholdCohortAgent:
    cohort = HouseholdCohortAgent(
        cohort_id="toy-sx-b:poor-smallholder",
        node_id="toy-sx-b",
        cohort_class=CohortClass.POOR_SMALLHOLDER,
        zone=_zone("toy-sx-b"),
        households=500.0,
        adults=1_000.0,
        land_mu=4_000.0,
        grain_shi=grain,
        silver_tael=10.0,
        debt_tael=5.0,
        movable_assets_tael=1_000.0,
    )
    return cohort
