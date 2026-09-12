"""Shared fixtures: the toy dataset, its graphs, the calendar, and test counterparties.

Unit tests of the household ladder must not require a whole market to exist, so the two doubles
here implement the actor protocols with declared, unlimited or explicitly limited behaviour. They
are test doubles and are named as such: nothing in `src/` may import them.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from late_ming_lab.actors.exchange import (
    CreditDecision,
    NodeBound,
    TradeOutcome,
)
from late_ming_lab.core.clock import Clock, Month, Period
from late_ming_lab.core.config import SimulationConfig
from late_ming_lab.core.events import EventLogger
from late_ming_lab.core.rng import RngStreams
from late_ming_lab.core.tick import TickContext, TickPhase
from late_ming_lab.networks.dataset import SpatialDataset
from late_ming_lab.networks.fixtures import toy_spatial_dataset
from late_ming_lab.networks.graphs import SpatialGraphs
from late_ming_lab.systems.calendar import AgriculturalCalendar, core_default_calendar


@pytest.fixture
def toy_dataset() -> SpatialDataset:
    return toy_spatial_dataset()


@pytest.fixture
def toy_graphs(toy_dataset: SpatialDataset) -> SpatialGraphs:
    return toy_dataset.build()


@pytest.fixture
def calendar() -> AgriculturalCalendar:
    return core_default_calendar()


@pytest.fixture
def short_config() -> SimulationConfig:
    return SimulationConfig.model_validate({"tick_count": 6, "warmup_ticks": 2})


@pytest.fixture
def tick_context(short_config: SimulationConfig) -> TickContext:
    """A real tick context for the first tick, so unit tests exercise the real event log."""
    clock = Clock.from_config(short_config)
    return TickContext(
        config=short_config,
        clock=clock,
        tick=0,
        month=Month(year=short_config.start_year, month=short_config.start_month),
        period=Period.WARMUP,
        rng=RngStreams(short_config.root_seed),
        logger=EventLogger(tick_count=short_config.tick_count),
    )


@dataclass
class StubMarket:
    """Unlimited grain at a fixed price: a market, minus its constraints."""

    price_tael_per_shi: float = 1.5
    grain_shi: float = 1_000_000.0
    silver_tael: float = 1_000_000.0
    name: str = "stub-market"

    def buy_grain(
        self,
        ctx: TickContext,
        buyer: NodeBound,
        shi_wanted: float,
        max_silver: float,
        *,
        phase: TickPhase = TickPhase.HOUSEHOLD_CONSUMPTION,
    ) -> TradeOutcome:
        del phase  # the stub has no phase-dependent behaviour; the protocol does
        cost = min(shi_wanted * self.price_tael_per_shi, max_silver, self.grain_shi)
        if cost <= 0.0:
            return TradeOutcome(quantity=0.0, value_tael=0.0, counterparty_id=self.name)
        shi = cost / self.price_tael_per_shi
        self.grain_shi -= shi
        self.silver_tael += cost
        return TradeOutcome(quantity=shi, value_tael=cost, counterparty_id=self.name)

    def buy_movables(
        self,
        ctx: TickContext,
        seller: NodeBound,
        wanted_tael: float,
        max_tael: float,
        *,
        phase: TickPhase = TickPhase.HOUSEHOLD_CONSUMPTION,
    ) -> TradeOutcome:
        del phase
        proceeds = min(wanted_tael, max_tael, self.silver_tael)
        self.silver_tael -= proceeds
        return TradeOutcome(quantity=proceeds, value_tael=proceeds, counterparty_id=self.name)


@dataclass
class StubCredit:
    """A lender with a declared collateral rule and unlimited silver."""

    land_price_tael_per_mu: float = 2.5
    loan_to_value: float = 0.5
    silver_tael: float = 1_000_000.0
    name: str = "stub-lender"

    def borrow(
        self,
        ctx: TickContext,
        borrower: NodeBound,
        requested_tael: float,
        collateral_tael: float,
        existing_debt_tael: float,
    ) -> CreditDecision:
        capacity = max(
            0.0, min(self.loan_to_value * collateral_tael - existing_debt_tael, self.silver_tael)
        )
        granted = max(0.0, min(requested_tael, capacity))
        self.silver_tael -= granted
        return CreditDecision(granted_tael=granted, capacity_tael=capacity, lender_id=self.name)

    def sell_land(
        self, ctx: TickContext, seller: NodeBound, wanted_tael: float, max_mu: float
    ) -> TradeOutcome:
        paid = min(wanted_tael, self.silver_tael)
        mu = min(max_mu, paid / self.land_price_tael_per_mu)
        if mu <= 0.0:
            return TradeOutcome(quantity=0.0, value_tael=0.0, counterparty_id=self.name)
        paid = min(mu * self.land_price_tael_per_mu, self.silver_tael)
        mu = min(mu, paid / self.land_price_tael_per_mu)
        self.silver_tael -= paid
        return TradeOutcome(quantity=mu, value_tael=paid, counterparty_id=self.name)


@pytest.fixture
def market() -> StubMarket:
    return StubMarket()


@pytest.fixture
def credit() -> StubCredit:
    return StubCredit()


@pytest.fixture
def market_factory() -> type[StubMarket]:
    """The double's class, so a test can build a constrained market."""
    return StubMarket


@pytest.fixture
def credit_factory() -> type[StubCredit]:
    """The double's class, so a test can build a lender with a different rule."""
    return StubCredit
