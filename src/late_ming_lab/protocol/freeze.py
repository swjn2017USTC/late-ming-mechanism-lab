"""Freezing the protocol, and refusing anything scored under a different one.

A frozen protocol is only worth something if a batch cannot quietly be read against a later version
of it. Three things are enforced here:

```text
identity      the protocol's digest is the SHA-256 of its canonical content, with no clock in it,
              so two reads of the same file agree and any edit changes the identity
commitment    a batch records the digest it was scored under; scoring refuses a batch whose digest
              differs from the protocol on disk, rather than re-scoring old results under new rules
isolation     a score computed in one window may not read another: the calibration objective and the
              prediction checks are separate surfaces, and this module is the single place that says
              which purposes may read which windows
```

The failure mode this prevents is mundane and fatal to the phase's purpose: freeze a protocol, read
results, adjust a definition, and report the adjusted numbers as if they had been pre-registered.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field

from late_ming_lab.protocol.schema import (
    ValidationProtocol,
    load_protocol,
)

#: What a caller intends to do with a window's values.
Purpose = Literal["fit", "score", "report"]

#: Which window ids each purpose may read. ``fit`` is the narrow one on purpose: only the
#: calibration window is a fitting target, and the reporting window is never one.
PURPOSE_WINDOWS: Final[dict[str, frozenset[str]]] = {
    "fit": frozenset({"calibration"}),
    "score": frozenset({"hold-out", "extrapolation"}),
    "report": frozenset({"calibration", "hold-out", "extrapolation", "whole-run"}),
}

#: The key a batch manifest carries the protocol identity under.
BATCH_PROTOCOL_KEY: Final[str] = "validation_protocol"


class ProtocolMismatchError(RuntimeError):
    """Raised when a batch was scored under a protocol other than the frozen one."""


class WindowAccessError(RuntimeError):
    """Raised when a purpose tries to read a window it may not read."""


class ProtocolFreeze(BaseModel):
    """The frozen protocol's identity, as a batch manifest records it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = Field(min_length=1)
    version: str = Field(min_length=1)
    digest: str = Field(min_length=64, max_length=64)
    frozen_on: str = Field(min_length=1)
    outcomes: tuple[str, ...] = ()
    threshold_dependent_readings: tuple[str, ...] = ()

    @classmethod
    def of(cls, protocol: ValidationProtocol) -> ProtocolFreeze:
        return cls(
            schema_version=protocol.schema_version,
            version=protocol.version,
            digest=protocol.digest(),
            frozen_on=protocol.frozen_on,
            outcomes=tuple(outcome.id for outcome in protocol.primary_outcomes),
            threshold_dependent_readings=protocol.threshold_dependence(),
        )

    def record(self) -> dict[str, Any]:
        """What goes into a batch manifest."""
        return self.model_dump(mode="json")


def freeze_protocol(root: str | Path) -> ProtocolFreeze:
    """Load the protocol and return its identity."""
    return ProtocolFreeze.of(load_protocol(root))


def assert_batch_protocol(manifest: dict[str, Any], freeze: ProtocolFreeze) -> None:
    """Refuse a batch manifest that was scored under a different protocol.

    A manifest that records no protocol at all is refused too: an unrecorded batch cannot be shown
    to have been read under the frozen rules, and silence must not read as agreement.
    """
    recorded = manifest.get(BATCH_PROTOCOL_KEY)
    if not isinstance(recorded, dict):
        raise ProtocolMismatchError(
            f"this batch records no {BATCH_PROTOCOL_KEY!r}; it cannot be scored under "
            f"protocol {freeze.version} because nothing says which rules produced it"
        )
    digest = recorded.get("digest")
    if digest != freeze.digest:
        raise ProtocolMismatchError(
            f"this batch was scored under protocol digest {str(digest)[:12]}, and the frozen "
            f"protocol is {freeze.digest[:12]} (version {freeze.version}); re-score it under the "
            "frozen rules instead of reading it as if it had been"
        )
    version = recorded.get("version")
    if version != freeze.version:
        raise ProtocolMismatchError(
            f"this batch records protocol version {version!r} against {freeze.version!r}"
        )


def stamp_batch(manifest: dict[str, Any], freeze: ProtocolFreeze) -> dict[str, Any]:
    """A copy of a manifest with the protocol identity recorded in it."""
    return {**manifest, BATCH_PROTOCOL_KEY: freeze.record()}


def assert_window_access(protocol: ValidationProtocol, window_id: str, purpose: Purpose) -> None:
    """Refuse a window a purpose may not read, naming what the purpose may read instead."""
    protocol.window(window_id)  # raises KeyError on an unknown window
    allowed = PURPOSE_WINDOWS[purpose]
    if window_id not in allowed:
        raise WindowAccessError(
            f"{purpose!r} may not read the {window_id!r} window; it may read "
            f"{', '.join(sorted(allowed))}. The isolation rule is in "
            "data/protocol/validation-protocol-v2.yaml and is not negotiable per report."
        )
    if purpose == "fit" and protocol.window(window_id).role != "scoring":
        raise WindowAccessError(
            f"{window_id!r} is a reporting window and is never a fitting target"
        )


def readable_windows(protocol: ValidationProtocol, purpose: Purpose) -> tuple[str, ...]:
    """The windows a purpose may read, in protocol order."""
    return tuple(window.id for window in protocol.windows if window.id in PURPOSE_WINDOWS[purpose])
