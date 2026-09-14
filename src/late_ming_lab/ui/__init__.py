"""The artifact browser: what the phases already wrote, read back and drawn.

Two modules, deliberately separate:

- :mod:`late_ming_lab.ui.data` is the loader. It reads a run directory, a batch directory or the
  mechanism cards, imports no UI framework, and can be exercised headlessly — which is what the
  tests do.
- :mod:`late_ming_lab.ui.app` is the Solara page: seven tabs over whatever the loader returned.

Nothing in this package runs the model, writes an artifact or reaches the network. See
``docs/ui.md`` for how to launch it and what each tab reads.
"""

from late_ming_lab.ui.data import (
    ComparisonResult,
    RunView,
    SeriesSpec,
    UiDataError,
    compare_runs,
    load_cards,
    load_run_view,
    series_catalog,
)

__all__ = [
    "ComparisonResult",
    "RunView",
    "SeriesSpec",
    "UiDataError",
    "compare_runs",
    "load_cards",
    "load_run_view",
    "series_catalog",
]
