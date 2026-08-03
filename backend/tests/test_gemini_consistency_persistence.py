from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.base import Base
from app.models.gemini_benchmark import (
    GeminiBenchmarkExperiment,
    GeminiBenchmarkMembership,
    GeminiBenchmarkModel,
    GeminiBenchmarkRun,
)


def _experiment() -> GeminiBenchmarkExperiment:
    now = datetime.now(timezone.utc)
    return GeminiBenchmarkExperiment(
        label="consistency-test",
        corpus_version="gemini-consistency-v1",
        corpus_hash="corpus-hash",
        mode="pilot",
        requested_runs=2,
        provider="gemini_api",
        git_head="abc123",
        migration_head="0035_gemini_consistency_benchmark",
        prompt_versions_json="{}",
        configuration_hash="config-hash",
        build_identities_json="{}",
        model_settings_json="{}",
        state="created",
        started_at=now,
        report_root="data/debug-sessions/gemini-consistency/experiment",
    )


def test_benchmark_tables_store_experiment_matrix_and_ordered_membership() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    inspector = inspect(engine)
    assert {
        "gemini_benchmark_experiments",
        "gemini_benchmark_models",
        "gemini_benchmark_runs",
        "gemini_benchmark_memberships",
    }.issubset(inspector.get_table_names())

    with Session(engine) as session:
        experiment = _experiment()
        model = GeminiBenchmarkModel(
            experiment_id=experiment.id,
            requested_model="gemini-2.5-flash",
            actual_model="gemini-2.5-flash-001",
            availability_state="available",
            settings_json='{"temperature":0.2}',
            position=0,
        )
        session.add(experiment)
        session.flush()
        model.experiment_id = experiment.id
        session.add(model)
        session.flush()
        run_a = GeminiBenchmarkRun(
            experiment_id=experiment.id,
            model_config_id=model.id,
            run_index=1,
            stable_run_key=f"{experiment.id}:gemini-2.5-flash:1",
            state="created",
            identity_json="{}",
        )
        run_b = GeminiBenchmarkRun(
            experiment_id=experiment.id,
            model_config_id=model.id,
            run_index=2,
            stable_run_key=f"{experiment.id}:gemini-2.5-flash:2",
            state="created",
            identity_json="{}",
        )
        session.add_all([run_a, run_b])
        session.flush()
        session.add_all(
            [
                GeminiBenchmarkMembership(
                    run_id=run_b.id,
                    corpus_case_id="case-002",
                    position=1,
                    stable_project_key=f"{run_b.id}:case-002",
                    state="claimed",
                ),
                GeminiBenchmarkMembership(
                    run_id=run_a.id,
                    corpus_case_id="case-001",
                    position=0,
                    stable_project_key=f"{run_a.id}:case-001",
                    state="completed",
                    project_id="project-a",
                    metrics_json='{"total_tokens":42}',
                ),
            ]
        )
        session.commit()

        stored = session.get(GeminiBenchmarkExperiment, experiment.id)
        assert stored is not None
        assert stored.corpus_hash == "corpus-hash"
        assert [run.run_index for run in stored.runs] == [1, 2]
        assert stored.models[0].actual_model == "gemini-2.5-flash-001"


def test_benchmark_membership_and_run_keys_are_unique() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        experiment = _experiment()
        model = GeminiBenchmarkModel(
            experiment_id=experiment.id,
            requested_model="gemini-2.5-flash",
            availability_state="available",
            settings_json="{}",
            position=0,
        )
        session.add(experiment)
        session.flush()
        model.experiment_id = experiment.id
        session.add(model)
        session.flush()
        run = GeminiBenchmarkRun(
            experiment_id=experiment.id,
            model_config_id=model.id,
            run_index=1,
            stable_run_key="stable-run",
            state="created",
            identity_json="{}",
        )
        session.add(run)
        session.flush()
        session.add(
            GeminiBenchmarkMembership(
                run_id=run.id,
                corpus_case_id="case-001",
                position=0,
                stable_project_key="stable-project",
                state="claimed",
            )
        )
        session.commit()

        session.add(
            GeminiBenchmarkMembership(
                run_id=run.id,
                corpus_case_id="case-001",
                position=0,
                stable_project_key="stable-project",
                state="claimed",
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
