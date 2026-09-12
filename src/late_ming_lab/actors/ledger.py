"""Shared double-entry accounting for every actor that holds a balance sheet.

Household cohorts, merchant houses and local elites all move the same kind of quantities —
grain, silver, land, debt, goods — and all of them must obey the same two rules:

- **no negative balance**: every field is validated on assignment, and a change that would
  produce one is refused *before* anything is written;
- **no unsourced balance change**: balances move only through :meth:`LedgerAgent._apply`, which
  records the delta, so a balance can always be reconciled against the movements that explain it.

The trigger keys in :data:`LEDGER_KEYS` are the contract between the actors and the event log:
wherever a balance moves, the explaining event carries the matching delta under one of these
names, and the run-scale invariants in `tests/invariants/` rebuild balances from the log alone.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from types import MappingProxyType

from pydantic import BaseModel, ConfigDict, PrivateAttr

GRAIN_DELTA = "grain_delta_shi"
SILVER_DELTA = "silver_delta_tael"
LAND_DELTA = "land_delta_mu"
DEBT_DELTA = "debt_delta_tael"
ASSETS_DELTA = "assets_delta_tael"
TAX_ARREARS_DELTA = "tax_arrears_delta_tael"
TROOPS_DELTA = "troops_delta_people"
ARMS_DELTA = "arms_delta_units"
PAY_ARREARS_DELTA = "pay_arrears_delta_tael"
ADULTS_DELTA = "adults_delta_people"

#: The trigger keys every balance movement is recorded under.
LEDGER_KEYS: tuple[str, ...] = (
    GRAIN_DELTA,
    SILVER_DELTA,
    LAND_DELTA,
    DEBT_DELTA,
    ASSETS_DELTA,
    TAX_ARREARS_DELTA,
    TROOPS_DELTA,
    ARMS_DELTA,
    PAY_ARREARS_DELTA,
    ADULTS_DELTA,
)

#: Balance field name -> the trigger key that records its movements.
LEDGER_KEY_BY_FIELD: Mapping[str, str] = MappingProxyType(
    {
        "grain_shi": GRAIN_DELTA,
        "silver_tael": SILVER_DELTA,
        "land_mu": LAND_DELTA,
        "debt_tael": DEBT_DELTA,
        "movable_assets_tael": ASSETS_DELTA,
        "goods_tael": ASSETS_DELTA,
        "tax_arrears_tael": TAX_ARREARS_DELTA,
        "troops": TROOPS_DELTA,
        "arms_units": ARMS_DELTA,
        "pay_arrears_tael": PAY_ARREARS_DELTA,
        "adults": ADULTS_DELTA,
    }
)

#: Keyword used by :meth:`LedgerAgent._apply` -> balance field name.
DELTA_FIELDS: Mapping[str, str] = MappingProxyType(
    {
        "grain": "grain_shi",
        "silver": "silver_tael",
        "land": "land_mu",
        "debt": "debt_tael",
        "assets": "movable_assets_tael",
        "goods": "goods_tael",
        "tax_arrears": "tax_arrears_tael",
        "troops": "troops",
        "arms": "arms_units",
        "pay_arrears": "pay_arrears_tael",
        "adults": "adults",
    }
)

BALANCE_TOLERANCE = 1e-9


class LedgerError(RuntimeError):
    """Raised when an actor's balances disagree with the movements it recorded."""


class LedgerAgent(BaseModel):
    """Base class for actors holding a reconciled balance sheet."""

    model_config = ConfigDict(validate_assignment=True, extra="forbid")

    _ledger: dict[str, float] = PrivateAttr(default_factory=dict)
    _initial: dict[str, float] = PrivateAttr(default_factory=dict)

    @property
    def balance_fields(self) -> tuple[str, ...]:
        """Balance fields this actor actually holds."""
        return tuple(field for field in LEDGER_KEY_BY_FIELD if field in type(self).model_fields)

    def model_post_init(self, _context: object) -> None:
        self._ledger = {LEDGER_KEY_BY_FIELD[field]: 0.0 for field in self.balance_fields}
        self._initial = {field: float(getattr(self, field)) for field in self.balance_fields}

    @property
    def ledger_deltas(self) -> Mapping[str, float]:
        return MappingProxyType(self._ledger)

    @property
    def initial_balances(self) -> Mapping[str, float]:
        return MappingProxyType(self._initial)

    def _apply(
        self,
        *,
        grain: float = 0.0,
        silver: float = 0.0,
        land: float = 0.0,
        debt: float = 0.0,
        assets: float = 0.0,
        goods: float = 0.0,
        tax_arrears: float = 0.0,
        troops: float = 0.0,
        arms: float = 0.0,
        pay_arrears: float = 0.0,
        adults: float = 0.0,
        impacts: tuple[tuple[str, float], ...] = (),
    ) -> None:
        """Apply a balance change atomically; the only place balances ever move."""
        changes = {
            "grain": grain,
            "silver": silver,
            "land": land,
            "debt": debt,
            "assets": assets,
            "goods": goods,
            "tax_arrears": tax_arrears,
            "troops": troops,
            "arms": arms,
            "pay_arrears": pay_arrears,
            "adults": adults,
        }
        candidates: list[tuple[str, float]] = []
        for keyword, delta in changes.items():
            field = DELTA_FIELDS[keyword]
            if field not in self.balance_fields or delta == 0.0:
                continue
            value = float(getattr(self, field)) + delta
            if not math.isfinite(value) or value < 0.0:
                raise LedgerError(
                    f"{self.ledger_name}: refusing an impossible balance change; {field} "
                    f"would become {value}"
                )
            candidates.append((field, value))
        for field, value in candidates:
            setattr(self, field, value)
        for key, value in impacts:
            self._ledger[key] = self._ledger[key] + value

    @property
    def ledger_name(self) -> str:
        """Identity used in error messages; subclasses override."""
        return type(self).__name__

    def check_balances(self) -> None:
        """Reconcile every balance against the movements recorded for it."""
        for field in self.balance_fields:
            key = LEDGER_KEY_BY_FIELD[field]
            expected = self._initial[field] + self._ledger[key]
            actual = float(getattr(self, field))
            if not math.isclose(actual, expected, rel_tol=1e-9, abs_tol=BALANCE_TOLERANCE):
                raise LedgerError(
                    f"{self.ledger_name}: {field} is {actual} but the recorded movements "
                    f"account for {expected}; a balance changed without an entry"
                )
