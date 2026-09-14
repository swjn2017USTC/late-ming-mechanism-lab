"""Render a batch plan into the Slurm array script that runs it.

The script is generated, never written by hand, so the three things a cluster must not get wrong
come from one place: the array bounds come from the plan's task count, the per-task time limit
comes from the declared per-task cost and the declared safety factor, and the environment is the
one HPC demands — ``--export=NONE``, ``UV_OFFLINE=1``, ``USTC_LLM_ENABLED=0``.

One reading of the two walltime arguments is worth stating, because a script that dies halfway
through a task is worse than a script that refuses to be submitted: ``seconds_per_task * safety``
is the estimate the renderer *derives*, and it is what ``--time`` declares; ``walltime`` is the
operator's declared ceiling for one task, and rendering refuses when the estimate does not fit
inside it. So a plan whose tasks are more expensive than the declared budget is refused here rather
than killed on a node.

The rendered script carries the HPC rules as a header comment, and the body is plain bash: no
network call, no credential, no runtime model.
"""

from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Final

from late_ming_lab.experiments.batch import BatchError, BatchPlan

#: The template ships inside the package, beside this module.
TEMPLATE_NAME: Final[str] = "slurm-array.sh.tmpl"

#: What a placeholder looks like in the template.
_PLACEHOLDER: Final[re.Pattern[str]] = re.compile(r"\{\{([a-z_]+)\}\}")

#: Slurm's own time forms: minutes; minutes:seconds; hours:minutes:seconds; and the same three with
#: a leading day count. Parsed rather than passed through, because the declared ceiling has to be
#: comparable with the estimate.
_TIME_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^(?:(?P<days>\d+)-)?(?:(?P<hours>\d+):)?(?:(?P<minutes>\d+):)?(?P<seconds>\d+)$"
)
_SECONDS_PER_DAY: Final[int] = 86_400
_SECONDS_PER_HOUR: Final[int] = 3_600
_SECONDS_PER_MINUTE: Final[int] = 60

#: The shortest time limit a scheduler reliably accepts: an estimate below a minute is rounded up to
#: it, because ``--time=00:00:15`` is rejected outright by many Slurm configurations and a task that
#: never starts is not a cheaper task.
_MINIMUM_JOB_SECONDS: Final[int] = 60


def parse_walltime(value: str) -> int:
    """Seconds in a Slurm walltime, or a refusal naming what was not understood."""
    match = _TIME_PATTERN.match(value.strip())
    if match is None:
        raise BatchError(
            f"{value!r} is not a Slurm walltime; expected minutes, minutes:seconds, "
            "hours:minutes:seconds, or days-hours:minutes:seconds"
        )
    return (
        int(match.group("days") or 0) * _SECONDS_PER_DAY
        + int(match.group("hours") or 0) * _SECONDS_PER_HOUR
        + int(match.group("minutes") or 0) * _SECONDS_PER_MINUTE
        + int(match.group("seconds"))
    )


def format_walltime(seconds: int) -> str:
    """A whole number of seconds as ``hours:minutes:seconds``, which Slurm accepts."""
    hours, remainder = divmod(seconds, _SECONDS_PER_HOUR)
    minutes, rest = divmod(remainder, _SECONDS_PER_MINUTE)
    return f"{hours:02d}:{minutes:02d}:{rest:02d}"


def render_slurm_script(
    plan: BatchPlan,
    *,
    partition: str,
    walltime: str,
    cpus: int,
    concurrency: int,
    seconds_per_task: float,
    safety: float = 1.5,
) -> str:
    """Render the array script for ``plan``, or refuse if the declared budget does not hold."""
    if safety < 1.0:
        raise BatchError(
            f"safety must be at least 1.0 so the derived limit is above the measured cost, got "
            f"{safety}"
        )
    if seconds_per_task <= 0:
        raise BatchError(f"seconds_per_task must be positive, got {seconds_per_task}")
    if cpus < 1:
        raise BatchError(f"cpus must be at least 1, got {cpus}")
    if concurrency < 1:
        raise BatchError(f"concurrency must be at least 1, got {concurrency}")
    if not partition.strip():
        raise BatchError("a partition name is required")
    if not plan.tasks:
        raise BatchError(f"the {plan.batch_id} plan holds no tasks, so there is no array to submit")
    declared = parse_walltime(walltime)
    estimate = max(math.ceil(seconds_per_task * safety), _MINIMUM_JOB_SECONDS)
    if estimate > declared:
        raise BatchError(
            f"one {plan.family} task is estimated at {estimate}s "
            f"({seconds_per_task:g}s x {safety:g}) and the declared walltime is {walltime} "
            f"({declared}s): submit a longer walltime or a cheaper plan rather than a task that "
            "would be killed partway through"
        )
    replacements = {
        "batch_id": plan.batch_id,
        "partition": partition.strip(),
        "last_index": str(len(plan.tasks) - 1),
        "concurrency": str(concurrency),
        "cpus": str(cpus),
        "walltime": format_walltime(estimate),
        "declared_walltime": format_walltime(declared),
        "seconds_per_task": f"{seconds_per_task:g}",
        "safety": f"{safety:g}",
        "plan_directory": str(plan.directory),
    }
    rendered = _substitute(_template_text(), replacements)
    return rendered if rendered.endswith("\n") else f"{rendered}\n"


def _template_text() -> str:
    template = Path(__file__).with_name(TEMPLATE_NAME)
    if not template.is_file():
        raise BatchError(f"the Slurm template {template} is missing from the package")
    return template.read_text(encoding="utf-8")


def _substitute(template: str, replacements: dict[str, str]) -> str:
    """Fill every placeholder, and refuse to emit a script that still holds one."""
    rendered = template
    for name, value in replacements.items():
        rendered = rendered.replace("{{" + name + "}}", value)
    remaining = sorted({match.group(1) for match in _PLACEHOLDER.finditer(rendered)})
    if remaining:
        raise BatchError(f"the Slurm template left placeholders unfilled: {', '.join(remaining)}")
    return rendered
