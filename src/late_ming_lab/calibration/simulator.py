"""The ABC simulator wrapper: one parameter draw becomes one sandbox run and one objective vector.

The runner is deliberately the P07 sandbox and nothing else. :func:`build_integrated_economy` builds
the same economy, with the same systems in the same tick order, that the P07 scenarios run; a draw
only replaces the parameter sets by name. So a calibration run is a scenario run of the existing
model, not a second model that happens to be easier to sample.

Three things are fixed for every draw and recorded with the ensemble rather than rediscovered:

- **the scenario** — the synthetic climate shock, the toy space, the nominal fiscal pressure. P09
  calibrates mechanism parameters against a fixed historical *condition*; letting the scenario move
  with the draw would let a climate setting absorb a mechanism's error.
- **the root seed** — common random numbers. Two draws that differ in one parameter share every
  RNG stream, so a distance difference is attributable to the parameter and not to a fresh weather
  sequence. The subsystem seeds are derived exactly as the kernel derives them.
- **the window** — the objective scores the calibration window only, and the summary statistics of
  the hold-out and extrapolation windows are computed by the prediction path, never here.

A draw outside its prior support is refused rather than clipped: silently pulling a proposal back
to the boundary would report a posterior for a model that never ran.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

import polars as pl

from late_ming_lab.calibration.priors import PriorTable, build_priors
from late_ming_lab.calibration.targets import Objective, TargetScores
from late_ming_lab.calibration.windows import calibration_window
from late_ming_lab.core.config import DEFAULT_ROOT_SEED, SimulationConfig
from late_ming_lab.core.hashing import canonical_json, hash_text
from late_ming_lab.core.kernel import SimulationKernel
from late_ming_lab.evidence.cards import ParameterCards
from late_ming_lab.evidence.ledger import PatternRegistry
from late_ming_lab.evidence.parameters import (
    core_default_band_parameters,
    core_default_crop_parameters,
    core_default_elite_parameters,
    core_default_fiscal_parameters,
    core_default_household_parameters,
    core_default_market_parameters,
    core_default_migration_parameters,
)
from late_ming_lab.experiments.integrated import (
    INTEGRATED_TICK_COUNT,
    INTEGRATED_WARMUP_TICKS,
    IntegratedScenario,
    build_integrated_economy,
)

#: Identifiers the runs carry, so a calibration run is distinguishable from a scenario run in a
#: run store rather than looking like a mislabelled P07 scenario.
CALIBRATION_SCENARIO_ID: Final[str] = "calibration-toy"
CALIBRATION_POLICY_ID: Final[str] = "calibration-v1"
CALIBRATION_RUN_LABEL: Final[str] = "calibration"


class SimulatorError(ValueError):
    """Raised when a draw cannot be turned into a run."""


@dataclass(frozen=True, slots=True)
class SimulatorSettings:
    """The fixed part of every calibration run: the space, the climate, the seed, the window."""

    dataset: str = "toy"
    monthly_event_probability: float = 0.4
    severity_floor: float = 0.6
    nominal_pressure: float = 0.02
    pay_share_of_treasury: float = 0.5
    garrison_troops: float = 300.0
    root_seed: int = DEFAULT_ROOT_SEED
    tick_count: int = INTEGRATED_TICK_COUNT
    warmup_ticks: int = INTEGRATED_WARMUP_TICKS

    def scenario(self) -> IntegratedScenario:
        return IntegratedScenario(
            label=CALIBRATION_SCENARIO_ID,
            dataset=self.dataset,
            monthly_event_probability=self.monthly_event_probability,
            severity_floor=self.severity_floor,
            nominal_pressure=self.nominal_pressure,
            pay_share_of_treasury=self.pay_share_of_treasury,
            garrison_troops=self.garrison_troops,
        )

    def config(self) -> SimulationConfig:
        return SimulationConfig.model_validate(
            {
                "tick_count": self.tick_count,
                "warmup_ticks": self.warmup_ticks,
                "root_seed": self.root_seed,
                "scenario_id": CALIBRATION_SCENARIO_ID,
                "policy_id": CALIBRATION_POLICY_ID,
            }
        )


@dataclass(frozen=True, slots=True)
class SimulatedRun:
    """One draw's run: what was run, what came out, and the digest that identifies it."""

    parameters: tuple[tuple[str, float], ...]
    parameter_hash: str
    run_id: str
    simulation_digest: str
    scores: TargetScores
    events: pl.DataFrame
    county_nodes: tuple[str, ...]

    def parameter_map(self) -> dict[str, float]:
        return dict(self.parameters)


