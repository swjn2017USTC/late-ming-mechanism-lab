"""Late Ming Mechanism Lab.

A historical mechanism laboratory: an explainable, reproducible agent-based model of
the 1625-1644 Shaanxi-Henan crisis. Simulation is an argument, not evidence.
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("late-ming-mechanism-lab")
except PackageNotFoundError:  # pragma: no cover - running from a source tree without install
    __version__ = "0.0.0"

__all__ = ["__version__"]
