from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.schemas.debug_batch import DebugBatchStart
from app.services.debug_batches.comparison import DebugBatchComparisonService
from app.services.debug_batches.service import DebugBatchService


def test_matching_frozen_batches_are_controlled(tmp_path) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        service = DebugBatchService(db=session, data_dir=tmp_path)
        baseline = service.start(DebugBatchStart(label="live-01"))
        service.finish(baseline.id)
        candidate = service.start(
            DebugBatchStart(label="live-02", baseline_batch_id=baseline.id)
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
        baseline = service.start(DebugBatchStart(label="live-01"))
        service.finish(baseline.id)
        candidate = service.start(
            DebugBatchStart(label="live-02", baseline_batch_id=baseline.id)
        )
        candidate.configuration_hash = "different"
        session.commit()
        service.finish(candidate.id)

        comparison = DebugBatchComparisonService(db=session, data_dir=tmp_path).compare(candidate.id)

        assert comparison["status"] == "uncontrolled"
        assert comparison["identity_match"] is False
        assert comparison["mismatches"]["configuration_hash"]["candidate"] == "different"
