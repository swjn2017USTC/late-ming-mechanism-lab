"""Trade-network disruption: the hook through which violence reaches the market.

P04 owns the market, not the violence. Armed groups arrive in P06, and when they do they must be
able to close a link or make it dangerous without editing the market's rules. So the market
consults a disruption regime for two multipliers per link — capacity and risk — and this module
supplies the regimes that exist today: no disruption, and a declared scaled regime with optional
blocked links.

The scaled regime is a scenario knob, not a claim about any year: it exists so the phase can ask
what transport cost and violence risk do to trade flow and price dispersion, and so P06 has a
bounded interface to drive.
"""

from __future__ import annotations

from typing import Final, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, model_validator

DISRUPTION_VERSION: Final[str] = "trade-disruption-v1"


@runtime_checkable
class TradeDisruption(Protocol):
    """How much of a link's capacity survives and how much riskier it has become."""

    @property
    def name(self) -> str: ...

    def risk_multiplier(self, origin: str, destination: str) -> float: ...

    def capacity_multiplier(self, origin: str, destination: str) -> float: ...


class CalmTrade(BaseModel):
    """Undisrupted trade: the reference regime for every counterfactual."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = "calm"

    def risk_multiplier(self, origin: str, destination: str) -> float:
        return 1.0

    def capacity_multiplier(self, origin: str, destination: str) -> float:
        return 1.0


class ScaledDisruption(BaseModel):
    """A declared regime: risk scaled up, capacity scaled down, named links cut.

    ``blocked_links`` are unordered pairs; a blocked link carries no traffic at all, which is
    what a road cut or a besieged town looks like to a merchant.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = "scaled"
    risk_scale: float = Field(ge=1.0)
    capacity_scale: float = Field(ge=0.0, le=1.0)
    blocked_links: tuple[tuple[str, str], ...] = ()

    @model_validator(mode="after")
    def _canonical_blocks(self) -> ScaledDisruption:
        for origin, destination in self.blocked_links:
            if origin == destination:
                raise ValueError(f"a link cannot connect {origin!r} to itself")
        return self

    @property
    def blocked(self) -> frozenset[tuple[str, str]]:
        return frozenset(_key(origin, destination) for origin, destination in self.blocked_links)

    def is_blocked(self, origin: str, destination: str) -> bool:
        return _key(origin, destination) in self.blocked

    def risk_multiplier(self, origin: str, destination: str) -> float:
        return self.risk_scale

    def capacity_multiplier(self, origin: str, destination: str) -> float:
        if self.is_blocked(origin, destination):
            return 0.0
        return self.capacity_scale


def _key(origin: str, destination: str) -> tuple[str, str]:
    return (origin, destination) if origin <= destination else (destination, origin)
