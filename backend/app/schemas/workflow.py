from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from app.services.workflow.stages import FRONTEND_EVENT_NAMES


FrontendMetadataValue = str | int | float | bool | None


class FrontendWorkflowEventCreate(BaseModel):
    action_name: str = Field(min_length=1, max_length=120)
    route: str = Field(min_length=1, max_length=240)
    user_visible_state: str = Field(min_length=1, max_length=120)
    timestamp: datetime
    backend_request_id: str | None = Field(default=None, max_length=120)
    metadata: dict[str, FrontendMetadataValue] = Field(default_factory=dict)

    @field_validator("action_name")
    @classmethod
    def validate_action_name(cls, value: str) -> str:
        if value not in FRONTEND_EVENT_NAMES:
            raise ValueError("unknown frontend workflow event")
        return value

    @model_validator(mode="after")
    def validate_payload_size(self) -> "FrontendWorkflowEventCreate":
        if len(self.metadata) > 20:
            raise ValueError("frontend workflow metadata is too large")
        return self


class FrontendWorkflowEventBatchCreate(BaseModel):
    frontend_session_id: str = Field(min_length=1, max_length=120)
    workflow_run_id: str = Field(min_length=1, max_length=36)
    correlation_id: str = Field(min_length=1, max_length=36)
    project_id: str = Field(min_length=1, max_length=36)
    events: list[FrontendWorkflowEventCreate] = Field(min_length=1, max_length=25)


class FrontendWorkflowEventBatchRead(BaseModel):
    accepted_count: int


class WorkflowRunRead(BaseModel):
    id: str
    project_id: str
    workflow_type: str
    parent_workflow_run_id: str | None = None
    root_workflow_run_id: str | None = None
    correlation_id: str
    status: str
    logging_mode: str
    started_at: datetime
    completed_at: datetime | None = None
    prompt_versions: dict[str, Any] = Field(default_factory=dict)


class WorkflowEventRead(BaseModel):
    id: str
    workflow_run_id: str
    sequence_number: int
    occurred_at: datetime
    recorded_at: datetime
    stage: str
    event_type: str
    severity: str
    blocking: bool
    message: str
    rule_id: str | None = None
