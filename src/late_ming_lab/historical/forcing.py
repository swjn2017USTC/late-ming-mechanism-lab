"""Observed climate forcing for the historical core: an annual index, and a declared allocator.

The record gives *events*: a drought, a famine, a crop failure, a locust outbreak, each with a place
and a date. The model needs a monthly severity per node. Two things therefore have to be separated,
and this module is where that happens:

```text
observed      the annual index: how many agricultural-category events the record carries for a
              seat in a year, turned into [0, 1] by declared weights and saturation counts. This is
              the only part of the forcing that comes from the record, and it is what the repository
              stores.
allocated     the monthly severity: the annual index shaped by the seasonal profile of the
              recorded months, or spread evenly in the ablation. This is a *model construction*
              with parameter cards, computed at run time, never written down as an observation.
```

Three properties are enforced rather than promised. A node-year the record does not cover is either
refused (the policy names the exact node-periods) or imputed as zero **and counted**, never silently
zeroed. The allocator's seasonal weights are the only part of it that rests on the record, and the
uniform mode exists so an experiment can remove them. And the series refuses a grade-``S``
provenance, so an invented series cannot enter through the observed door.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Final

import numpy as np
import polars as pl

from late_ming_lab.core.clock import Month
from late_ming_lab.evidence.grades import DataProvenance, EvidenceGrade
from late_ming_lab.evidence.parameters import HistoricalCoreParameters
from late_ming_lab.historical.provenance import WINDOW_END, WINDOW_START, reaches_derived
from late_ming_lab.historical.selection import (
    CLIMATE_RADIUS_KM,
    assign_events_to_seats,
)
from late_ming_lab.networks.nodes import CountyNode
from late_ming_lab.systems.climate import ClimateCoverageError, ClimateMode, ClimateSample

#: Columns of the stored annual index. ``records`` says whether the record covers the node-year at
#: all, which is what separates "nothing was recorded" from "nothing happened".
ANNUAL_COLUMNS: Final[tuple[str, ...]] = (
    "node_id",
    "year",
    "severity_index",
    "drought_events",
    "famine_events",
    "crop_events",
    "pest_events",
    "total_events",
    "records",
)

CATEGORY_COLUMNS: Final[tuple[str, ...]] = (
    "drought_events",
    "famine_events",
    "crop_events",
    "pest_events",
)

#: The event codes whose counts feed the index, from the REACHES coding guide.
CATEGORY_CODES: Final[dict[str, str]] = {
    "drought_events": "30",
    "famine_events": "35",
    "crop_events": "33",
    "pest_events": "32",
}


class MissingCoveragePolicy(StrEnum):
    """What to do with a node-year the record does not cover."""

    REFUSE = "refuse"
    ZERO = "zero"


class AllocationMode(StrEnum):
    """How the annual index becomes a monthly severity."""

    SEASONAL = "seasonal"
    UNIFORM = "uniform"


def severity_index(
    *, drought: int, famine: int, crop: int, pest: int, parameters: HistoricalCoreParameters
) -> float:
    """The annual index of one node-year, from its category counts.

    Each category contributes its weight once its count reaches the declared saturation, and
    proportionally before that; the sum is capped at one. The function is pure so a test can check
    the arithmetic without a dataset, and the weights are parameter cards rather than numbers here.
    """
    components = (
        (drought, parameters.drought_weight, parameters.drought_saturation_events),
        (famine, parameters.famine_weight, parameters.famine_saturation_events),
        (crop, parameters.crop_weight, parameters.crop_saturation_events),
        (pest, parameters.pest_weight, parameters.pest_saturation_events),
    )
    total = sum(weight * min(count / saturation, 1.0) for count, weight, saturation in components)
    return float(min(total, 1.0))


def build_annual_index(
    nodes: pl.DataFrame,
    events: pl.DataFrame,
    parameters: HistoricalCoreParameters,
    *,
    radius_km: float = CLIMATE_RADIUS_KM,
) -> pl.DataFrame:
    """One row per county node and year of the window, with its counts and its index.

    Every node-year of the window appears, whether or not the record covers it: a node-year with no
    assigned event carries ``records = False``, which is the flag the allocator's coverage policy
    reads. That is the difference between this table and a sparse count table, and it is why the
    coverage report can name uncovered periods instead of inferring them.
    """
    counties = nodes.filter(pl.col("kind") == "county").select(
        pl.col("node_id").alias("sys_id"), "latitude", "longitude"
    )
    if counties.height == 0:
        raise ValueError("the annual index needs at least one county node with coordinates")
    assigned = assign_events_to_seats(counties, events, radius_km=radius_km).rename(
        {"sys_id": "node_id"}
    )
    counts = (
        assigned.filter(pl.col("node_id").is_not_null())
        .group_by("node_id", "year")
        .agg(
            *[
                (pl.col("category") == code).sum().cast(pl.Int32).alias(name)
                for name, code in CATEGORY_CODES.items()
            ],
            pl.len().cast(pl.Int32).alias("total_events"),
        )
        .with_columns(pl.lit(True).alias("records"))
    )
    grid = (
        counties.select(pl.col("sys_id").alias("node_id"))
        .join(
            pl.DataFrame({"year": list(range(WINDOW_START, WINDOW_END + 1))}),
            how="cross",
        )
        .sort("node_id", "year")
    )
    joined = (
        grid.join(counts, on=["node_id", "year"], how="left")
        .with_columns(
            pl.col("records").fill_null(False),
            *[pl.col(name).fill_null(0) for name in CATEGORY_COLUMNS],
            pl.col("total_events").fill_null(0),
        )
        .with_columns(
            pl.struct([*CATEGORY_COLUMNS])
            .map_elements(
                lambda row: severity_index(
                    drought=int(row["drought_events"]),
                    famine=int(row["famine_events"]),
                    crop=int(row["crop_events"]),
                    pest=int(row["pest_events"]),
                    parameters=parameters,
                ),
                return_dtype=pl.Float64,
            )
            .alias("severity_index")
        )
    )
    return joined.select(*ANNUAL_COLUMNS)


def annual_provenance() -> DataProvenance:
    """Provenance for the stored annual index: derived from the REACHES record, never a series."""
    return reaches_derived(
        note=(
            "Weights and saturation counts are declared parameter cards, not measurements: the "
            "index orders years and places, it does not measure rainfall."
        )
    )


class AllocatedObservedClimate:
    """The observed annual index allocated across months by a declared, ablatable profile."""

    mode: ClimateMode = ClimateMode.OBSERVED_HISTORICAL
    rule_version: str = "climate-allocated-observed-v1"

    def __init__(
        self,
        annual: pl.DataFrame,
        parameters: HistoricalCoreParameters,
        *,
        coverage_policy: MissingCoveragePolicy = MissingCoveragePolicy.ZERO,
        allocation_mode: AllocationMode = AllocationMode.SEASONAL,
        series_id: str,
        provenance: DataProvenance | None = None,
        max_reported_gaps: int = 8,
    ) -> None:
        provenance = provenance or annual_provenance()
        if provenance.grade is EvidenceGrade.S:
            raise ValueError(
                "an observed series must be graded A, B, C or D; a series graded S is an invented "
                "series and belongs in the synthetic mode"
            )
        missing = [column for column in ANNUAL_COLUMNS if column not in annual.columns]
        if missing:
            raise ValueError(f"annual index is missing columns: {', '.join(missing)}")
        self.series_id = series_id
        self.provenance = provenance
        self.parameters = parameters
        self.allocation_mode = allocation_mode
        self.coverage_policy = coverage_policy
        self._index: dict[tuple[str, int], float] = {}
        uncovered: list[tuple[str, int]] = []
        for row in annual.select(list(ANNUAL_COLUMNS)).iter_rows(named=True):
            key = (str(row["node_id"]), int(row["year"]))
            if key in self._index:
                raise ValueError(f"annual index repeats {key[0]} {key[1]}")
            severity = float(row["severity_index"])
            if not 0.0 <= severity <= 1.0 or not np.isfinite(severity):
                raise ValueError(f"annual index has severity {severity} for {key[0]} {key[1]}")
            self._index[key] = severity
            if not bool(row["records"]):
                uncovered.append(key)
        self.uncovered_node_years: tuple[tuple[str, int], ...] = tuple(sorted(uncovered))
        if coverage_policy is MissingCoveragePolicy.REFUSE and self.uncovered_node_years:
            named = ", ".join(
                f"{node_id} {year}"
                for node_id, year in self.uncovered_node_years[:max_reported_gaps]
            )
            more = len(self.uncovered_node_years) - max_reported_gaps
            suffix = f" and {more} more" if more > 0 else ""
            raise ClimateCoverageError(
                f"observed forcing refuses {self.series_id}: {len(self.uncovered_node_years)} "
                f"node-year(s) carry no record ({named}{suffix}). Either select nodes and "
                "years the record covers, or declare the zero-imputation policy and report the "
                "imputed share."
            )
        profile = self._month_weights(parameters, allocation_mode)
        self._weights: dict[int, float] = profile

    @property
    def weights(self) -> dict[int, float]:
        """The monthly weights actually in use, so a report can print them."""
        return dict(self._weights)

    @property
    def imputed_node_years(self) -> tuple[tuple[str, int], ...]:
        """Node-years whose severity is an imputation rather than a record."""
        return self.uncovered_node_years

    @staticmethod
    def _month_weights(
        parameters: HistoricalCoreParameters, mode: AllocationMode
    ) -> dict[int, float]:
        if mode is AllocationMode.UNIFORM:
            return {month: 1.0 / 12.0 for month in range(1, 13)}
        declared = parameters.monthly_allocation_profile
        total = sum(declared.values())
        if total <= 0:
            raise ValueError("the seasonal profile must have a positive total")
        return {month: declared.get(month, 0.0) / total for month in range(1, 13)}

    def annual_severity(self, node_id: str, year: int) -> float:
        """The stored annual index for a node-year, or a coverage error when it is absent."""
        try:
            return self._index[(node_id, year)]
        except KeyError as error:
            raise ClimateCoverageError(
                f"series {self.series_id!r} has no annual value for {node_id} {year}"
            ) from error

    def monthly_severity(self, node_id: str, year: int, month: int) -> float:
        """The allocated severity: the annual index shaped by the month's weight.

        The weights are normalised shares of the year, so ``severity = index x weight x 12`` gives a
        monthly mean equal to the annual index in both allocation modes - until a month clips at
        one. Clipping compresses the extreme years, and how much it compresses them is measured
        rather than asserted: :meth:`clipped_node_months` counts the node-months that hit the
        ceiling, and the summary reports the count. A level claim about peak severity in the worst
        years is therefore not preserved by construction, and the count says how often that bites.
        """
        annual = self.annual_severity(node_id, year)
        weight = self._weights.get(month, 0.0)
        return float(min(1.0, annual * weight * 12.0))

    def shock(self, *, node: CountyNode, month: Month, rng: np.random.Generator) -> ClimateSample:
        """The severity the kernel reads for one node and month; consumes no randomness."""
        del rng
        return ClimateSample(severity=self.monthly_severity(node.node_id, month.year, month.month))

    def clipped_node_months(self) -> int:
        """How many node-months the allocator had to clip at severity one."""
        clipped = 0
        for node_id, year in self._index:
            for month in range(1, 13):
                annual = self._index[(node_id, year)]
                if annual * self._weights.get(month, 0.0) * 12.0 > 1.0:
                    clipped += 1
        return clipped

    def summary(self) -> dict[str, Any]:
        """What a run's provenance should record about the forcing it used."""
        return {
            "series_id": self.series_id,
            "allocation_mode": self.allocation_mode.value,
            "coverage_policy": self.coverage_policy.value,
            "node_years": len(self._index),
            "imputed_node_years": len(self.uncovered_node_years),
            "imputed_share": (
                len(self.uncovered_node_years) / len(self._index) if self._index else 0.0
            ),
            "clipped_node_months": self.clipped_node_months(),
            "provenance_grade": self.provenance.grade.value,
            "provenance_source": self.provenance.source_id,
            "provenance_locator": self.provenance.locator,
        }
