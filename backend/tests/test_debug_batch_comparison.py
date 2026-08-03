import json

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.schemas.debug_batch import DebugBatchStart
from app.services.debug_batches.comparison import DebugBatchComparisonService
from app.services.debug_batches.service import DebugBatchService


COMPLETE_FRONTEND_IDENTITY = json.dumps(
    {
        "component": "frontend",
        "git_sha": "abc1234567890",
        "dirty": False,
        "build_timestamp": "2026-08-03T00:00:00Z",
        "identity": "frontend-test",
    }
)


def test_matching_frozen_batches_are_controlled(tmp_path) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        service = DebugBatchService(db=session, data_dir=tmp_path)
        baseline = service.start(DebugBatchStart(label="live-01", frontend_build_identity=COMPLETE_FRONTEND_IDENTITY))
        service.finish(baseline.id)
        candidate = service.start(
            DebugBatchStart(label="live-02", baseline_batch_id=baseline.id, frontend_build_identity=COMPLETE_FRONTEND_IDENTITY)
        )
        service.finish(candidate.id)

        comparison = DebugBatchComparisonService(db=session, data_dir=tmp_path).compare(candidate.id)

        assert comparison["status"] == "controlled"
        assert comparison["identity_match"] is True
        assert comparison["mismatches"] == {}


def test_identity_mismatch_is_uncontrolled(tmp_path) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        service = DebugBatchService(db=session, data_dir=tmp_path)
        baseline = service.start(DebugBatchStart(label="live-01", frontend_build_identity=COMPLETE_FRONTEND_IDENTITY))
        service.finish(baseline.id)
        candidate = service.start(
            DebugBatchStart(label="live-02", baseline_batch_id=baseline.id, frontend_build_identity=COMPLETE_FRONTEND_IDENTITY)
        )
        candidate.configuration_hash = "different"
        session.commit()
        service.finish(candidate.id)

        comparison = DebugBatchComparisonService(db=session, data_dir=tmp_path).compare(candidate.id)

        assert comparison["status"] == "configuration_mismatch"
        assert comparison["identity_match"] is False
        assert comparison["mismatches"]["configuration_hash"]["candidate"] == "different"
