"""Rule-based extraction policies: how hard the county assesses and how hard it collects.

A policy answers two separate questions, and the model keeps them separate because they can move
independently: how much is *assessed* against the tax base, and how much *effort* is spent
extracting it. A county can assess more without collecting more, and the phase's experiment is
built to see exactly that if it happens.

Both implementations are declared rules, not findings. Nothing here concludes that raising
pressure erodes the base; that hypothesis belongs to a later mechanism phase, and P05 exists to
supply the measurements it would need.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field


@runtime_checkable
class ExtractionPolicy(Protocol):
    """How a county decides its assessment rate and its collection effort."""

    @property
    def name(self) -> str: ...

    def assessment_rate(
        self, *, nominal_pressure: float, arrears_tael: float, quota_tael: float
    ) -> float: ...

    def collection_effort(
        self,
        *,
        nominal_pressure: float,
        arrears_tael: float,
        quota_tael: float,
        coercion_capacity: float,
    ) -> float: ...


class FixedExtraction(BaseModel):
    """One declared rate and one declared effort, whatever the arrears look like."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = "fixed"
    effort: float = Field(ge=0.0, le=1.0)

    def assessment_rate(
        self, *, nominal_pressure: float, arrears_tael: float, quota_tael: float
    ) -> float:
        return nominal_pressure

    def collection_effort(
        self,
        *,
        nominal_pressure: float,
        arrears_tael: float,
        quota_tael: float,
        coercion_capacity: float,
    ) -> float:
        return self.effort


class ArrearsEscalation(BaseModel):
    """Raise the rate and the effort when arrears accumulate against the quota.

    ``arrears_weight`` says how much of a growing arrears stock turns into extra pressure, and
    ``effort_ceiling`` caps the effort — an apparatus cannot work harder than full effort, and the
    coercion capacity is the part of that ceiling it can actually enforce.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = "arrears-escalation"
    base_effort: float = Field(ge=0.0, le=1.0)
    arrears_weight: float = Field(ge=0.0)
    effort_ceiling: float = Field(gt=0.0, le=1.0)

    def _arrears_pressure(self, *, arrears_tael: float, quota_tael: float) -> float:
        if quota_tael <= 0.0:
            return 0.0
        return arrears_tael / quota_tael

    def assessment_rate(
        self, *, nominal_pressure: float, arrears_tael: float, quota_tael: float
    ) -> float:
        escalation = 1.0 + self.arrears_weight * self._arrears_pressure(
            arrears_tael=arrears_tael, quota_tael=quota_tael
        )
        return nominal_pressure * escalation

    def collection_effort(
        self,
        *,
        nominal_pressure: float,
        arrears_tael: float,
        quota_tael: float,
        coercion_capacity: float,
    ) -> float:
        rise = self.arrears_weight * self._arrears_pressure(
            arrears_tael=arrears_tael, quota_tael=quota_tael
        )
        enforceable = min(self.effort_ceiling, max(coercion_capacity, self.base_effort))
        return min(self.effort_ceiling, enforceable + rise)