#: How a parameter set is rebuilt from its declared defaults. The name is the class's own name, so
#: the draw and the set it lands in cannot drift apart.
_DEFAULTS = (
    ("CropParameters", core_default_crop_parameters),
    ("HouseholdParameters", core_default_household_parameters),
    ("MarketParameters", core_default_market_parameters),
    ("EliteParameters", core_default_elite_parameters),
    ("FiscalParameters", core_default_fiscal_parameters),
    ("MigrationParameters", core_default_migration_parameters),
    ("BandParameters", core_default_band_parameters),
)


class SandboxSimulator:
    """A deterministic map from a parameter draw to the objective vector of one sandbox run."""

    def __init__(
        self,
        cards: ParameterCards,
        registry: PatternRegistry,
        *,
        settings: SimulatorSettings | None = None,
    ) -> None:
        self._priors: PriorTable = build_priors(cards)
        self._objective: Objective = Objective.from_registry(registry)
        self._settings = settings or SimulatorSettings()
        self._scored: dict[tuple[float, ...], TargetScores] = {}
        self._simulations = 0

    @property
    def priors(self) -> PriorTable:
        return self._priors

    @property
    def objective(self) -> Objective:
        return self._objective

    @property
    def settings(self) -> SimulatorSettings:
        return self._settings

    def parameter_sets(self, parameters: Mapping[str, float]) -> dict[str, object]:
        """The draw's parameter sets, each rebuilt from its declared default."""
        self._check(parameters)
        grouped: dict[str, dict[str, float]] = {}
        for prior in self._priors:
            grouped.setdefault(prior.parameter_set, {})[prior.name] = float(parameters[prior.name])
        return {
            name: default().model_copy(update=grouped[name])
            for name, default in _DEFAULTS
            if name in grouped
        }

    def run(self, parameters: Mapping[str, float]) -> SimulatedRun:
        """Run the sandbox for one draw and score its calibration window."""
        self._check(parameters)
        self._simulations += 1
        ordered = tuple((prior.name, float(parameters[prior.name])) for prior in self._priors)
        scenario = self._settings.scenario()
        economy = build_integrated_economy(scenario, parameter_sets=self.parameter_sets(parameters))
        county_nodes = tuple(node.node_id for node in economy.graphs.nodes.counties)
        result = SimulationKernel(self._settings.config(), list(economy.systems)).run(
            run_label=CALIBRATION_RUN_LABEL
        )
        scores = self._objective.score(
            result.events, window=calibration_window(), county_nodes=county_nodes
        )
        return SimulatedRun(
            parameters=ordered,
            parameter_hash=parameter_hash(ordered),
            run_id=result.manifest.run_id,
            simulation_digest=result.summary.simulation_digest,
            scores=scores,
            events=result.events,
            county_nodes=county_nodes,
        )

    def distance(self, parameters: Mapping[str, float]) -> tuple[float, ...]:
        """The objective vector for one draw, memoised: the same draw is never run twice.

        Memoisation is exact because the simulator is deterministic under common random numbers;
        the sampler re-proposing a value it already tried costs a dictionary lookup, not a run.
        """
        self._check(parameters)
        key = tuple(float(parameters[prior.name]) for prior in self._priors)
        cached = self._scored.get(key)
        if cached is None:
            cached = self.run(parameters).scores
            self._scored[key] = cached
        return cached.vector()

    def simulation_count(self) -> int:
        """How many sandbox runs this simulator has actually executed."""
        return self._simulations

    def distinct_draw_count(self) -> int:
        """How many distinct draws have been scored; the rest were repeats, served from cache."""
        return len(self._scored)

    def _check(self, parameters: Mapping[str, float]) -> None:
        expected = set(self._priors.names())
        supplied = set(parameters)
        if supplied != expected:
            missing = sorted(expected - supplied)
            extra = sorted(supplied - expected)
            raise SimulatorError(
                f"draw does not match the priors; missing {missing}, extra {extra}"
            )
        for prior in self._priors:
            value = float(parameters[prior.name])
            if not self._priors.contains(prior.name, value):
                raise SimulatorError(
                    f"{prior.name}={value} is outside its card range [{prior.low}, {prior.high}]"
                )


def parameter_hash(parameters: tuple[tuple[str, float], ...]) -> str:
    """The digest of one draw, quoted in the ensemble so a row identifies the exact run."""
    return hash_text(canonical_json({name: value for name, value in parameters}))
