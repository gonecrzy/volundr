from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy.orm import Session

from app.models.debug_batch import DebugBatch
from app.schemas.debug_batch import DebugBatchFrontendEventsCreate
from app.services.workflow.redaction import RedactionService


def record_frontend_events(
    *, db: Session, data_dir: Path, batch_id: str, payload: DebugBatchFrontendEventsCreate
) -> int:
    batch = db.get(DebugBatch, batch_id)
    if batch is None:
        raise LookupError("debug batch not found")
    if batch.state not in {"active", "finishing"}:
        raise ValueError("frontend evidence cannot be added to a frozen batch")
    redactor = RedactionService()
    events_path = data_dir / "debug-sessions" / batch_id / "frontend" / "events.ndjson"
    events_path.parent.mkdir(parents=True, exist_ok=True)
    with events_path.open("a", encoding="utf-8") as stream:
        for event in payload.events:
            safe_event = redactor._redact_value(event.model_dump(mode="json"))
            redactor.assert_json_redacted(safe_event)
            stream.write(json.dumps(safe_event, sort_keys=True) + "\n")
    return len(payload.events)
