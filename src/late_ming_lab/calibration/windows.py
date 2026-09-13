"""The three calibration windows, declared once and enforced everywhere.

They are named, fixed tick ranges over the 240-tick run. The rule the phase must not break is that
**no objective may read the hold-out or the extrapolation window**: those exist so that a calibrated
ensemble can be asked whether it predicts, after the fact. `CalibrationWindow` therefore knows which
windows an objective may touch, and the target loader refuses a target whose window is not the
calibration window.

A fourth window, :data:`WHOLE_RUN_WINDOW`, is declared for the prediction path only: a pattern whose
own recorded window is 1627-1644 makes a claim that spans two thirds of the split, and it can only
be scored against all of it. It is not part of the tiling, and the objective refuses it exactly as
it refuses the other two.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final


class WindowRole(StrEnum):
    """What a window is for. Only ``CALIBRATION`` may appear in an objective."""

    CALIBRATION = "calibration"
    HOLD_OUT = "hold-out"
    EXTRAPOLATION = "extrapolation"
    #: The whole run, for the prediction path only. A pattern whose own window is 1627-1644 makes a
    #: claim that spans the hold-out and extrapolation split, and can only be checked against all of
    #: it. No objective may read it: the objective refuses every role but ``CALIBRATION``.
    WHOLE_RUN = "whole-run"


@dataclass(frozen=True, slots=True)
class CalibrationWindow:
    """One named tick range of the run, with the calendar window it corresponds to."""

    role: WindowRole
    label: str
    first_tick: int
    last_tick: int
    calendar: str
    note: str

    @property
    def tick_count(self) -> int:
        return self.last_tick - self.first_tick + 1

    def contains(self, tick: int) -> bool:
        return self.first_tick <= tick <= self.last_tick

    def slice(self, ticks: list[int]) -> list[int]:
        return [tick for tick in ticks if self.contains(tick)]


#: The fixed split of the 1625-1644 run. Declared here so no experiment can choose its own.
WINDOWS: Final[tuple[CalibrationWindow, ...]] = (
    CalibrationWindow(
        role=WindowRole.CALIBRATION,
        label="calibration-1625-1634",
        first_tick=0,
        last_tick=119,
        calendar="1625-01 to 1634-12",
        note=(
            "The warm-up plus the first shock decade. This is the only window an objective may "
            "read: it contains the onset of the crisis and enough years for the slow state "
            "(arrears, land, depletion) to move."
        ),
    ),
    CalibrationWindow(
        role=WindowRole.HOLD_OUT,
        label="hold-out-1635-1642",
        first_tick=120,
        last_tick=215,
        calendar="1635-01 to 1642-12",
        note=(
            "Reserved. Nothing may be fitted to it; it exists to test whether a calibrated "
            "ensemble predicts the middle of the crisis, where the drought, the fiscal shortfall "
            "and the armed groups are all in play together."
        ),
    ),
    CalibrationWindow(
        role=WindowRole.EXTRAPOLATION,
        label="extrapolation-1643-1644",
        first_tick=216,
        last_tick=239,
        calendar="1643-01 to 1644-12",
        note=(
            "Reserved, and the hard case: the last two years, beyond the decade the ensemble was "
            "shaped on, where the sources describe the collapse of the fiscal-military system."
        ),
    ),
)

WINDOW_BY_ROLE: Final[dict[WindowRole, CalibrationWindow]] = {
    window.role: window for window in WINDOWS
}


#: The whole 1625-1644 window. It is not part of the three-way split — it is the split's union,
#: declared separately so the split stays a tiling and this stays a prediction-only view.
WHOLE_RUN_WINDOW: Final[CalibrationWindow] = CalibrationWindow(
    role=WindowRole.WHOLE_RUN,
    label="whole-run-1625-1644",
    first_tick=0,
    last_tick=239,
    calendar="1625-01 to 1644-12",
    note=(
        "The whole run, used only by the hold-out prediction path. A pattern recording 1627-1644 "
        "cannot be scored inside a single third of the window, and scoring it is not fitting: the "
        "calibration objective is bound to the calibration window and refuses this one."
    ),
)


def window(role: WindowRole) -> CalibrationWindow:
    return WINDOW_BY_ROLE[role]


def whole_run_window() -> CalibrationWindow:
    return WHOLE_RUN_WINDOW


def calibration_window() -> CalibrationWindow:
    return window(WindowRole.CALIBRATION)


def hold_out_window() -> CalibrationWindow:
    return window(WindowRole.HOLD_OUT)


def extrapolation_window() -> CalibrationWindow:
    return window(WindowRole.EXTRAPOLATION)


def window_covering_tick(tick: int) -> CalibrationWindow:
    for candidate in WINDOWS:
        if candidate.contains(tick):
            return candidate
    raise ValueError(f"tick {tick} is outside every declared window (run is {240} ticks)")
