WORKFLOW_EVENT_SCHEMA_VERSION = "workflow-event-v1"
WORKFLOW_DIAGNOSIS_VERSION = "workflow-diagnosis-v1"
WORKFLOW_REDACTION_VERSION = "workflow-redaction-v1"

WORKFLOW_STAGES = frozenset(
    {
        "project_request",
        "requirement_extraction",
        "requirement_validation",
        "requirement_clarification",
        "design_specification_review",
        "design_plan_generation",
        "design_plan_validation",
        "design_plan_review",
        "source_generation",
        "source_extraction",
        "source_contract_validation",
        "contract_repair",
        "worker_submission",
        "cad_execution",
        "execution_repair",
        "topology_validation",
        "artifact_consistency",
        "mesh_validation",
        "printability_validation",
        "candidate_classification",
        "candidate_review",
        "configuration_preview",
        "configuration_execution",
        "revision_planning",
        "revision_scope_validation",
        "component_revision",
        "scope_correction",
        "output_preservation",
        "acceptance",
        "rejection",
        "export",
        "frontend_workflow",
        "provider_response",
    }
)

WORKFLOW_TYPES = frozenset(
    {
        "initial_generation",
        "requirement_clarification",
        "design_plan_creation",
        "regeneration",
        "configuration_change",
        "structured_revision",
        "component_revision",
        "output_retry",
        "candidate_acceptance",
        "candidate_rejection",
        "export",
        "contract_repair",
        "source_generation",
    }
)

TERMINAL_WORKFLOW_STATUSES = frozenset(
    {"completed", "failed", "blocked", "cancelled", "abandoned"}
)

FRONTEND_EVENT_NAMES = frozenset(
    {
        "project_created",
        "request_submitted",
        "clarification_displayed",
        "clarification_answered",
        "design_review_opened",
        "design_approved",
        "generation_started",
        "candidate_opened",
        "output_selected",
        "warning_expanded",
        "configuration_previewed",
        "configuration_submitted",
        "revision_requested",
        "revision_plan_approved",
        "candidate_accepted",
        "candidate_rejected",
        "export_requested",
        "visible_error_displayed",
        "diagnostic_bundle_requested",
    }
)
