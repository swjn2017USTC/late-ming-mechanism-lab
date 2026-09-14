"""The family registry, the analyzer, and the offline replay path.

These are the three surfaces that decide what a command *can* do, so the tests are about refusals:
an unknown family, an artifact this command does not read, a seed a document-writing family does not
have, and a replay with no recorded fixtures. Every one of them fails closed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from late_ming_lab.analysis.summary import AnalysisError, summarize, write_reports
from late_ming_lab.experiments.families import FAMILIES, ExperimentError, run_family
from late_ming_lab.experiments.replay import ReplayError, replay_run, replay_settings
from late_ming_lab.policies.ustc_v41 import CONFIRMED_MODEL_IDS

REPOSITORY = Path(__file__).resolve().parents[2]


def test_every_family_names_what_it_runs_and_what_it_writes() -> None:
    assert set(FAMILIES) == {
        "ablations",
        "p04",
        "p10",
        "p12",
        "integrated",
        "evidence",
        "mechanisms",
    }
    for name, family in FAMILIES.items():
        assert family.name == name
        assert family.description
        assert callable(family.runner)


def test_an_unknown_family_is_refused_with_the_ones_that_exist() -> None:
    with pytest.raises(ExperimentError, match="unknown family"):
        run_family("p11", root=REPOSITORY)


def test_a_document_family_refuses_a_seed_it_has_no_use_for() -> None:
    """A seed that changes nothing is a promise the command cannot keep."""
    with pytest.raises(ExperimentError, match="no seeds"):
        run_family("evidence", root=REPOSITORY, seed=1)
    with pytest.raises(ExperimentError, match="no seeds"):
        run_family("mechanisms", root=REPOSITORY, replicates=2)


def test_the_integrated_family_refuses_a_replicate_axis_it_does_not_have() -> None:
    with pytest.raises(ExperimentError, match="once"):
        run_family("integrated", root=REPOSITORY, replicates=3)


def test_the_holdout_family_refuses_a_seed_it_does_not_declare() -> None:
    """V2-P04's arms are a comparison at declared seeds; another axis is another comparison."""
    with pytest.raises(ExperimentError, match="declared seeds"):
        run_family("p04", root=REPOSITORY, replicates=2)
    with pytest.raises(ExperimentError, match="declared"):
        run_family("p04", root=REPOSITORY, seed=1)


def test_the_analyzer_reads_each_artifact_kind_by_its_layout() -> None:
    cards = summarize(REPOSITORY / "docs/mechanisms")
    assert cards.kind == "mechanism-cards"
    assert dict(cards.headline)["cards"] == 6

    batch = summarize(REPOSITORY / "outputs/experiments/p10-ablations")
    assert batch.kind == "experiment-batch"
    assert int(str(dict(batch.headline)["runs"])) > 0

    robustness = summarize(REPOSITORY / "outputs/experiments/p12-robustness")
    assert robustness.kind == "policy-robustness-batch"
    assert "ustc:refused" in str(dict(robustness.headline)["arms"])

    ensemble = summarize(REPOSITORY / "outputs/calibration/p09-cards87a14e9d-32p-ch1-s20260913")
    assert ensemble.kind == "calibration-batch"
    assert int(str(dict(ensemble.headline)["draws"])) > 0


def test_the_analyzer_refuses_a_directory_it_cannot_identify(tmp_path: Path) -> None:
    (tmp_path / "notes.txt").write_text("not an artifact", encoding="utf-8")
    with pytest.raises(AnalysisError, match="is not an artifact"):
        summarize(tmp_path)
    with pytest.raises(AnalysisError, match="does not exist"):
        summarize(tmp_path / "absent")


def test_a_summary_round_trips_as_json() -> None:
    import json

    summary = summarize(REPOSITORY / "docs/mechanisms")
    payload = json.loads(summary.to_json())
    assert payload["kind"] == "mechanism-cards"
    assert payload["headline"]["cards"] == 6


def test_the_analyzer_reads_a_run_directory_the_run_store_wrote(tmp_path: Path) -> None:
    """The layout the analyzer expects is the layout the project actually writes.

    The run store names the event log `agent_events.parquet`; an analyzer that required
    `events.parquet` would refuse every run the CLI produces, so the check is made against a real
    run rather than against a hand-written directory.
    """
    from late_ming_lab.core.config import SimulationConfig
    from late_ming_lab.core.kernel import SimulationKernel
    from late_ming_lab.storage.run_store import RunStore

    result = SimulationKernel(
        SimulationConfig.model_validate({"tick_count": 4, "warmup_ticks": 1})
    ).run(run_label="analyze-check")
    directory = RunStore(tmp_path).write(result)

    summary = summarize(directory)
    assert summary.kind == "run"
    headline = dict(summary.headline)
    assert headline["run_id"] == result.manifest.run_id
    assert headline["ticks"] == 4
    assert headline["llm_enabled"] is False
    assert headline["simulation_digest"] == result.summary.simulation_digest
    with pytest.raises(AnalysisError, match="no document"):
        write_reports(directory)


def test_replay_settings_declare_no_credential_and_the_confirmed_model() -> None:
    """The offline path has no key to leak and no environment to read: that is the point of it."""
    settings = replay_settings()
    assert settings.model_id == CONFIRMED_MODEL_IDS[0]
    assert settings.api_key.get_secret_value() == ""
    assert settings.base_url == ""


def test_a_replay_without_recorded_fixtures_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(ReplayError, match="no recorded fixtures"):
        replay_run(fixtures=tmp_path, output_root=tmp_path / "out")
    assert not (tmp_path / "out").exists(), "a failed replay must not leave a run directory behind"
