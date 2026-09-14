"""HPC surfaces: the Slurm array template that schedules a planned batch.

Nothing in this package runs a simulation, reaches a network or reads a credential. It renders a
plan into the script a cluster runs: one array index per task, one offline environment, and the
runtime decision layer explicitly off.
"""

from __future__ import annotations

from late_ming_lab.hpc.slurm_array import TEMPLATE_NAME, parse_walltime, render_slurm_script

__all__ = ["TEMPLATE_NAME", "parse_walltime", "render_slurm_script"]
