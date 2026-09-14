"""Window isolation and the protocol commitment, both directions, in the code that enforces them.

Two things must not be true of a V2 batch: that it was fitted on the window it is scored on, and
that it is read under a protocol other than the one that scored it. Both are refused here rather
than documented, and the refusals are checked in both directions — a fit that reads a hold-out
window and a score that reads the calibration window are the same bug seen from two sides.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from late_ming_lab.protocol.freeze import (
    PURPOSE_WINDOWS,
    ProtocolFreeze,
    ProtocolMismatchError,
    WindowAccessError,
    assert_batch_protocol,
    assert_window_access,
    freeze_protocol,
    readable_windows,
    stamp_batch,
)
from late_ming_lab.protocol.schema import ValidationProtocol, load_protocol


@pytest.fixture(scope="module")
def protocol() -> ValidationProtocol:
    return load_protocol(".")


@pytest.fixture(scope="module")
def frozen() -> ProtocolFreeze:
    return freeze_protocol(".")


def test_fitting_may_read_only_the_calibration_window(protocol: ValidationProtocol) -> None:
    assert readable_windows(protocol, "fit") == ("calibration",)
    assert_window_access(protocol, "calibration", "fit")


@pytest.mark.parametrize("window", ["hold-out", "extrapolation"])
def test_a_fit_that_reads_a_held_out_window_is_refused(
    protocol: ValidationProtocol, window: str
) -> None:
    with pytest.raises(WindowAccessError, match="may not read"):
        assert_window_access(protocol, window, "fit")


def test_the_reporting_window_is_never_a_fitting_target(protocol: ValidationProtocol) -> None:
    """A whole-run window overlaps every scoring window, so nothing may be fitted on it."""
    with pytest.raises(WindowAccessError, match="may not read"):
        assert_window_access(protocol, "whole-run", "fit")


@pytest.mark.parametrize("window", ["calibration", "whole-run"])
def test_a_score_that_reads_the_fitting_window_is_refused(
    protocol: ValidationProtocol, window: str
) -> None:
    """The other direction: a score may not be computed on what the parameters were fitted on."""
    with pytest.raises(WindowAccessError, match="may not read"):
        assert_window_access(protocol, window, "score")


@pytest.mark.parametrize("window", ["hold-out", "extrapolation"])
def test_a_score_may_read_the_windows_it_is_for(protocol: ValidationProtocol, window: str) -> None:
    assert_window_access(protocol, window, "score")


def test_an_unknown_window_is_refused_rather_than_defaulted(protocol: ValidationProtocol) -> None:
    with pytest.raises(KeyError):
        assert_window_access(protocol, "not-a-window", "report")


def test_every_purpose_reads_only_windows_the_protocol_declares(
    protocol: ValidationProtocol,
) -> None:
    declared = {window.id for window in protocol.windows}
    for purpose, allowed in PURPOSE_WINDOWS.items():
        assert allowed <= declared, purpose
        for window in readable_windows(protocol, purpose):  # type: ignore[arg-type]
            assert_window_access(protocol, window, purpose)  # type: ignore[arg-type]


def test_a_batch_that_records_no_protocol_is_refused(frozen: ProtocolFreeze) -> None:
    """Silence is not agreement: an unrecorded batch cannot be shown to be comparable."""
    with pytest.raises(ProtocolMismatchError, match="records no"):
        assert_batch_protocol({"label": "v1-batch"}, frozen)


def test_a_batch_scored_under_another_protocol_is_refused(frozen: ProtocolFreeze) -> None:
    stale = {
        "label": "v1-batch",
        "validation_protocol": {
            "schema_version": frozen.schema_version,
            "version": frozen.version,
            "digest": "0" * 64,
            "frozen_on": frozen.frozen_on,
        },
    }
    with pytest.raises(ProtocolMismatchError, match="scored under protocol digest"):
        assert_batch_protocol(stale, frozen)


def test_a_batch_of_another_version_with_the_same_digest_is_refused(
    frozen: ProtocolFreeze,
) -> None:
    """Version and digest must agree: one without the other is a half-read identity."""
    wrong_version = {
        "validation_protocol": {
            "schema_version": frozen.schema_version,
            "version": "1.9.9",
            "digest": frozen.digest,
            "frozen_on": frozen.frozen_on,
        }
    }
    with pytest.raises(ProtocolMismatchError, match="version"):
        assert_batch_protocol(wrong_version, frozen)


def test_stamping_a_batch_makes_it_readable_and_it_records_the_identity(
    frozen: ProtocolFreeze,
) -> None:
    stamped = stamp_batch({"label": "pilot"}, frozen)
    assert stamped["validation_protocol"]["digest"] == frozen.digest
    assert_batch_protocol(stamped, frozen)
    assert stamped["label"] == "pilot"


def test_a_changed_protocol_invalidates_what_was_scored_under_the_old_one(
    tmp_path: Path, protocol: ValidationProtocol
) -> None:
    """The acceptance criterion: a new protocol version makes old batches incompatible.

    The check runs against a real second version — the frozen file with one substantive effect
    changed — so what is tested is the mechanism, not a hand-written digest.
    """
    import json

    import yaml

    from late_ming_lab.protocol.schema import PROTOCOL_PATH

    stamped = stamp_batch({"label": "scored"}, ProtocolFreeze.of(protocol))

    payload = json.loads(json.dumps(yaml.safe_load(_protocol_text())))
    payload["version"] = "2.0.1"
    payload["primary_outcomes"][0]["minimum_substantive_effect"] = 0.25
    path = tmp_path / PROTOCOL_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")

    revised = freeze_protocol(tmp_path)
    assert revised.digest != protocol.digest()
    with pytest.raises(ProtocolMismatchError):
        assert_batch_protocol(stamped, revised)


def _protocol_text() -> str:
    from late_ming_lab.protocol.schema import PROTOCOL_PATH

    return Path(PROTOCOL_PATH).read_text(encoding="utf-8")


def test_a_pilot_run_without_a_protocol_stamp_is_refused(tmp_path: Path) -> None:
    """The fail-closed path a real batch takes: a run that records no protocol is not readable."""
    from late_ming_lab.protocol.report import ReportError, _assert_stamp

    with pytest.raises(ReportError, match="carries no"):
        _assert_stamp(tmp_path, protocol=load_protocol("."))


def test_a_pilot_run_stamped_with_another_protocol_is_refused(tmp_path: Path) -> None:
    """A run scored under another protocol cannot be read as if the frozen one had scored it."""
    import json

    from late_ming_lab.protocol.evaluation import PROTOCOL_STAMP_FILE
    from late_ming_lab.protocol.freeze import ProtocolFreeze, stamp_batch
    from late_ming_lab.protocol.report import ReportError, _assert_stamp

    protocol = load_protocol(".")
    stale = ProtocolFreeze.of(protocol).model_copy(update={"digest": "1" * 64})
    (tmp_path / PROTOCOL_STAMP_FILE).write_text(
        json.dumps(stamp_batch({}, stale)), encoding="utf-8"
    )
    with pytest.raises(ReportError, match="scored under protocol digest"):
        _assert_stamp(tmp_path, protocol=protocol)
