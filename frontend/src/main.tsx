import Editor from "@monaco-editor/react";
import React, { useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { STLLoader } from "three/examples/jsm/loaders/STLLoader.js";
import {
  acceptDisabledReason,
  canAcceptRevision,
  candidateFindingBuckets,
  candidateFindingRecoveryActions,
  geometricFindingBuckets,
  revisionViewerLabel,
  revisionWorkflowLabel,
  revisionPromptFromCandidateFinding,
  revisionPromptFromGeometricFinding,
  outputDimensionsLabel,
  outputSolidCountLabel,
  outputStateLabel,
  outputTopologyLabel,
  canRetryOutput,
  designConsistencyLabel,
  sourceCheckSummary,
  type CandidateFinding,
  type CandidateFindingRecoveryActionKind,
  type DesignConsistency,
  type GeometricAnalysis,
  type GeometricFinding,
  type ReviewState,
  type RevisionOutput,
  type ValidationSummary,
} from "./candidateView";
import {
  assumptionBuckets,
  canContinueGeneration,
  defaultProvenanceRows,
  protectedRequirementCount,
  requirementProvenanceRows,
  requirementStageLabel,
  traceFailureMessage,
  type RequirementOutcome,
} from "./designSpecificationView";
import {
  canGenerateConfiguration,
  configurationControlKind,
  configurationImpactLabel,
  configurationStateLabel,
  type ConfigurationChange,
  type ConfigurationParameter,
  type ConfigurationPreset,
} from "./configurationView";
import {
  canApproveDesignPlan,
  canGenerateFromDesignPlan,
  designPlanClarificationQuestions,
  designPlanStageLabel,
  designPlanSummaryCounts,
  type DesignPlanReviewState,
} from "./designPlanView";
import {
  canApproveRevisionPlan,
  canGenerateFromRevisionPlan,
  componentRevisionCounts,
  revisionComplianceBuckets,
  revisionPlanStageLabel,
  revisionPlanSummaryCounts,
  revisionSuccessBuckets,
  type ComponentRevisionSummary,
  type RevisionComplianceResult,
  type RevisionPlanOutcome,
  type RevisionPlanReviewState,
  type RevisionSuccessResult,
} from "./revisionPlanView";
import { applyChatClarificationAnswer, nextChatWorkflowAction } from "./chatWorkflow";
import "./styles.css";

const API_BASE = "/api";
type VolundrFrontendEnv = {
  VITE_VOLUNDR_GENERATION_MODE?: string;
};
const FRONTEND_ENV = (import.meta as ImportMeta & { env?: VolundrFrontendEnv }).env ?? {};
const ADVANCED_WORKFLOW_ENABLED =
  (FRONTEND_ENV.VITE_VOLUNDR_GENERATION_MODE ?? "advanced").toLowerCase() === "advanced";

type Project = {
  id: string;
  name: string;
  original_intent: string;
  status: string;
  active_revision_id: string | null;
};

type ProjectMessage = {
  id: string;
  revision_id: string | null;
  role: string;
  content: string;
  created_at: string;
};

type MeshMetadata = {
  size_x_mm: number;
  size_y_mm: number;
  size_z_mm: number;
  volume_mm3: number;
  triangle_count: number;
  connected_components: number;
  is_watertight: boolean;
};

type Revision = {
  id: string;
  parent_revision_id: string | null;
  design_specification_id: string | null;
  design_plan_id: string | null;
  configuration_change_id: string | null;
  revision_number: number;
  source_type: string;
  status: string;
  is_accepted: boolean;
  review_state: ReviewState | null;
  accepted_at: string | null;
  rejected_at: string | null;
  user_instruction: string | null;
  cad_backend: string;
  source_language: string;
  source_path: string;
  source_hash: string | null;
  source_contract_version: string | null;
  execution_manifest_path: string | null;
  stl_path: string | null;
  ai_output_path: string | null;
  output_manifest_path: string | null;
  expected_output_count: number | null;
  required_output_count: number | null;
  successful_output_count: number | null;
  blocked_output_count: number | null;
  failed_output_count: number | null;
  created_at: string;
  metadata: MeshMetadata | null;
  error_message: string | null;
  validation_summary: ValidationSummary;
  design_consistency?: DesignConsistency | null;
};

type ClarificationQuestion = {
  id: string;
  project_id: string;
  design_specification_id: string;
  requirement_id: string | null;
  question: string;
  reason: string | null;
  display_order: number;
  created_at: string;
};

type DesignSpecification = {
  id: string;
  project_id: string;
  generation_attempt_id: string | null;
  superseded_specification_id: string | null;
  version_number: number;
  schema_version: string;
  prompt_template_version: string;
  ruleset_version: string;
  provider: string;
  provider_model: string | null;
  user_instruction: string;
  raw_response_path: string | null;
  specification_path: string;
  content_hash: string;
  outcome: RequirementOutcome;
  supported_scope: boolean;
  clarification_required: boolean;
  generation_ready: boolean;
  created_at: string;
  specification: {
    purpose?: string;
    critical_dimensions?: Array<{
      id: string;
      label: string;
      value: number | string | boolean | null;
      unit?: string | null;
      source: string;
      importance?: string;
      protected?: boolean;
    }>;
    parameters?: Array<{
      id: string;
      label: string;
      value: number | string | boolean | null;
      unit?: string | null;
      source: string;
      importance?: string;
      protected?: boolean;
      explanation?: string | null;
    }>;
    functional_requirements?: Array<{
      id: string;
      description: string;
      source: string;
      importance?: string;
      protected?: boolean;
    }>;
    print_requirements?: Record<string, unknown>;
    assumptions?: Array<{
      id: string;
      description: string;
      source: string;
      requires_approval?: boolean;
    }>;
    conflicts?: Array<{ id?: string; description?: string }>;
    missing_requirements?: Array<{ id?: string; label?: string; reason?: string }>;
  };
  clarification_questions: ClarificationQuestion[];
};

type DesignPlan = {
  id: string;
  project_id: string;
  design_specification_id: string;
  generation_attempt_id: string | null;
  superseded_design_plan_id: string | null;
  version_number: number;
  schema_version: string;
  prompt_template_version: string;
  ruleset_version: string;
  provider: string;
  provider_model: string | null;
  raw_response_path: string | null;
  plan_path: string;
  content_hash: string;
  outcome: "plan_ready" | "plan_clarification_required" | "plan_failed";
  review_state: DesignPlanReviewState;
  clarification_required: boolean;
  plan_ready: boolean;
  approved_at: string | null;
  rejected_at: string | null;
  created_at: string;
  generated_revision_id: string | null;
  clarification_questions: Array<{
    id: string;
    project_id: string;
    design_plan_id: string;
    related_plan_field: string | null;
    question: string;
    reason: string | null;
    display_order: number;
    created_at: string;
  }>;
  plan: {
    purpose?: string;
    design_level?: string;
    product_type?: string;
    parameters?: Array<{
      id: string;
      label: string;
      value: number | string | boolean | null;
      unit?: string | null;
      editable?: boolean;
      protected?: boolean;
      component_id?: string | null;
    }>;
    derived_parameters?: Array<{
      id: string;
      label: string;
      expression: string;
      unit?: string | null;
      depends_on?: string[];
    }>;
    dependency_edges?: Array<{
      from: string;
      to: string;
      relationship: string;
    }>;
    components?: Array<{
      id: string;
      label: string;
      description?: string;
      features?: string[];
      parameters?: string[];
    }>;
    features?: Array<{
      id: string;
      component_id: string;
      type: string;
      description: string;
      parameters?: string[];
      protected?: boolean;
    }>;
    presets?: Array<{
      id: string;
      label: string;
      parameter_values?: Record<string, unknown>;
    }>;
    assembly_strategy?: { type?: string; instructions?: string[] };
    printable_outputs?: Array<{
      id: string;
      label: string;
      component_ids: string[];
      quantity: number;
      orientation?: string | null;
    }>;
    risks?: Array<{
      id?: string;
      severity?: string;
      description?: string;
      mitigation?: string;
    }>;
    clarification_questions?: Array<{
      id?: string;
      question?: string;
      reason?: string;
      related_plan_field?: string;
    }>;
  };
};

type RevisionPlanClarificationQuestion = {
  id: string;
  project_id: string;
  revision_plan_id: string;
  requirement_id: string | null;
  question: string;
  reason: string | null;
  display_order: number;
  created_at: string;
};

type RevisionPlan = {
  id: string;
  project_id: string;
  base_revision_id: string;
  base_design_specification_id: string | null;
  base_design_plan_id: string | null;
  generation_attempt_id: string | null;
  superseded_revision_plan_id: string | null;
  generated_revision_id: string | null;
  revised_design_specification_id: string | null;
  revised_design_plan_id: string | null;
  version_number: number;
  schema_version: string;
  prompt_template_version: string;
  ruleset_version: string;
  provider: string;
  provider_model: string | null;
  user_instruction: string;
  reason: string;
  raw_response_path: string | null;
  plan_path: string;
  content_hash: string;
  base_source_hash: string | null;
  base_output_manifest_hash: string | null;
  base_design_specification_hash: string | null;
  base_design_plan_hash: string | null;
  outcome: RevisionPlanOutcome;
  review_state: RevisionPlanReviewState;
  clarification_required: boolean;
  revision_ready: boolean;
  approved_at: string | null;
  rejected_at: string | null;
  created_at: string;
  revision_plan: {
    summary?: string;
    requested_changes?: Array<{
      target_type: string;
      target_id: string;
      current_value?: number | string | boolean | null;
      requested_value?: number | string | boolean | null;
      change_type?: string;
      source?: string;
    }>;
    required_dependency_changes?: Array<{ parameter_id: string; affects?: string[] }>;
    targeted_components?: string[];
    targeted_features?: string[];
    targeted_outputs?: string[];
    targeted_findings?: string[];
    allowed_parameter_changes?: string[];
    protected_parameters?: Array<{
      parameter_id: string;
      expected_value?: number | string | boolean | null;
      unit?: string | null;
    }>;
    protected_components?: string[];
    protected_features?: string[];
    protected_outputs?: string[];
    prohibited_changes?: string[];
    success_criteria?: Array<{
      type: string;
      target_id: string;
      expected_value?: number | string | boolean | null;
      unit?: string | null;
    }>;
    clarification_questions?: Array<{
      id?: string;
      question?: string;
      reason?: string;
      related_requirement_id?: string;
    }>;
  };
  clarification_questions: RevisionPlanClarificationQuestion[];
};

type BuildVolumeProfile = {
  x_mm: number;
  y_mm: number;
  z_mm: number;
};

type PrintabilityProfile = {
  profile_version: string;
  printer_name: string;
  process: string;
  material_behavior: string;
  build_volume: BuildVolumeProfile;
  nozzle_diameter_mm: number;
  default_layer_height_mm: number;
};

type SavedPrintabilityProfile = PrintabilityProfile & {
  id: string;
  created_at: string;
  updated_at: string;
};

type PrintabilitySeverity = "Pass" | "Notice" | "Warning" | "Critical";

type PrintabilityHighlight = {
  rule_id: string;
  severity: PrintabilitySeverity;
  type: string;
  bounds_min_mm: [number, number, number] | null;
  bounds_max_mm: [number, number, number] | null;
  face_indices: number[] | null;
};

type PrintabilityResult = {
  severity: PrintabilitySeverity;
  rule_id: string;
  detected_value: {
    value: number | string;
    units: string;
  };
  affected_count: number | null;
  affected_area_mm2: number | null;
  explanation: string;
  suggested_correction: string;
  orientation_dependent: boolean;
  dismissed: boolean;
  highlight: PrintabilityHighlight | null;
};

type PrintabilityReport = {
  profile_version: string;
  profile: PrintabilityProfile;
  results: PrintabilityResult[];
  highlights: PrintabilityHighlight[];
};

const DEFAULT_PRINTABILITY_PROFILE: PrintabilityProfile = {
  profile_version: "printability-fdm-v1",
  printer_name: "Generic FDM 256",
  process: "FDM",
  material_behavior: "general PLA/PETG",
  build_volume: {
    x_mm: 256,
    y_mm: 256,
    z_mm: 256,
  },
  nozzle_diameter_mm: 0.4,
  default_layer_height_mm: 0.2,
};

function App() {
  const [projectName, setProjectName] = useState("");
  const [intent, setIntent] = useState("");
  const [instruction, setInstruction] = useState("");
  const [generationPrompt, setGenerationPrompt] = useState("");
  const [source, setSource] = useState("");
  const [project, setProject] = useState<Project | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [revisions, setRevisions] = useState<Revision[]>([]);
  const [projectMessages, setProjectMessages] = useState<ProjectMessage[]>([]);
  const [selectedRevision, setSelectedRevision] = useState<Revision | null>(null);
  const [isCompiling, setIsCompiling] = useState(false);
  const [isGenerating, setIsGenerating] = useState(false);
  const [isSavingProject, setIsSavingProject] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [compileLog, setCompileLog] = useState<string | null>(null);
  const [aiOutput, setAiOutput] = useState<string | null>(null);
  const [revisionDiff, setRevisionDiff] = useState<string | null>(null);
  const [printabilityProfile, setPrintabilityProfile] = useState<PrintabilityProfile>(
    DEFAULT_PRINTABILITY_PROFILE,
  );
  const [savedPrintabilityProfiles, setSavedPrintabilityProfiles] = useState<
    SavedPrintabilityProfile[]
  >([]);
  const [selectedPrintabilityProfileId, setSelectedPrintabilityProfileId] = useState("");
  const [isSavingPrintabilityProfile, setIsSavingPrintabilityProfile] = useState(false);
  const [printabilityReport, setPrintabilityReport] = useState<PrintabilityReport | null>(null);
  const [candidateFindings, setCandidateFindings] = useState<CandidateFinding[]>([]);
  const [geometricAnalysis, setGeometricAnalysis] = useState<GeometricAnalysis | null>(null);
  const [revisionOutputs, setRevisionOutputs] = useState<RevisionOutput[]>([]);
  const [selectedOutputId, setSelectedOutputId] = useState<string | null>(null);
  const [isRetryingOutputId, setIsRetryingOutputId] = useState<string | null>(null);
  const [sourceContractError, setSourceContractError] = useState<string | null>(null);
  const [isReviewActionPending, setIsReviewActionPending] = useState(false);
  const [designSpecification, setDesignSpecification] = useState<DesignSpecification | null>(null);
  const [designPlan, setDesignPlan] = useState<DesignPlan | null>(null);
  const [designPlanAnswers, setDesignPlanAnswers] = useState<Record<string, string>>({});
  const [revisionPlan, setRevisionPlan] = useState<RevisionPlan | null>(null);
  const [revisionPlanAnswers, setRevisionPlanAnswers] = useState<Record<string, string>>({});
  const [configurationParameters, setConfigurationParameters] = useState<ConfigurationParameter[]>([]);
  const [configurationPresets, setConfigurationPresets] = useState<ConfigurationPreset[]>([]);
  const [configurationDraft, setConfigurationDraft] = useState<Record<string, string | number | boolean>>({});
  const [selectedConfigurationPresetId, setSelectedConfigurationPresetId] = useState("");
  const [configurationPreview, setConfigurationPreview] = useState<ConfigurationChange | null>(null);
  const [isPreviewingConfiguration, setIsPreviewingConfiguration] = useState(false);
  const [isGeneratingConfiguration, setIsGeneratingConfiguration] = useState(false);
  const [revisionComplianceResult, setRevisionComplianceResult] =
    useState<RevisionComplianceResult | null>(null);
  const [revisionSuccessResults, setRevisionSuccessResults] = useState<RevisionSuccessResult[]>([]);
  const [componentRevisionSummary, setComponentRevisionSummary] =
    useState<ComponentRevisionSummary | null>(null);
  const [pendingRevisionFindingIds, setPendingRevisionFindingIds] = useState<string[]>([]);
  const [clarificationAnswers, setClarificationAnswers] = useState<Record<string, string>>({});
  const [isSubmittingClarification, setIsSubmittingClarification] = useState(false);
  const [isCreatingDesignPlan, setIsCreatingDesignPlan] = useState(false);
  const [isDesignPlanActionPending, setIsDesignPlanActionPending] = useState(false);
  const [isContinuingGeneration, setIsContinuingGeneration] = useState(false);
  const [isPlanningRevision, setIsPlanningRevision] = useState(false);
  const [isRevisionPlanActionPending, setIsRevisionPlanActionPending] = useState(false);
  const [isGeneratingRevision, setIsGeneratingRevision] = useState(false);
  const [isInspectingPrintability, setIsInspectingPrintability] = useState(false);
  const [dismissedPrintabilityResults, setDismissedPrintabilityResults] = useState<Set<string>>(
    () => new Set(),
  );
  const [isProjectDrawerOpen, setIsProjectDrawerOpen] = useState(false);
  const printabilitySectionRef = useRef<HTMLDivElement | null>(null);

  const selectedOutput =
    revisionOutputs.find((output) => output.id === selectedOutputId) ?? revisionOutputs[0] ?? null;
  const selectedOutputIsPersisted = Boolean(selectedOutput);
  const activeMetadata = selectedOutput?.metadata ?? selectedRevision?.metadata ?? null;
  const stlUrl = selectedOutput?.stl_path && selectedOutputIsPersisted
    ? `${API_BASE}/revision-outputs/${selectedOutput.id}/stl`
    : selectedRevision?.status === "succeeded" && selectedRevision.stl_path
      ? `${API_BASE}/revisions/${selectedRevision.id}/stl`
      : null;
  const sourceUrl = selectedRevision ? `${API_BASE}/revisions/${selectedRevision.id}/source` : null;
  const manifestUrl = selectedRevision ? `${API_BASE}/revisions/${selectedRevision.id}/output-manifest` : null;
  const exportUrl = selectedRevision ? `${API_BASE}/revisions/${selectedRevision.id}/export.zip` : null;
  const selectedSourceLabel = "Python";
  const sourcePanelLabel = "Python source";
  const sourceEditorLanguage = "python";
  const printabilityHighlights = useMemo(
    () => printabilityReport?.highlights ?? [],
    [printabilityReport],
  );
  const hasProjectName = projectName.trim().length > 0;
  const isDraftProject = project?.status === "draft";
  const canCompileSource = source.trim().length > 0;
  const canAskAi = generationPrompt.trim().length > 0;
  const canSaveProject = Boolean(project) && hasProjectName;
  const workspaceTitle =
    project && !isDraftProject ? project.name : projectName.trim() || "Untitled draft";
  const selectedViewerLabel = revisionViewerLabel(selectedRevision, project);
  const selectedWorkflowLabel = revisionWorkflowLabel(selectedRevision);
  const acceptReason = acceptDisabledReason(selectedRevision);
  const canAcceptSelectedRevision = canAcceptRevision(selectedRevision);
  const currentRequirementStage = requirementStageLabel(designSpecification);
  const currentDesignPlanStage = designPlanStageLabel(designPlan);
  const canContinueFromSpecification =
    canContinueGeneration(designSpecification) && !isGenerating && !isCreatingDesignPlan;
  const canApproveCurrentDesignPlan =
    canApproveDesignPlan(designPlan) && !isDesignPlanActionPending && !isContinuingGeneration;
  const canGenerateFromCurrentDesignPlan =
    canGenerateFromDesignPlan(designPlan) && !isDesignPlanActionPending && !isContinuingGeneration;
  const currentRevisionPlanStage = revisionPlanStageLabel(revisionPlan);
  const selectedRevisionCanPlan = Boolean(
    selectedRevision?.status === "succeeded" && selectedRevision.design_plan_id,
  );
  const canPlanRevisionFromCurrentContext = Boolean(
    project &&
      (selectedRevisionCanPlan || project.active_revision_id),
  );
  const hasRequirementClarificationPending =
    designSpecification?.outcome === "clarification_required" &&
    designSpecification.clarification_questions.length > 0;
  const designPlanQuestions = designPlanClarificationQuestions(designPlan);
  const hasDesignPlanClarificationPending =
    designPlan?.review_state === "clarification_required" &&
    designPlanQuestions.length > 0;
  const hasRevisionClarificationPending =
    revisionPlan?.review_state === "clarification_required" &&
    revisionPlan.clarification_questions.length > 0;
  const isChatActionPending =
    isGenerating ||
    isPlanningRevision ||
    isSubmittingClarification ||
    isDesignPlanActionPending ||
    isRevisionPlanActionPending;
  const chatButtonLabel = isChatActionPending
    ? "Sending"
    : hasRequirementClarificationPending || hasDesignPlanClarificationPending || hasRevisionClarificationPending
      ? "Answer"
      : ADVANCED_WORKFLOW_ENABLED && canPlanRevisionFromCurrentContext
        ? "Plan revision"
        : "Send";
  const chatPlaceholder = hasRequirementClarificationPending || hasDesignPlanClarificationPending || hasRevisionClarificationPending
    ? "Answer clarification"
    : "Message Gemini";
  const canApproveCurrentRevisionPlan =
    canApproveRevisionPlan(revisionPlan) && !isRevisionPlanActionPending && !isGeneratingRevision;
  const canGenerateFromCurrentRevisionPlan =
    canGenerateFromRevisionPlan(revisionPlan) && !isRevisionPlanActionPending && !isGeneratingRevision;
  const canGenerateCurrentConfiguration =
    canGenerateConfiguration(configurationPreview) && !isGeneratingConfiguration;

  useEffect(() => {
    void refreshProjects();
    void refreshPrintabilityProfiles();
  }, []);

  async function refreshProjects() {
    try {
      setProjects(await request<Project[]>("/projects", { method: "GET" }));
    } catch {
      setProjects([]);
    }
  }

  async function refreshPrintabilityProfiles() {
    try {
      setSavedPrintabilityProfiles(
        await request<SavedPrintabilityProfile[]>("/printability-profiles", { method: "GET" }),
      );
    } catch {
      setSavedPrintabilityProfiles([]);
    }
  }

  function resetRequirementState() {
    setDesignSpecification(null);
    setDesignPlan(null);
    setDesignPlanAnswers({});
    setClarificationAnswers({});
    setIsSubmittingClarification(false);
    setIsCreatingDesignPlan(false);
    setIsDesignPlanActionPending(false);
    setIsContinuingGeneration(false);
  }

  function resetRevisionPlanState() {
    setRevisionPlan(null);
    setRevisionPlanAnswers({});
    setRevisionComplianceResult(null);
    setRevisionSuccessResults([]);
    setComponentRevisionSummary(null);
    setPendingRevisionFindingIds([]);
    setIsPlanningRevision(false);
    setIsRevisionPlanActionPending(false);
    setIsGeneratingRevision(false);
  }

  function resetConfigurationState() {
    setConfigurationParameters([]);
    setConfigurationPresets([]);
    setConfigurationDraft({});
    setSelectedConfigurationPresetId("");
    setConfigurationPreview(null);
    setIsPreviewingConfiguration(false);
    setIsGeneratingConfiguration(false);
  }

  async function loadCurrentDesignSpecification(projectId: string) {
    try {
      setDesignSpecification(
        await request<DesignSpecification>(`/projects/${projectId}/design-specification`, {
          method: "GET",
        }),
      );
      setClarificationAnswers({});
      await loadCurrentDesignPlan(projectId);
    } catch {
      resetRequirementState();
    }
  }

  async function loadCurrentDesignPlan(projectId: string) {
    try {
      setDesignPlan(
        await request<DesignPlan>(`/projects/${projectId}/design-plan`, {
          method: "GET",
        }),
      );
      setDesignPlanAnswers({});
      await loadConfigurationOptions(projectId);
    } catch {
      setDesignPlan(null);
      setDesignPlanAnswers({});
      resetConfigurationState();
    }
  }

  async function loadConfigurationOptions(projectId: string) {
    try {
      const [parameters, presets] = await Promise.all([
        request<ConfigurationParameter[]>(`/projects/${projectId}/configuration/parameters`, {
          method: "GET",
        }),
        request<ConfigurationPreset[]>(`/projects/${projectId}/configuration/presets`, {
          method: "GET",
        }),
      ]);
      setConfigurationParameters(parameters);
      setConfigurationPresets(presets);
      setConfigurationDraft(
        Object.fromEntries(
          parameters.map((parameter) => [parameter.id, parameter.value ?? ""]),
        ),
      );
      setConfigurationPreview(null);
    } catch {
      resetConfigurationState();
    }
  }

  async function loadCurrentRevisionPlan(projectId: string) {
    try {
      const plan = await request<RevisionPlan>(`/projects/${projectId}/revision-plan`, {
        method: "GET",
      });
      setRevisionPlan(plan);
      setRevisionPlanAnswers({});
      await loadRevisionPlanResults(plan);
    } catch {
      resetRevisionPlanState();
    }
  }

  async function loadRevisionPlanResults(plan: RevisionPlan) {
    try {
      setRevisionComplianceResult(
        await request<RevisionComplianceResult>(`/revision-plans/${plan.id}/compliance-result`, {
          method: "GET",
        }),
      );
    } catch {
      setRevisionComplianceResult(null);
    }
    try {
      setRevisionSuccessResults(
        await request<RevisionSuccessResult[]>(`/revision-plans/${plan.id}/success-results`, {
          method: "GET",
        }),
      );
    } catch {
      setRevisionSuccessResults([]);
    }
    try {
      setComponentRevisionSummary(
        await request<ComponentRevisionSummary>(`/revision-plans/${plan.id}/component-revision-summary`, {
          method: "GET",
        }),
      );
    } catch {
      setComponentRevisionSummary(null);
    }
  }

  async function saveProject() {
    if (!project || !hasProjectName) {
      setMessage("Name is required before saving");
      return;
    }
    setIsSavingProject(true);
    setMessage(null);
    try {
      const updatedProject = await request<Project>(`/projects/${project.id}${isDraftProject ? "/save" : ""}`, {
        method: isDraftProject ? "POST" : "PATCH",
        body: JSON.stringify({
          name: projectName,
          original_intent: intent,
        }),
      });
      setProject(updatedProject);
      setProjects((current) => {
        const existing = current.some((entry) => entry.id === updatedProject.id);
        if (!existing) {
          return [updatedProject, ...current];
        }
        return current.map((entry) => (entry.id === updatedProject.id ? updatedProject : entry));
      });
      setMessage("Project saved");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Project save failed");
    } finally {
      setIsSavingProject(false);
    }
  }

  async function archiveProject() {
    if (!project) {
      return;
    }
    setIsSavingProject(true);
    setMessage(null);
    try {
      await request<Project>(`/projects/${project.id}/archive`, {
        method: "POST",
      });
      setProjects((current) => current.filter((entry) => entry.id !== project.id));
      setProject(null);
      setProjectName("");
      setIntent("");
      setInstruction("");
      setGenerationPrompt("");
      setSource("");
      setRevisions([]);
      setProjectMessages([]);
      setSelectedRevision(null);
      setCandidateFindings([]);
      setGeometricAnalysis(null);
      setPrintabilityReport(null);
      setDismissedPrintabilityResults(new Set());
      setCompileLog(null);
      setAiOutput(null);
      setRevisionDiff(null);
      resetRequirementState();
      resetRevisionPlanState();
      setMessage("Project archived");
      setIsProjectDrawerOpen(false);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Project archive failed");
    } finally {
      setIsSavingProject(false);
    }
  }

  async function deleteProject() {
    if (!project || !window.confirm("Delete this project permanently?")) {
      return;
    }
    setIsSavingProject(true);
    setMessage(null);
    try {
      await requestEmpty(`/projects/${project.id}`, {
        method: "DELETE",
      });
      setProjects((current) => current.filter((entry) => entry.id !== project.id));
      setProject(null);
      setProjectName("");
      setIntent("");
      setInstruction("");
      setGenerationPrompt("");
      setSource("");
      setRevisions([]);
      setProjectMessages([]);
      setSelectedRevision(null);
      setCandidateFindings([]);
      setGeometricAnalysis(null);
      setPrintabilityReport(null);
      setDismissedPrintabilityResults(new Set());
      setCompileLog(null);
      setAiOutput(null);
      setRevisionDiff(null);
      resetRequirementState();
      resetRevisionPlanState();
      setMessage("Project deleted");
      setIsProjectDrawerOpen(false);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Project delete failed");
    } finally {
      setIsSavingProject(false);
    }
  }

  async function compileSource() {
    if (!canCompileSource) {
      setMessage("Enter CAD source before compiling");
      return;
    }
    setIsCompiling(true);
    setMessage(null);
    try {
      const currentProject = project ?? (await createDraftProject());

      if (!project || project.id !== currentProject.id) {
        setProject(currentProject);
      }

      const revision = await request<Revision>(`/projects/${currentProject.id}/revisions`, {
        method: "POST",
        body: JSON.stringify({
          source,
          user_instruction: instruction,
        }),
      });
      const nextRevisions = [...revisions, revision];
      setRevisions(nextRevisions);
      setSelectedRevision(revision);
      await loadCandidateFindings(revision);
      await loadGeometricAnalysis(revision);
      setPrintabilityReport(null);
      setDismissedPrintabilityResults(new Set());
      setProject({ ...currentProject, active_revision_id: revision.is_accepted ? revision.id : currentProject.active_revision_id });
      setMessage(revision.status === "succeeded" ? "Compiled" : revision.error_message ?? "Compile failed");
      await loadCompileLog(revision);
      await loadAiOutput(revision);
      await loadRevisionDiff(revision);
      await loadProjectMessages(currentProject.id);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Request failed");
    } finally {
      setIsCompiling(false);
    }
  }

  async function generateSource() {
    const prompt = generationPrompt.trim();
    if (!prompt) {
      setMessage("Enter an AI prompt before asking AI");
      return;
    }
    setIsGenerating(true);
    setMessage(null);
    setSourceContractError(null);
    setGenerationPrompt("");
    try {
      const currentProject = project ?? (await createDraftProject());

      if (!project || project.id !== currentProject.id) {
        setProject(currentProject);
      }

      if (!ADVANCED_WORKFLOW_ENABLED) {
        setMessage("Generating source");
        const revision = await request<Revision>(`/projects/${currentProject.id}/generate`, {
          method: "POST",
          body: JSON.stringify({ user_instruction: prompt }),
        });
        const nextRevisions = await request<Revision[]>(`/projects/${currentProject.id}/revisions`, {
          method: "GET",
        });
        setRevisions(nextRevisions);
        await loadProjectMessages(currentProject.id);
        setSelectedRevision(revision);
        await selectRevision(revision);
        setMessage(revision.status === "succeeded" ? "Candidate ready" : revision.error_message ?? "Generation failed");
        return;
      }

      setMessage("Understanding request");
      const specification = await request<DesignSpecification>(`/projects/${currentProject.id}/requirements`, {
        method: "POST",
        body: JSON.stringify({ user_instruction: prompt }),
      });
      setDesignSpecification(specification);
      setDesignPlan(null);
      setClarificationAnswers({});
      if (specification.outcome === "generation_ready") {
        setMessage("Requirements ready");
      } else if (specification.outcome === "clarification_required") {
        setMessage("Waiting for clarification");
      } else if (specification.outcome === "requirements_conflict") {
        setMessage("Requirements conflict");
      } else if (specification.outcome === "unsupported_request") {
        setMessage("Unsupported request");
      } else {
        setMessage("Requirement extraction failed");
      }
      await loadProjectMessages(currentProject.id);
    } catch (error) {
      const fallback = ADVANCED_WORKFLOW_ENABLED ? "Requirement extraction failed" : "Generation failed";
      const message = error instanceof Error ? error.message : fallback;
      setMessage(message);
      if (message.startsWith("Model source rejected before compile")) {
        setSourceContractError(message);
      }
    } finally {
      setIsGenerating(false);
    }
  }

  async function submitClarificationAnswers(answerOverride?: Record<string, string>) {
    if (!designSpecification) {
      return;
    }
    const answers = answerOverride ?? clarificationAnswers;
    setIsSubmittingClarification(true);
    setSourceContractError(null);
    setMessage("Understanding request");
    try {
      const specification = await request<DesignSpecification>(
        `/design-specifications/${designSpecification.id}/clarification-answers`,
        {
          method: "POST",
          body: JSON.stringify({
            answers: designSpecification.clarification_questions.map((question) => ({
              question_id: question.id,
              answer: answers[question.id] ?? "",
            })),
          }),
        },
      );
      setDesignSpecification(specification);
      setDesignPlan(null);
      setClarificationAnswers({});
      setMessage(specification.outcome === "generation_ready" ? "Requirements ready" : requirementStageLabel(specification));
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Clarification failed");
    } finally {
      setIsSubmittingClarification(false);
    }
  }

  async function createDesignPlanFromSpecification() {
    if (!project) {
      setMessage("Save or create a project before planning");
      return;
    }
    if (!designSpecification || !canContinueGeneration(designSpecification)) {
      setMessage("Requirements must be ready before planning");
      return;
    }
    setIsCreatingDesignPlan(true);
    setSourceContractError(null);
    setMessage("Planning product model");
    try {
      const plan = await request<DesignPlan>(`/design-specifications/${designSpecification.id}/design-plan`, {
        method: "POST",
      });
      setDesignPlan(plan);
      setDesignPlanAnswers({});
      setMessage(plan.review_state === "pending_review" ? "Plan review" : designPlanStageLabel(plan));
      await loadProjectMessages(project.id);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Design planning failed");
    } finally {
      setIsCreatingDesignPlan(false);
    }
  }

  async function approveDesignPlan() {
    if (!designPlan || !canApproveDesignPlan(designPlan)) {
      return;
    }
    setIsDesignPlanActionPending(true);
    setMessage(null);
    try {
      const approved = await request<DesignPlan>(`/design-plans/${designPlan.id}/approve`, {
        method: "POST",
      });
      setDesignPlan(approved);
      if (project) {
        await loadProjectMessages(project.id);
      }
      await continueGenerationFromDesignPlan(approved);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Design Plan approval failed");
    } finally {
      setIsDesignPlanActionPending(false);
    }
  }

  async function rejectDesignPlan() {
    if (!designPlan) {
      return;
    }
    setIsDesignPlanActionPending(true);
    setMessage(null);
    try {
      const rejected = await request<DesignPlan>(`/design-plans/${designPlan.id}/reject`, {
        method: "POST",
      });
      setDesignPlan(rejected);
      setMessage("Plan rejected");
      if (project) {
        await loadProjectMessages(project.id);
      }
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Design Plan rejection failed");
    } finally {
      setIsDesignPlanActionPending(false);
    }
  }

  async function continueGenerationFromDesignPlan(planOverride?: DesignPlan) {
    if (!project) {
      setMessage("Save or create a project before generation");
      return;
    }
    const planToGenerate = planOverride ?? designPlan;
    if (!planToGenerate || !canGenerateFromDesignPlan(planToGenerate)) {
      setMessage("Design Plan must be approved before generation");
      return;
    }
    setIsContinuingGeneration(true);
    setSourceContractError(null);
    setMessage("Generating model");
    try {
      const revision = await request<Revision>(`/design-plans/${planToGenerate.id}/generate`, {
        method: "POST",
      });
      const nextRevisions = await request<Revision[]>(`/projects/${project.id}/revisions`, {
        method: "GET",
      });
      setRevisions(nextRevisions);
      setSelectedRevision(revision);
      await loadCandidateFindings(revision);
      await loadGeometricAnalysis(revision);
      setPrintabilityReport(null);
      setDismissedPrintabilityResults(new Set());
      setProject({ ...project, active_revision_id: revision.is_accepted ? revision.id : project.active_revision_id });
      setMessage(revision.status === "succeeded" ? "Candidate ready" : revision.error_message ?? "Generation failed");
      await selectRevision(revision);
      await loadProjectMessages(project.id);
    } catch (error) {
      const message = error instanceof Error ? error.message : "Generation failed";
      if (message.startsWith("Model source rejected before compile")) {
        setSourceContractError(message);
        setMessage("Model source rejected before compile");
      } else {
        setMessage(message);
      }
    } finally {
      setIsContinuingGeneration(false);
    }
  }

  async function submitDesignPlanClarificationAnswers(answerOverride?: Record<string, string>) {
    if (!designPlan) {
      return;
    }
    const questions = designPlanClarificationQuestions(designPlan);
    const answers = answerOverride ?? designPlanAnswers;
    setIsDesignPlanActionPending(true);
    setMessage("Planning product model");
    try {
      const plan = await request<DesignPlan>(
        `/design-plans/${designPlan.id}/clarification-answers`,
        {
          method: "POST",
          body: JSON.stringify({
            answers: questions.map((question) => ({
              question_id: question.id,
              answer: answers[question.id] ?? "",
            })),
          }),
        },
      );
      setDesignPlan(plan);
      setDesignPlanAnswers({});
      setMessage(designPlanStageLabel(plan));
      if (project) {
        await loadProjectMessages(project.id);
      }
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Design Plan clarification failed");
    } finally {
      setIsDesignPlanActionPending(false);
    }
  }

  async function createRevisionPlanFromPrompt() {
    const prompt = generationPrompt.trim();
    if (!project || !prompt) {
      setMessage("Open a project and enter a revision request");
      return;
    }
    const baseRevisionId = selectedRevisionCanPlan
      ? selectedRevision?.id ?? null
      : project.active_revision_id;
    if (!baseRevisionId) {
      setMessage("Accept a base revision before planning a revision");
      return;
    }
    setIsPlanningRevision(true);
    setSourceContractError(null);
    setRevisionComplianceResult(null);
    setRevisionSuccessResults([]);
    setComponentRevisionSummary(null);
    setComponentRevisionSummary(null);
    setGenerationPrompt("");
    setMessage("Planning revision");
    try {
      const plan = await request<RevisionPlan>(`/projects/${project.id}/revision-plans`, {
        method: "POST",
        body: JSON.stringify({
          base_revision_id: baseRevisionId,
          user_instruction: prompt,
          reason: pendingRevisionFindingIds.length > 0 ? "geometric_finding" : "user_request",
          targeted_finding_ids: pendingRevisionFindingIds,
        }),
      });
      setRevisionPlan(plan);
      setRevisionPlanAnswers({});
      setPendingRevisionFindingIds([]);
      setMessage(plan.review_state === "pending_review" ? "Revision plan review" : revisionPlanStageLabel(plan));
      await loadProjectMessages(project.id);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Revision planning failed");
    } finally {
      setIsPlanningRevision(false);
    }
  }

  async function submitRevisionPlanClarificationAnswers(answerOverride?: Record<string, string>) {
    if (!revisionPlan) {
      return;
    }
    const answers = answerOverride ?? revisionPlanAnswers;
    setIsRevisionPlanActionPending(true);
    setMessage("Planning revision");
    try {
      const plan = await request<RevisionPlan>(
        `/revision-plans/${revisionPlan.id}/clarification-answers`,
        {
          method: "POST",
          body: JSON.stringify({
            answers: revisionPlan.clarification_questions.map((question) => ({
              question_id: question.id,
              answer: answers[question.id] ?? "",
            })),
          }),
        },
      );
      setRevisionPlan(plan);
      setRevisionPlanAnswers({});
      setMessage(revisionPlanStageLabel(plan));
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Revision clarification failed");
    } finally {
      setIsRevisionPlanActionPending(false);
    }
  }

  async function submitRequirementClarificationFromChat() {
    if (!designSpecification) {
      return;
    }
    const result = applyChatClarificationAnswer(
      designSpecification.clarification_questions,
      clarificationAnswers,
      generationPrompt,
    );
    setClarificationAnswers(result.answers);
    setGenerationPrompt("");
    if (!result.answeredQuestionId) {
      setMessage("Answer the clarification question before continuing.");
      return;
    }
    if (!result.readyToSubmit) {
      const nextQuestion = designSpecification.clarification_questions.find(
        (question) => question.id === result.nextQuestionId,
      );
      setMessage(nextQuestion ? `Answer recorded. ${nextQuestion.question}` : "Answer recorded.");
      return;
    }
    await submitClarificationAnswers(result.answers);
  }

  async function submitDesignPlanClarificationFromChat() {
    if (!designPlan) {
      return;
    }
    const questions = designPlanClarificationQuestions(designPlan);
    const result = applyChatClarificationAnswer(
      questions,
      designPlanAnswers,
      generationPrompt,
    );
    setDesignPlanAnswers(result.answers);
    setGenerationPrompt("");
    if (!result.answeredQuestionId) {
      setMessage("Answer the Design Plan clarification question before continuing.");
      return;
    }
    if (!result.readyToSubmit) {
      const nextQuestion = questions.find((question) => question.id === result.nextQuestionId);
      setMessage(nextQuestion ? `Answer recorded. ${nextQuestion.question}` : "Answer recorded.");
      return;
    }
    await submitDesignPlanClarificationAnswers(result.answers);
  }

  async function submitRevisionPlanClarificationFromChat() {
    if (!revisionPlan) {
      return;
    }
    const result = applyChatClarificationAnswer(
      revisionPlan.clarification_questions,
      revisionPlanAnswers,
      generationPrompt,
    );
    setRevisionPlanAnswers(result.answers);
    setGenerationPrompt("");
    if (!result.answeredQuestionId) {
      setMessage("Answer the revision clarification question before continuing.");
      return;
    }
    if (!result.readyToSubmit) {
      const nextQuestion = revisionPlan.clarification_questions.find(
        (question) => question.id === result.nextQuestionId,
      );
      setMessage(nextQuestion ? `Answer recorded. ${nextQuestion.question}` : "Answer recorded.");
      return;
    }
    await submitRevisionPlanClarificationAnswers(result.answers);
  }

  async function approveRevisionPlan() {
    if (!revisionPlan || !canApproveRevisionPlan(revisionPlan)) {
      return;
    }
    setIsRevisionPlanActionPending(true);
    setMessage(null);
    try {
      const approved = await request<RevisionPlan>(`/revision-plans/${revisionPlan.id}/approve`, {
        method: "POST",
      });
      setRevisionPlan(approved);
      if (project) {
        await loadProjectMessages(project.id);
      }
      await generateFromRevisionPlan(approved);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Revision Plan approval failed");
    } finally {
      setIsRevisionPlanActionPending(false);
    }
  }

  async function rejectRevisionPlan() {
    if (!revisionPlan) {
      return;
    }
    setIsRevisionPlanActionPending(true);
    setMessage(null);
    try {
      const rejected = await request<RevisionPlan>(`/revision-plans/${revisionPlan.id}/reject`, {
        method: "POST",
      });
      setRevisionPlan(rejected);
      setMessage("Revision plan rejected");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Revision Plan rejection failed");
    } finally {
      setIsRevisionPlanActionPending(false);
    }
  }

  async function generateFromRevisionPlan(planOverride?: RevisionPlan) {
    const planToGenerate = planOverride ?? revisionPlan;
    if (!planToGenerate || !canGenerateFromRevisionPlan(planToGenerate)) {
      setMessage("Revision Plan must be approved before source revision");
      return;
    }
    setIsGeneratingRevision(true);
    setSourceContractError(null);
    setRevisionComplianceResult(null);
    setRevisionSuccessResults([]);
    setMessage("Revising source");
    try {
      const revision = await request<Revision>(`/revision-plans/${planToGenerate.id}/generate`, {
        method: "POST",
      });
      if (project) {
        const nextRevisions = await request<Revision[]>(`/projects/${project.id}/revisions`, {
          method: "GET",
        });
        setRevisions(nextRevisions);
        await loadProjectMessages(project.id);
      }
      setSelectedRevision(revision);
      await selectRevision(revision);
      const refreshedPlan = await request<RevisionPlan>(`/revision-plans/${planToGenerate.id}`, {
        method: "GET",
      });
      setRevisionPlan(refreshedPlan);
      await loadRevisionPlanResults(refreshedPlan);
      setMessage(revision.status === "succeeded" ? "Revision candidate ready" : revision.error_message ?? "Revision failed");
    } catch (error) {
      const message = error instanceof Error ? error.message : "Revision failed";
      setMessage(message);
      if (
        message.startsWith("Revision source rejected before compile") ||
        message.startsWith("Model source rejected before compile")
      ) {
        setSourceContractError(message);
      }
      try {
        setRevisionComplianceResult(
          await request<RevisionComplianceResult>(`/revision-plans/${planToGenerate.id}/compliance-result`, {
            method: "GET",
          }),
        );
      } catch {
        setRevisionComplianceResult(null);
      }
    } finally {
      setIsGeneratingRevision(false);
    }
  }

  function submitPrompt() {
    const action = nextChatWorkflowAction({
      advancedWorkflowEnabled: ADVANCED_WORKFLOW_ENABLED,
      hasRequirementClarificationPending,
      hasDesignPlanClarificationPending,
      hasRevisionPlanClarificationPending: hasRevisionClarificationPending,
      canPlanRevisionFromCurrentContext,
    });
    switch (action) {
      case "answer_requirement_clarification":
        void submitRequirementClarificationFromChat();
        return;
      case "answer_design_plan_clarification":
        void submitDesignPlanClarificationFromChat();
        return;
      case "answer_revision_plan_clarification":
        void submitRevisionPlanClarificationFromChat();
        return;
      case "plan_revision":
        void createRevisionPlanFromPrompt();
        return;
      case "generate":
        void generateSource();
        return;
    }
  }

  function handlePromptKeyDown(event: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key !== "Enter" || event.shiftKey) {
      return;
    }
    event.preventDefault();
    if (!isChatActionPending && generationPrompt.trim()) {
      submitPrompt();
    }
  }

  async function selectRevision(revision: Revision) {
    setSelectedRevision(revision);
    await loadRevisionOutputs(revision);
    await loadCandidateFindings(revision);
    await loadGeometricAnalysis(revision);
    await loadComponentRevisionSummary(revision);
    setPrintabilityReport(null);
    setDismissedPrintabilityResults(new Set());
    const response = await fetch(`${API_BASE}/revisions/${revision.id}/source`);
    if (response.ok) {
      setSource(await response.text());
    }
    await loadCompileLog(revision);
    await loadAiOutput(revision);
    await loadRevisionDiff(revision);
  }

  async function loadComponentRevisionSummary(revision: Revision) {
    try {
      setComponentRevisionSummary(
        await request<ComponentRevisionSummary>(`/revisions/${revision.id}/component-revision-summary`, {
          method: "GET",
        }),
      );
    } catch {
      setComponentRevisionSummary(null);
    }
  }

  async function createDraftProject() {
    return request<Project>("/projects/draft", {
      method: "POST",
    });
  }

  async function selectProject(nextProject: Project) {
    setIsProjectDrawerOpen(false);
    setProject(nextProject);
    setProjectName(nextProject.name);
    setIntent(nextProject.original_intent);
    await loadCurrentDesignSpecification(nextProject.id);
    await loadCurrentRevisionPlan(nextProject.id);
    await loadProjectMessages(nextProject.id);
    const nextRevisions = await request<Revision[]>(`/projects/${nextProject.id}/revisions`, {
      method: "GET",
    });
    setRevisions(nextRevisions);
    const activeRevision =
      nextRevisions.find((revision) => revision.id === nextProject.active_revision_id) ??
      nextRevisions.at(-1) ??
      null;
    setSelectedRevision(activeRevision);
    if (activeRevision) {
      await selectRevision(activeRevision);
    } else {
      setCandidateFindings([]);
      setGeometricAnalysis(null);
      setRevisionOutputs([]);
      setSelectedOutputId(null);
      setPrintabilityReport(null);
      setDismissedPrintabilityResults(new Set());
      setCompileLog(null);
      setAiOutput(null);
      setRevisionDiff(null);
    }
  }

  async function previewConfiguration() {
    if (!project) {
      return;
    }
    setIsPreviewingConfiguration(true);
    setMessage(null);
    try {
      const values: Record<string, string | number | boolean> = {};
      const userOverrides: Record<string, string | number | boolean> = {};
      const selectedPreset = configurationPresets.find(
        (entry) => entry.preset_id === selectedConfigurationPresetId,
      );
      const presetValues = selectedPreset ? configurationDraftValues(selectedPreset.parameter_values) : {};
      for (const parameter of configurationParameters) {
        const value = configurationDraft[parameter.id];
        if (value === "") {
          continue;
        }
        const normalized = normalizeConfigurationValue(parameter, value);
        if (selectedPreset) {
          if (normalized !== presetValues[parameter.id]) {
            userOverrides[parameter.id] = normalized;
          }
        } else if (normalized !== parameter.value) {
          values[parameter.id] = normalized;
        }
      }
      const preview = await request<ConfigurationChange>(
        `/projects/${project.id}/configuration/preview`,
        {
          method: "POST",
          body: JSON.stringify({
            selected_preset_id: selectedConfigurationPresetId || null,
            parameter_values: values,
            user_overrides: userOverrides,
          }),
        },
      );
      setConfigurationPreview(preview);
      setMessage(configurationStateLabel(preview.validation_state));
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Configuration preview failed");
    } finally {
      setIsPreviewingConfiguration(false);
    }
  }

  async function generateConfigurationCandidate() {
    if (!configurationPreview) {
      return;
    }
    setIsGeneratingConfiguration(true);
    setMessage(null);
    try {
      const revision = await request<Revision>(
        `/configuration-changes/${configurationPreview.id}/generate`,
        { method: "POST" },
      );
      setSelectedRevision(revision);
      setSource(await requestText(`/revisions/${revision.id}/source`, { method: "GET" }));
      await loadRevisionOutputs(revision);
      await loadCandidateFindings(revision);
      await loadGeometricAnalysis(revision);
      if (project) {
        const refreshedProject = await request<Project>(`/projects/${project.id}`, { method: "GET" });
        setProject(refreshedProject);
        const nextRevisions = await request<Revision[]>(`/projects/${project.id}/revisions`, {
          method: "GET",
        });
        setRevisions(nextRevisions);
      }
      const refreshedPreview = await request<ConfigurationChange>(
        `/configuration-changes/${configurationPreview.id}`,
        { method: "GET" },
      );
      setConfigurationPreview(refreshedPreview);
      setMessage("Configuration candidate ready");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Configuration generation failed");
    } finally {
      setIsGeneratingConfiguration(false);
    }
  }

  async function loadProjectMessages(projectId: string) {
    try {
      setProjectMessages(await request<ProjectMessage[]>(`/projects/${projectId}/messages`, {
        method: "GET",
      }));
    } catch {
      setProjectMessages([]);
    }
  }

  async function loadCompileLog(revision: Revision) {
    const response = await fetch(`${API_BASE}/revisions/${revision.id}/compile-log`);
    setCompileLog(response.ok ? await response.text() : null);
  }

  async function loadAiOutput(revision: Revision) {
    if (!revision.ai_output_path) {
      setAiOutput(null);
      return;
    }
    const response = await fetch(`${API_BASE}/revisions/${revision.id}/ai-output`);
    setAiOutput(response.ok ? await response.text() : null);
  }

  async function loadRevisionDiff(revision: Revision) {
    if (!revision.parent_revision_id) {
      setRevisionDiff(null);
      return;
    }
    const response = await fetch(`${API_BASE}/revisions/${revision.id}/diff`);
    setRevisionDiff(response.ok ? await response.text() : null);
  }

  async function loadCandidateFindings(revision: Revision) {
    if (!isOpenCandidate(revision)) {
      setCandidateFindings([]);
      return;
    }
    try {
      setCandidateFindings(await request<CandidateFinding[]>(`/candidates/${revision.id}/findings`, {
        method: "GET",
      }));
    } catch {
      setCandidateFindings([]);
    }
  }

  async function loadRevisionOutputs(revision: Revision) {
    try {
      const outputs = await request<RevisionOutput[]>(`/revisions/${revision.id}/outputs`, {
        method: "GET",
      });
      setRevisionOutputs(outputs);
      setSelectedOutputId((current) => {
        if (current && outputs.some((output) => output.id === current)) {
          return current;
        }
        return outputs.find((output) => output.stl_path)?.id ?? outputs[0]?.id ?? null;
      });
    } catch {
      setRevisionOutputs([]);
      setSelectedOutputId(null);
    }
  }

  async function loadGeometricAnalysis(revision: Revision) {
    if (revision.status !== "succeeded" || !revision.stl_path) {
      setGeometricAnalysis(null);
      return;
    }
    try {
      setGeometricAnalysis(
        await request<GeometricAnalysis>(`/candidates/${revision.id}/geometric-analysis`, {
          method: "GET",
        }),
      );
    } catch {
      setGeometricAnalysis(null);
    }
  }

  async function acceptSelectedCandidate() {
    if (!selectedRevision || !canAcceptSelectedRevision) {
      return;
    }
    setIsReviewActionPending(true);
    setMessage(null);
    try {
      const accepted = await request<Revision>(`/candidates/${selectedRevision.id}/accept`, {
        method: "POST",
      });
      setSelectedRevision(accepted);
      setRevisions((current) =>
        current.map((revision) => (revision.id === accepted.id ? accepted : revision)),
      );
      if (project) {
        const updatedProject = { ...project, active_revision_id: accepted.id };
        setProject(updatedProject);
        setProjects((current) =>
          current.map((entry) => (entry.id === updatedProject.id ? updatedProject : entry)),
        );
        await loadProjectMessages(project.id);
      }
      await loadCandidateFindings(accepted);
      await loadGeometricAnalysis(accepted);
      setMessage(`Accepted R${accepted.revision_number}`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Candidate acceptance failed");
    } finally {
      setIsReviewActionPending(false);
    }
  }

  async function rejectSelectedCandidate() {
    if (!selectedRevision || !isOpenCandidate(selectedRevision)) {
      return;
    }
    setIsReviewActionPending(true);
    setMessage(null);
    try {
      const rejected = await request<Revision>(`/candidates/${selectedRevision.id}/reject`, {
        method: "POST",
      });
      setSelectedRevision(rejected);
      setRevisions((current) =>
        current.map((revision) => (revision.id === rejected.id ? rejected : revision)),
      );
      await loadCandidateFindings(rejected);
      await loadGeometricAnalysis(rejected);
      if (project) {
        await loadProjectMessages(project.id);
      }
      setMessage(`Rejected R${rejected.revision_number}`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Candidate rejection failed");
    } finally {
      setIsReviewActionPending(false);
    }
  }

  function handleCandidateFindingRecovery(
    finding: CandidateFinding,
    actionKind: CandidateFindingRecoveryActionKind,
  ) {
    if (actionKind === "profile") {
      printabilitySectionRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
      setMessage(
        "Review the printer build volume/profile. If the profile is correct, revise the model or split outputs.",
      );
      return;
    }
    setGenerationPrompt(revisionPromptFromCandidateFinding(finding));
    setPendingRevisionFindingIds([finding.id]);
    setMessage("Revision prompt prepared from validation finding");
  }

  async function retryOutput(output: RevisionOutput) {
    setIsRetryingOutputId(output.id);
    setMessage(null);
    try {
      const retried = await request<RevisionOutput>(`/revision-outputs/${output.id}/retry`, {
        method: "POST",
      });
      setRevisionOutputs((current) =>
        current.map((entry) => (entry.id === retried.id ? retried : entry)),
      );
      if (selectedRevision) {
        const refreshed = await request<Revision>(`/candidates/${selectedRevision.id}`, {
          method: "GET",
        });
        setSelectedRevision(refreshed);
        setRevisions((current) =>
          current.map((revision) => (revision.id === refreshed.id ? refreshed : revision)),
        );
        await loadCandidateFindings(refreshed);
      }
      setMessage(`Retried ${retried.label}`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Output retry failed");
    } finally {
      setIsRetryingOutputId(null);
    }
  }

  async function dismissCandidateFinding(findingId: string) {
    setMessage(null);
    try {
      const dismissed = await request<CandidateFinding>(`/validation-findings/${findingId}/dismiss`, {
        method: "POST",
        body: JSON.stringify({ reason: "Dismissed during candidate review" }),
      });
      setCandidateFindings((current) =>
        current.map((finding) => (finding.id === dismissed.id ? dismissed : finding)),
      );
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Finding dismissal failed");
    }
  }

  async function restoreSelectedRevision() {
    if (!selectedRevision) {
      return;
    }
    const restoredProject = await request<Project>(`/revisions/${selectedRevision.id}/restore`, {
      method: "POST",
    });
    setProject(restoredProject);
    setProjects((current) =>
      current.map((entry) => (entry.id === restoredProject.id ? restoredProject : entry)),
    );
    setMessage(`Restored R${selectedRevision.revision_number}`);
  }

  async function inspectSelectedRevisionPrintability() {
    if (!selectedRevision?.is_accepted) {
      return;
    }
    setIsInspectingPrintability(true);
    setMessage(null);
    try {
      const report = await request<PrintabilityReport>(
        `/revisions/${selectedRevision.id}/printability`,
        {
          method: "POST",
          body: JSON.stringify(printabilityProfile),
        },
      );
      setPrintabilityReport(report);
      setDismissedPrintabilityResults(new Set());
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Printability inspection failed");
    } finally {
      setIsInspectingPrintability(false);
    }
  }

  function updatePrintabilityProfile(profile: PrintabilityProfile) {
    setPrintabilityProfile(profile);
    setPrintabilityReport(null);
    setDismissedPrintabilityResults(new Set());
  }

  function selectPrintabilityProfile(profileId: string) {
    setSelectedPrintabilityProfileId(profileId);
    const savedProfile = savedPrintabilityProfiles.find((entry) => entry.id === profileId);
    updatePrintabilityProfile(savedProfile ?? DEFAULT_PRINTABILITY_PROFILE);
  }

  function startNewPrintabilityProfile() {
    setSelectedPrintabilityProfileId("");
    updatePrintabilityProfile(DEFAULT_PRINTABILITY_PROFILE);
  }

  async function savePrintabilityProfile() {
    setIsSavingPrintabilityProfile(true);
    setMessage(null);
    try {
      const path = selectedPrintabilityProfileId
        ? `/printability-profiles/${selectedPrintabilityProfileId}`
        : "/printability-profiles";
      const savedProfile = await request<SavedPrintabilityProfile>(path, {
        method: selectedPrintabilityProfileId ? "PATCH" : "POST",
        body: JSON.stringify(toPrintabilityProfilePayload(printabilityProfile)),
      });
      setSelectedPrintabilityProfileId(savedProfile.id);
      setPrintabilityProfile(savedProfile);
      setSavedPrintabilityProfiles((current) => {
        const existing = current.some((entry) => entry.id === savedProfile.id);
        if (!existing) {
          return [...current, savedProfile].sort(comparePrinterProfiles);
        }
        return current
          .map((entry) => (entry.id === savedProfile.id ? savedProfile : entry))
          .sort(comparePrinterProfiles);
      });
      setMessage("Printer profile saved");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Printer profile save failed");
    } finally {
      setIsSavingPrintabilityProfile(false);
    }
  }

  async function deletePrintabilityProfile() {
    if (!selectedPrintabilityProfileId) {
      return;
    }
    setIsSavingPrintabilityProfile(true);
    setMessage(null);
    try {
      await requestEmpty(`/printability-profiles/${selectedPrintabilityProfileId}`, {
        method: "DELETE",
      });
      setSavedPrintabilityProfiles((current) =>
        current.filter((entry) => entry.id !== selectedPrintabilityProfileId),
      );
      startNewPrintabilityProfile();
      setMessage("Printer profile deleted");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Printer profile delete failed");
    } finally {
      setIsSavingPrintabilityProfile(false);
    }
  }

  function dismissPrintabilityResult(ruleId: string) {
    setDismissedPrintabilityResults((current) => {
      const next = new Set(current);
      next.add(ruleId);
      return next;
    });
  }

  function startNewProject() {
    setProject(null);
    setProjectName("");
    setIntent("");
    setInstruction("");
    setGenerationPrompt("");
    setSource("");
    setRevisions([]);
    setProjectMessages([]);
    setSelectedRevision(null);
    setCandidateFindings([]);
    setGeometricAnalysis(null);
    setCompileLog(null);
    setAiOutput(null);
    setRevisionDiff(null);
    setPrintabilityReport(null);
    setDismissedPrintabilityResults(new Set());
    resetRequirementState();
    resetRevisionPlanState();
    resetConfigurationState();
    setMessage("New draft workspace");
    setIsProjectDrawerOpen(false);
  }

  return (
    <main className="workspace">
      <header className="topbar">
        <div className="topbar-left">
          <button className="icon-button" onClick={() => setIsProjectDrawerOpen(true)}>
            Projects
          </button>
          <div>
            <h1>{workspaceTitle}</h1>
            <p>
              {selectedRevision
                ? `${selectedViewerLabel} - R${selectedRevision.revision_number} - ${selectedWorkflowLabel}`
                : "Draft workspace"}
            </p>
          </div>
        </div>
        <div className="topbar-actions">
          {sourceUrl ? (
            <a className="download compact-action" href={sourceUrl}>
              {selectedSourceLabel}
            </a>
          ) : null}
          {stlUrl ? (
            <a className="download compact-action" href={stlUrl}>
              STL
            </a>
          ) : null}
          {manifestUrl && selectedRevision?.output_manifest_path ? (
            <a className="download compact-action" href={manifestUrl}>
              Manifest
            </a>
          ) : null}
          {exportUrl && selectedRevision?.output_manifest_path ? (
            <a className="download compact-action" href={exportUrl}>
              ZIP
            </a>
          ) : null}
          <button className="primary" disabled={isCompiling || !canCompileSource} onClick={compileSource}>
            {isCompiling ? "Compiling" : "Compile"}
          </button>
        </div>
      </header>

      {isProjectDrawerOpen ? (
        <div className="drawer-backdrop" onClick={() => setIsProjectDrawerOpen(false)}>
          <aside className="project-drawer" aria-label="Projects" onClick={(event) => event.stopPropagation()}>
            <div className="drawer-heading">
              <div>
                <h2>Projects</h2>
                <p>{projects.length} active</p>
              </div>
              <button className="text-action" onClick={() => setIsProjectDrawerOpen(false)}>
                Close
              </button>
            </div>
            <button className="secondary full-width" onClick={startNewProject}>
              New workspace
            </button>
            <div className="project-list">
              {projects.length === 0 ? <p className="empty">No projects</p> : null}
              {projects.map((entry) => (
                <button
                  className={entry.id === project?.id ? "project-item selected" : "project-item"}
                  key={entry.id}
                  onClick={() => void selectProject(entry)}
                >
                  {entry.name}
                </button>
              ))}
            </div>
          </aside>
        </div>
      ) : null}

      <section className="main-grid">
        <section className="viewer-panel" aria-label="STL preview">
          <StlViewer stlUrl={stlUrl} highlights={printabilityHighlights} />
          <section className="prompt-dock" aria-label="Prompt chat">
            <div className="chat-log">
              <MessageList messages={projectMessages} compact />
              <WorkflowChatCards
                designPlan={designPlan}
                designSpecification={designSpecification}
                revision={selectedRevision}
                revisionPlan={revisionPlan}
                findings={candidateFindings}
              />
              {message ? <p className="message">{message}</p> : null}
            </div>
            <form className="prompt-row" onSubmit={(event) => {
              event.preventDefault();
              submitPrompt();
            }}>
              <textarea
                aria-label="AI chat message"
                placeholder={chatPlaceholder}
                rows={2}
                value={generationPrompt}
                onKeyDown={handlePromptKeyDown}
                onChange={(event) => setGenerationPrompt(event.target.value)}
              />
              <button className="secondary" disabled={isChatActionPending || !canAskAi} type="submit">
                {chatButtonLabel}
              </button>
            </form>
          </section>
        </section>

        <section className="metadata-panel" aria-label="Workspace details">
          <section className="project-card" aria-label="Project setup">
            <div className="section-heading">
              <h2>Project</h2>
              <div className="mini-actions">
                <button className="secondary compact" disabled={!canSaveProject || isSavingProject} onClick={() => void saveProject()}>
                  {isSavingProject ? "Saving" : "Save"}
                </button>
                <button className="secondary compact" disabled={!project || isSavingProject} onClick={() => void archiveProject()}>
                  Archive
                </button>
                <button className="secondary compact" disabled={!project || isSavingProject} onClick={() => void deleteProject()}>
                  Delete
                </button>
              </div>
            </div>
            <label>
              Name
              <input required value={projectName} onChange={(event) => setProjectName(event.target.value)} />
            </label>
            <label>
              Intent
              <input required value={intent} onChange={(event) => setIntent(event.target.value)} />
            </label>
            <label>
              Manual compile note
              <input value={instruction} onChange={(event) => setInstruction(event.target.value)} />
            </label>
            {project && isDraftProject && !hasProjectName ? (
              <p className="empty">Name this draft when you want it to appear in Projects.</p>
            ) : null}
          </section>

          <section className="revision-panel" aria-label="Revisions">
            {ADVANCED_WORKFLOW_ENABLED ? (
              <LifecycleStatus
                designPlan={designPlan}
                designSpecification={designSpecification}
                revision={selectedRevision}
              />
            ) : null}
            {ADVANCED_WORKFLOW_ENABLED ? (
              <>
                <DesignSpecificationReview
                  answers={clarificationAnswers}
                  canContinue={canContinueFromSpecification}
                  hasDesignPlan={Boolean(designPlan)}
                  isContinuing={isCreatingDesignPlan}
                  isSubmittingAnswers={isSubmittingClarification}
                  specification={designSpecification}
                  stageLabel={currentRequirementStage}
                  onAnswerChange={(questionId, answer) =>
                    setClarificationAnswers((current) => ({ ...current, [questionId]: answer }))
                  }
                  onContinue={() => void createDesignPlanFromSpecification()}
                  onSubmitAnswers={() => void submitClarificationAnswers()}
                />
                <DesignPlanReview
                  canApprove={canApproveCurrentDesignPlan}
                  canGenerate={canGenerateFromCurrentDesignPlan}
                  isActionPending={isDesignPlanActionPending}
                  isGenerating={isContinuingGeneration}
                  plan={designPlan}
                  stageLabel={currentDesignPlanStage}
                  onApprove={() => void approveDesignPlan()}
                  onGenerate={() => void continueGenerationFromDesignPlan()}
                  onReject={() => void rejectDesignPlan()}
                />
                <RevisionPlanReview
                  answers={revisionPlanAnswers}
                  canApprove={canApproveCurrentRevisionPlan}
                  canGenerate={canGenerateFromCurrentRevisionPlan}
                  complianceResult={revisionComplianceResult}
                  isActionPending={isRevisionPlanActionPending}
                  isGenerating={isGeneratingRevision}
                  isSubmittingAnswers={isRevisionPlanActionPending}
                  plan={revisionPlan}
                  stageLabel={currentRevisionPlanStage}
                  successResults={revisionSuccessResults}
                  onAnswerChange={(questionId, answer) =>
                    setRevisionPlanAnswers((current) => ({ ...current, [questionId]: answer }))
                  }
                  onApprove={() => void approveRevisionPlan()}
                  onGenerate={() => void generateFromRevisionPlan()}
                  onReject={() => void rejectRevisionPlan()}
                  onSubmitAnswers={() => void submitRevisionPlanClarificationAnswers()}
                />
              </>
            ) : null}
            <SourceContractRejection message={sourceContractError} />
            <h2>Revisions</h2>
            <div className="revision-list">
              {revisions.length === 0 ? <p className="empty">No revisions</p> : null}
              {revisions.map((revision) => (
                <button
                  className={revision.id === selectedRevision?.id ? "revision selected" : "revision"}
                  key={revision.id}
                  onClick={() => void selectRevision(revision)}
                >
                  <span>
                    R{revision.revision_number}
                    {revision.id === project?.active_revision_id ? " active" : ""}
                  </span>
                  <span>{revision.source_type.replace("_", " ")} - {revisionWorkflowLabel(revision)}</span>
                </button>
              ))}
            </div>
          </section>

          <CandidateReview
            acceptDisabledReason={acceptReason}
            canAccept={canAcceptSelectedRevision}
            findings={candidateFindings}
            componentRevisionSummary={componentRevisionSummary}
            geometricAnalysis={geometricAnalysis}
            isPending={isReviewActionPending}
            outputs={revisionOutputs}
            revision={selectedRevision}
            selectedOutputId={selectedOutputId}
            viewerLabel={selectedViewerLabel}
            workflowLabel={selectedWorkflowLabel}
            onAccept={() => void acceptSelectedCandidate()}
            onDismissFinding={(findingId) => void dismissCandidateFinding(findingId)}
            onRetryOutput={(output) => void retryOutput(output)}
            onReject={() => void rejectSelectedCandidate()}
            onSelectOutput={(outputId) => setSelectedOutputId(outputId)}
            onRecoverFinding={handleCandidateFindingRecovery}
            onRegenerateFromPlan={() => {
              if (designPlan && designPlan.id === selectedRevision?.design_plan_id) {
                void continueGenerationFromDesignPlan(designPlan);
                return;
              }
              setMessage("Open the approved Design Plan before regenerating this candidate");
            }}
            onReviseFromGeometricFinding={(finding) => {
              setGenerationPrompt(revisionPromptFromGeometricFinding(finding));
              setPendingRevisionFindingIds(
                finding.validation_finding_id ? [finding.validation_finding_id] : [],
              );
              setMessage("Revision prompt prepared from geometric finding");
            }}
            retryingOutputId={isRetryingOutputId}
          />

          {ADVANCED_WORKFLOW_ENABLED ? (
            <ConfigurationPanel
              canGenerate={canGenerateCurrentConfiguration}
              change={configurationPreview}
              draft={configurationDraft}
              isGenerating={isGeneratingConfiguration}
              isPreviewing={isPreviewingConfiguration}
              parameters={configurationParameters}
              presets={configurationPresets}
              selectedPresetId={selectedConfigurationPresetId}
              onDraftChange={(parameterId, value) =>
                setConfigurationDraft((current) => ({ ...current, [parameterId]: value }))
              }
              onGenerate={() => void generateConfigurationCandidate()}
              onPresetChange={(presetId) => {
                setSelectedConfigurationPresetId(presetId);
                const preset = configurationPresets.find((entry) => entry.preset_id === presetId);
                if (preset) {
                  setConfigurationDraft((current) => ({
                    ...current,
                    ...configurationDraftValues(preset.parameter_values),
                  }));
                }
              }}
              onPreview={() => void previewConfiguration()}
            />
          ) : null}

          <div ref={printabilitySectionRef}>
            <h2>Metadata</h2>
            <Metadata metadata={activeMetadata} />
            <PrintabilityInspector
              canInspect={Boolean(selectedRevision?.is_accepted)}
              dismissedRuleIds={dismissedPrintabilityResults}
              isInspecting={isInspectingPrintability}
              isSavingProfile={isSavingPrintabilityProfile}
              profile={printabilityProfile}
              report={printabilityReport}
              savedProfiles={savedPrintabilityProfiles}
              selectedProfileId={selectedPrintabilityProfileId}
              onDeleteProfile={() => void deletePrintabilityProfile()}
              onDismiss={dismissPrintabilityResult}
              onInspect={() => void inspectSelectedRevisionPrintability()}
              onNewProfile={startNewPrintabilityProfile}
              onProfileChange={updatePrintabilityProfile}
              onProfileSelect={selectPrintabilityProfile}
              onSaveProfile={() => void savePrintabilityProfile()}
            />
          </div>
          {selectedRevision?.is_accepted && selectedRevision.id !== project?.active_revision_id ? (
            <div className="actions">
              <button className="download" onClick={() => void restoreSelectedRevision()}>
                Restore revision
              </button>
            </div>
          ) : null}
          <section className="source-panel" aria-label={sourcePanelLabel}>
            <div className="section-heading">
              <h2>Source</h2>
            </div>
            <Editor
              language={sourceEditorLanguage}
              height="320px"
              options={{
                minimap: { enabled: false },
                fontSize: 13,
                wordWrap: "on",
                scrollBeyondLastLine: false,
              }}
              theme="vs-dark"
              value={source}
              onChange={(value) => setSource(value ?? "")}
            />
          </section>
          <Diagnostics compileLog={compileLog} aiOutput={aiOutput} revisionDiff={revisionDiff} />
        </section>
      </section>
    </main>
  );
}

function LifecycleStatus({
  designPlan,
  designSpecification,
  revision,
}: {
  designPlan: DesignPlan | null;
  designSpecification: DesignSpecification | null;
  revision: Revision | null;
}) {
  const steps = [
    "Describe",
    "Requirements",
    "Design Plan",
    "Approve",
    "Generate",
    "Executing CadQuery",
    "Validating topology",
    "Candidate",
    "Accept or revise",
  ];
  const currentIndex = lifecycleIndex({ designPlan, designSpecification, revision });
  return (
    <section className="lifecycle-strip" aria-label="Staged CadQuery workflow">
      {steps.map((step, index) => (
        <span
          className={index < currentIndex ? "complete" : index === currentIndex ? "current" : ""}
          key={step}
        >
          {step}
        </span>
      ))}
    </section>
  );
}

function lifecycleIndex({
  designPlan,
  designSpecification,
  revision,
}: {
  designPlan: DesignPlan | null;
  designSpecification: DesignSpecification | null;
  revision: Revision | null;
}): number {
  if (revision?.review_state === "accepted") {
    return 8;
  }
  if (revision?.review_state === "ready" || revision?.review_state === "ready_with_warnings" || revision?.review_state === "blocked") {
    return 7;
  }
  if (revision?.status === "running" || revision?.status === "compiling") {
    return 5;
  }
  if (revision?.status === "validating") {
    return 6;
  }
  if (designPlan?.generated_revision_id || designPlan?.review_state === "approved") {
    return 4;
  }
  if (designPlan?.review_state === "pending_review") {
    return 3;
  }
  if (designPlan) {
    return 2;
  }
  if (designSpecification?.generation_ready || designSpecification?.clarification_required) {
    return 1;
  }
  return 0;
}

function DesignSpecificationReview({
  answers,
  canContinue,
  hasDesignPlan,
  isContinuing,
  isSubmittingAnswers,
  specification,
  stageLabel,
  onAnswerChange,
  onContinue,
  onSubmitAnswers,
}: {
  answers: Record<string, string>;
  canContinue: boolean;
  hasDesignPlan: boolean;
  isContinuing: boolean;
  isSubmittingAnswers: boolean;
  specification: DesignSpecification | null;
  stageLabel: string;
  onAnswerChange: (questionId: string, answer: string) => void;
  onContinue: () => void;
  onSubmitAnswers: () => void;
}) {
  if (!specification) {
    return null;
  }

  const buckets = assumptionBuckets(specification);
  const requirements = specification.specification.functional_requirements ?? [];
  const questions = specification.clarification_questions;
  const traceMessage = traceFailureMessage(specification);
  const allAnswersPresent =
    questions.length > 0 && questions.every((question) => (answers[question.id] ?? "").trim().length > 0);

  return (
    <section className="requirements-review" aria-label="Requirements">
      <div className="section-heading">
        <h2>Requirements</h2>
        <span className={`requirement-state ${specification.outcome}`}>{stageLabel}</span>
      </div>
      <dl className="review-facts">
        <dt>Purpose</dt>
        <dd>{specification.specification.purpose ?? "Unknown"}</dd>
        <dt>Protected</dt>
        <dd>{protectedRequirementCount(specification)}</dd>
        <dt>Version</dt>
        <dd>{specification.version_number}</dd>
      </dl>

      {specification.outcome === "clarification_required" ? (
        <div className="clarification-list">
          {questions.map((question) => (
            <label key={question.id}>
              {question.question}
              {question.reason ? <span className="field-note">{question.reason}</span> : null}
              <input
                value={answers[question.id] ?? ""}
                onChange={(event) => onAnswerChange(question.id, event.target.value)}
              />
            </label>
          ))}
          <div className="actions">
            <button
              className="primary"
              disabled={!allAnswersPresent || isSubmittingAnswers}
              onClick={onSubmitAnswers}
            >
              {isSubmittingAnswers ? "Submitting" : "Submit answers"}
            </button>
          </div>
        </div>
      ) : null}

      {specification.outcome === "generation_ready" ? (
        <>
          {traceMessage ? <p className="error-state">{traceMessage}</p> : null}
          <SummaryList
            title="Critical dimensions"
            items={requirementProvenanceRows(specification)}
          />
          <SummaryList
            title="Protected requirements"
            items={requirements
              .filter((requirement) => requirement.protected)
              .map((requirement) => `${requirement.description} (${requirement.source})`)}
          />
          <SummaryList title="Defaults" items={defaultProvenanceRows(specification)} />
          <SummaryList title="AI assumptions" items={buckets.aiAssumptions} />
          {hasDesignPlan ? (
            <p className="empty">Design Plan created. Review it below.</p>
          ) : (
            <div className="actions">
              <button className="primary" disabled={!canContinue} onClick={onContinue}>
                {isContinuing ? "Planning" : "Create Design Plan"}
              </button>
            </div>
          )}
        </>
      ) : null}

      {specification.outcome === "requirements_conflict" ? (
        <SummaryList
          title="Conflicts"
          items={(specification.specification.conflicts ?? []).map(
            (conflict) => conflict.description ?? conflict.id ?? "Unspecified conflict",
          )}
        />
      ) : null}

      {specification.outcome === "unsupported_request" ? (
        <SummaryList
          title="Unsupported"
          items={(specification.specification.missing_requirements ?? []).map(
            (missing) => missing.reason ?? missing.label ?? missing.id ?? "Outside current scope",
          )}
        />
      ) : null}
    </section>
  );
}

function DesignPlanReview({
  canApprove,
  canGenerate,
  isActionPending,
  isGenerating,
  plan,
  stageLabel,
  onApprove,
  onGenerate,
  onReject,
}: {
  canApprove: boolean;
  canGenerate: boolean;
  isActionPending: boolean;
  isGenerating: boolean;
  plan: DesignPlan | null;
  stageLabel: string;
  onApprove: () => void;
  onGenerate: () => void;
  onReject: () => void;
}) {
  if (!plan) {
    return null;
  }

  const counts = designPlanSummaryCounts(plan);
  const parameters = plan.plan.parameters ?? [];
  const derived = plan.plan.derived_parameters ?? [];
  const components = plan.plan.components ?? [];
  const features = plan.plan.features ?? [];
  const outputs = plan.plan.printable_outputs ?? [];
  const risks = plan.plan.risks ?? [];
  const questions = designPlanClarificationQuestions(plan);

  return (
    <section className="design-plan-review" aria-label="Design Plan">
      <div className="section-heading">
        <h2>Design Plan</h2>
        <span className={`requirement-state ${plan.review_state}`}>{stageLabel}</span>
      </div>
      <dl className="review-facts">
        <dt>Level</dt>
        <dd>{plan.plan.design_level ?? "Unknown"}</dd>
        <dt>Components</dt>
        <dd>{counts.components}</dd>
        <dt>Outputs</dt>
        <dd>{counts.outputs}</dd>
        <dt>Version</dt>
        <dd>{plan.version_number}</dd>
      </dl>

      {plan.review_state === "clarification_required" ? (
        <SummaryList
          title="Planning questions"
          items={questions.map((question) =>
            [question.question ?? "Clarification needed", question.reason].filter(Boolean).join(" - "),
          )}
        />
      ) : null}

      <SummaryList
        title="Editable parameters"
        items={parameters
          .filter((parameter) => parameter.editable !== false)
          .map((parameter) =>
            `${parameter.label}: ${parameter.value ?? "unset"}${parameter.unit ? ` ${parameter.unit}` : ""}${
              parameter.protected ? " (protected)" : ""
            }`,
          )}
      />
      <SummaryList
        title="Derived parameters"
        items={derived.map((parameter) => `${parameter.label}: ${parameter.expression}`)}
      />
      <SummaryList
        title="Dependencies"
        items={(plan.plan.dependency_edges ?? []).map(
          (edge) => `${edge.from} -> ${edge.to}: ${edge.relationship}`,
        )}
      />
      <SummaryList
        title="Components"
        items={components.map((component) => `${component.label} (${component.id})`)}
      />
      <SummaryList
        title="Features"
        items={features.map((feature) => `${feature.description} (${feature.type})`)}
      />
      <SummaryList
        title="Printable outputs"
        items={outputs.map(
          (output) => `${output.label}: ${output.component_ids.join(", ")} x${output.quantity}`,
        )}
      />
      <SummaryList
        title="Risks"
        items={risks.map((risk) =>
          [risk.severity ?? "notice", risk.description ?? risk.id ?? "Risk"].join(": "),
        )}
      />

      <div className="actions">
        <button
          className="secondary"
          disabled={
            isActionPending ||
            !["pending_review", "clarification_required"].includes(plan.review_state)
          }
          onClick={onReject}
        >
          Reject
        </button>
        <button className="primary" disabled={!canApprove} onClick={onApprove}>
          {isActionPending || isGenerating ? "Starting" : "Approve and generate"}
        </button>
        {plan.review_state === "approved" ? (
          <button className="primary" disabled={!canGenerate} onClick={onGenerate}>
            {isGenerating ? "Generating" : "Generate candidate"}
          </button>
        ) : null}
      </div>
    </section>
  );
}

function SummaryList({ title, items }: { title: string; items: string[] }) {
  if (items.length === 0) {
    return null;
  }
  return (
    <div className="summary-list">
      <h3>{title}</h3>
      <ul>
        {items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </div>
  );
}

function RevisionPlanReview({
  answers,
  canApprove,
  canGenerate,
  complianceResult,
  isActionPending,
  isGenerating,
  isSubmittingAnswers,
  plan,
  stageLabel,
  successResults,
  onAnswerChange,
  onApprove,
  onGenerate,
  onReject,
  onSubmitAnswers,
}: {
  answers: Record<string, string>;
  canApprove: boolean;
  canGenerate: boolean;
  complianceResult: RevisionComplianceResult | null;
  isActionPending: boolean;
  isGenerating: boolean;
  isSubmittingAnswers: boolean;
  plan: RevisionPlan | null;
  stageLabel: string;
  successResults: RevisionSuccessResult[];
  onAnswerChange: (questionId: string, answer: string) => void;
  onApprove: () => void;
  onGenerate: () => void;
  onReject: () => void;
  onSubmitAnswers: () => void;
}) {
  if (!plan) {
    return null;
  }

  const counts = revisionPlanSummaryCounts(plan);
  const requestedChanges = plan.revision_plan.requested_changes ?? [];
  const dependencies = plan.revision_plan.required_dependency_changes ?? [];
  const protectedParameters = plan.revision_plan.protected_parameters ?? [];
  const protectedComponents = plan.revision_plan.protected_components ?? [];
  const protectedFeatures = plan.revision_plan.protected_features ?? [];
  const protectedOutputs = plan.revision_plan.protected_outputs ?? [];
  const questions = plan.clarification_questions ?? [];
  const compliance = revisionComplianceBuckets(complianceResult);
  const success = revisionSuccessBuckets(successResults);

  return (
    <section className="revision-plan-review" aria-label="Revision Plan">
      <div className="section-heading">
        <h2>Revision Plan</h2>
        <span className={`requirement-state ${plan.review_state}`}>{stageLabel}</span>
      </div>
      <p>{plan.revision_plan.summary ?? plan.user_instruction}</p>
      <dl className="review-facts compact">
        <dt>Changes</dt>
        <dd>{counts.requestedChanges}</dd>
        <dt>Dependencies</dt>
        <dd>{counts.dependencies}</dd>
        <dt>Outputs</dt>
        <dd>{counts.targetedOutputs}</dd>
        <dt>Protected</dt>
        <dd>{counts.protectedParameters + counts.protectedOutputs}</dd>
      </dl>

      {questions.length > 0 ? (
        <div className="clarification-answers">
          <h3>Revision questions</h3>
          {questions.map((question) => (
            <label key={question.id}>
              {question.question}
              {question.reason ? <span>{question.reason}</span> : null}
              <input
                value={answers[question.id] ?? ""}
                onChange={(event) => onAnswerChange(question.id, event.target.value)}
              />
            </label>
          ))}
          <button className="primary" disabled={isSubmittingAnswers} onClick={onSubmitAnswers}>
            {isSubmittingAnswers ? "Submitting" : "Submit answers"}
          </button>
        </div>
      ) : null}

      <SummaryList
        title="Requested change"
        items={requestedChanges.map((change) =>
          `${change.target_id}: ${formatUnknown(change.current_value)} -> ${formatUnknown(change.requested_value)}`,
        )}
      />
      <SummaryList
        title="Required dependent updates"
        items={dependencies.map((dependency) =>
          `${dependency.parameter_id} affects ${(dependency.affects ?? []).join(", ") || "declared dependents"}`,
        )}
      />
      <SummaryList title="Affected components" items={plan.revision_plan.targeted_components ?? []} />
      <SummaryList title="Affected outputs" items={plan.revision_plan.targeted_outputs ?? []} />
      <SummaryList
        title="Will remain unchanged"
        items={[
          ...protectedParameters.map(
            (parameter) =>
              `${parameter.parameter_id}: ${formatUnknown(parameter.expected_value)}${parameter.unit ? ` ${parameter.unit}` : ""}`,
          ),
          ...protectedComponents.map((component) => `Component ${component}`),
          ...protectedFeatures.map((feature) => `Feature ${feature}`),
          ...protectedOutputs.map((output) => `Output ${output}`),
        ]}
      />
      <SummaryList
        title="Success checks"
        items={(plan.revision_plan.success_criteria ?? []).map(
          (criterion) =>
            `${criterion.type}: ${criterion.target_id} -> ${formatUnknown(criterion.expected_value)}`,
        )}
      />

      {complianceResult ? (
        <div className="source-checks">
          <h3>Revision scope checks</h3>
          <p>{complianceResult.passed ? "Passed approved revision scope" : "Rejected before compile"}</p>
          <FindingList title="Blocking" findings={compliance.blocking} />
          <FindingList title="Advisory" findings={compliance.advisory} />
        </div>
      ) : null}

      {successResults.length > 0 ? (
        <div className="source-checks">
          <h3>Revision verification</h3>
          <SuccessList title="Verified" results={success.verified} />
          <SuccessList title="Violated" results={success.violated} />
          <SuccessList title="Unable to verify" results={success.unverifiable} />
        </div>
      ) : null}

      <div className="actions">
        <button
          className="secondary"
          disabled={
            isActionPending ||
            !["pending_review", "clarification_required"].includes(plan.review_state)
          }
          onClick={onReject}
        >
          Reject
        </button>
        <button className="primary" disabled={!canApprove} onClick={onApprove}>
          {isActionPending ? "Approving" : "Approve revision plan"}
        </button>
        <button className="primary" disabled={!canGenerate} onClick={onGenerate}>
          {isGenerating ? "Revising" : "Generate revision"}
        </button>
      </div>
    </section>
  );
}

function FindingList({
  title,
  findings,
}: {
  title: string;
  findings: Array<{ rule_id: string; title: string; explanation?: string }>;
}) {
  if (findings.length === 0) {
    return null;
  }
  return (
    <div className="summary-list">
      <h3>{title}</h3>
      <ul>
        {findings.map((finding) => (
          <li key={finding.rule_id}>
            {finding.title}
            {finding.explanation ? ` - ${finding.explanation}` : ""}
          </li>
        ))}
      </ul>
    </div>
  );
}

function SuccessList({ title, results }: { title: string; results: RevisionSuccessResult[] }) {
  if (results.length === 0) {
    return null;
  }
  return (
    <div className="summary-list">
      <h3>{title}</h3>
      <ul>
        {results.map((result) => (
          <li key={result.id}>
            {result.target_id}: expected {formatUnknown(result.expected_value)}, detected{" "}
            {formatUnknown(result.detected_value)}
          </li>
        ))}
      </ul>
    </div>
  );
}

function formatUnknown(value: unknown): string {
  if (value === null || value === undefined) {
    return "unset";
  }
  if (typeof value === "object") {
    return JSON.stringify(value);
  }
  return String(value);
}

function ConfigurationPanel({
  canGenerate,
  change,
  draft,
  isGenerating,
  isPreviewing,
  parameters,
  presets,
  selectedPresetId,
  onDraftChange,
  onGenerate,
  onPresetChange,
  onPreview,
}: {
  canGenerate: boolean;
  change: ConfigurationChange | null;
  draft: Record<string, string | number | boolean>;
  isGenerating: boolean;
  isPreviewing: boolean;
  parameters: ConfigurationParameter[];
  presets: ConfigurationPreset[];
  selectedPresetId: string;
  onDraftChange: (parameterId: string, value: string | number | boolean) => void;
  onGenerate: () => void;
  onPresetChange: (presetId: string) => void;
  onPreview: () => void;
}) {
  if (parameters.length === 0) {
    return null;
  }
  return (
    <section className="configuration-panel" aria-label="Configure parameters">
      <div className="section-heading">
        <div>
          <h2>Configure</h2>
          <p>{configurationStateLabel(change?.validation_state ?? null)}</p>
        </div>
      </div>
      {presets.length > 0 ? (
        <label>
          Preset
          <select value={selectedPresetId} onChange={(event) => onPresetChange(event.target.value)}>
            <option value="">Custom</option>
            {presets.map((preset) => (
              <option key={`${preset.source}-${preset.preset_id}`} value={preset.preset_id}>
                {preset.label}
              </option>
            ))}
          </select>
        </label>
      ) : null}
      <div className="configuration-controls">
        {parameters.map((parameter) => {
          const kind = configurationControlKind(parameter);
          const value = draft[parameter.id] ?? parameter.value ?? "";
          return (
            <label key={parameter.id}>
              <span>
                {parameter.label}
                {parameter.unit ? ` (${parameter.unit})` : ""}
              </span>
              {kind === "checkbox" ? (
                <input
                  checked={Boolean(value)}
                  type="checkbox"
                  onChange={(event) => onDraftChange(parameter.id, event.target.checked)}
                />
              ) : kind === "select" ? (
                <select
                  value={String(value)}
                  onChange={(event) => onDraftChange(parameter.id, event.target.value)}
                >
                  {parameter.allowed_values.map((option) => (
                    <option key={String(option)} value={String(option)}>
                      {String(option)}
                    </option>
                  ))}
                </select>
              ) : kind === "number" ? (
                <input
                  max={parameter.maximum ?? undefined}
                  min={parameter.minimum ?? undefined}
                  step={parameter.type === "integer" ? 1 : 0.1}
                  type="number"
                  value={String(value)}
                  onChange={(event) => onDraftChange(parameter.id, event.target.value)}
                />
              ) : (
                <input disabled value={String(value)} readOnly />
              )}
              <small>
                {parameter.editable && parameter.source_mapped ? "Editable" : "Requires design revision"}
                {parameter.affected_outputs.length > 0 ? ` - outputs: ${parameter.affected_outputs.join(", ")}` : ""}
              </small>
            </label>
          );
        })}
      </div>
      {change ? (
        <div className={`configuration-summary ${change.validation_state}`}>
          <p>{configurationImpactLabel(change)}</p>
          {change.validation_errors.length > 0 ? (
            <ul>
              {change.validation_errors.map((error) => (
                <li key={`${error.code}-${error.parameter_id}`}>
                  {error.parameter_id}: {error.message}
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
      <div className="actions">
        <button className="secondary" disabled={isPreviewing || isGenerating} onClick={onPreview}>
          {isPreviewing ? "Previewing" : "Preview configuration"}
        </button>
        <button className="primary" disabled={!canGenerate} onClick={onGenerate}>
          {isGenerating ? "Generating" : "Generate candidate"}
        </button>
      </div>
    </section>
  );
}

function CandidateReview({
  acceptDisabledReason,
  canAccept,
  findings,
  componentRevisionSummary,
  geometricAnalysis,
  isPending,
  outputs,
  revision,
  selectedOutputId,
  viewerLabel,
  workflowLabel,
  onAccept,
  onDismissFinding,
  onRetryOutput,
  onReject,
  onSelectOutput,
  onRecoverFinding,
  onRegenerateFromPlan,
  onReviseFromGeometricFinding,
  retryingOutputId,
}: {
  acceptDisabledReason: string | null;
  canAccept: boolean;
  findings: CandidateFinding[];
  componentRevisionSummary: ComponentRevisionSummary | null;
  geometricAnalysis: GeometricAnalysis | null;
  isPending: boolean;
  outputs: RevisionOutput[];
  revision: Revision | null;
  selectedOutputId: string | null;
  viewerLabel: string;
  workflowLabel: string;
  onAccept: () => void;
  onDismissFinding: (findingId: string) => void;
  onRetryOutput: (output: RevisionOutput) => void;
  onReject: () => void;
  onSelectOutput: (outputId: string) => void;
  onRecoverFinding: (
    finding: CandidateFinding,
    actionKind: CandidateFindingRecoveryActionKind,
  ) => void;
  onRegenerateFromPlan: () => void;
  onReviseFromGeometricFinding: (finding: GeometricFinding) => void;
  retryingOutputId: string | null;
}) {
  if (!revision) {
    return null;
  }

  const isCandidate = isOpenCandidate(revision);
  const nonGeometricFindings = findings.filter((finding) => finding.category !== "geometry");
  const buckets = candidateFindingBuckets(nonGeometricFindings);
  const sourceChecks = sourceCheckSummary(findings);
  const consistency = revision.design_consistency ?? null;
  const consistencyFindings = consistency?.findings.filter((finding) => finding.is_blocking) ?? [];

  return (
    <section className="candidate-review" aria-label="Candidate review">
      <div className="section-heading">
        <h2>Review</h2>
        <span className={`review-state ${revision.review_state ?? "historical"}`}>{workflowLabel}</span>
      </div>
      <dl className="review-facts">
        <dt>Viewer</dt>
        <dd>{viewerLabel}</dd>
        {revision.expected_output_count ? (
          <>
            <dt>Outputs</dt>
            <dd>{revision.successful_output_count ?? 0}/{revision.expected_output_count}</dd>
          </>
        ) : null}
        <dt>Blocking</dt>
        <dd>{revision.validation_summary.blocking_count}</dd>
        <dt>Warnings</dt>
        <dd>{revision.validation_summary.advisory_count}</dd>
        <dt>Design consistency</dt>
        <dd>{designConsistencyLabel(revision)}</dd>
      </dl>
      <OutputReview
        outputs={outputs}
        selectedOutputId={selectedOutputId}
        onRetryOutput={onRetryOutput}
        onSelectOutput={onSelectOutput}
        retryingOutputId={retryingOutputId}
      />
      {isCandidate ? (
        <div className="actions">
          <button className="primary" disabled={!canAccept || isPending} onClick={onAccept}>
            {isPending ? "Working" : "Accept"}
          </button>
          <button className="secondary" disabled={isPending} onClick={onReject}>
            Reject
          </button>
        </div>
      ) : null}
      {isCandidate && !canAccept && acceptDisabledReason ? (
        <p className="blocked-reason">{acceptDisabledReason}</p>
      ) : null}
      {consistency && consistency.status !== "passed" ? (
        <div className="consistency-block">
          <h3>This design cannot be safely revised yet.</h3>
          <p>Volundr found an internal mismatch between the approved design plan and generated model.</p>
          {consistencyFindings.length > 0 ? (
            <>
              <h4>Internal alignment issues</h4>
              <ul>
                {consistencyFindings.slice(0, 5).map((finding) => (
                  <li key={`${finding.rule_id}-${finding.explanation}`}>{finding.explanation}</li>
                ))}
              </ul>
            </>
          ) : null}
          <div className="actions compact">
            <button className="secondary" disabled={isPending} onClick={onRegenerateFromPlan}>
              Regenerate from approved plan
            </button>
          </div>
          {consistency.findings.length > 0 ? (
            <details>
              <summary>View technical details</summary>
              <ul>
                {consistency.findings.map((finding) => (
                  <li key={`${finding.rule_id}-${finding.explanation}`}>
                    {finding.rule_id}: {finding.explanation}
                  </li>
                ))}
              </ul>
            </details>
          ) : null}
        </div>
      ) : null}
      <SourceCheckSummary
        findings={sourceChecks.blocking.concat(sourceChecks.advisory)}
        showPassed={isCandidate}
      />
      <ComponentRevisionSummaryView summary={componentRevisionSummary} />
      <GeometricCheckSummary
        analysis={geometricAnalysis}
        showLegacyMessage={revision.status === "succeeded" && !geometricAnalysis}
        onReviseFromFinding={onReviseFromGeometricFinding}
      />
      {buckets.blocking.length > 0 ? (
        <FindingGroup
          findings={buckets.blocking}
          title="Blocking findings"
          onRecoverFinding={onRecoverFinding}
        />
      ) : null}
      {buckets.advisory.length > 0 ? (
        <FindingGroup
          findings={buckets.advisory}
          title="Advisory warnings"
          onDismissFinding={onDismissFinding}
        />
      ) : null}
      {isCandidate && findings.length === 0 && !geometricAnalysis ? (
        <p className="empty">No validation findings</p>
      ) : null}
    </section>
  );
}

function OutputReview({
  outputs,
  selectedOutputId,
  onRetryOutput,
  onSelectOutput,
  retryingOutputId,
}: {
  outputs: RevisionOutput[];
  selectedOutputId: string | null;
  onRetryOutput: (output: RevisionOutput) => void;
  onSelectOutput: (outputId: string) => void;
  retryingOutputId: string | null;
}) {
  if (outputs.length === 0) {
    return null;
  }
  return (
    <div className="candidate-findings output-review">
      <h3>Printable outputs</h3>
      <div className="output-list">
        {outputs.map((output) => (
          <article
            className={output.id === selectedOutputId ? "output-card selected" : "output-card"}
            key={output.id}
          >
            <button className="output-select" onClick={() => onSelectOutput(output.id)}>
              <span>{output.label}</span>
              <span className={`review-state ${output.execution_state}`}>{outputStateLabel(output)}</span>
            </button>
            <dl className="review-facts compact">
              <dt>Quantity</dt>
              <dd>{output.quantity}</dd>
              <dt>Need</dt>
              <dd>{output.required ? "Required" : "Optional"}</dd>
              <dt>Components</dt>
              <dd>{output.component_ids.length > 0 ? output.component_ids.join(", ") : output.component_id ?? "Unassigned"}</dd>
              <dt>Size</dt>
              <dd>{outputDimensionsLabel(output)}</dd>
              <dt>Topology</dt>
              <dd>{outputTopologyLabel(output)}</dd>
              <dt>Solid count</dt>
              <dd>{outputSolidCountLabel(output)}</dd>
              <dt>Warnings</dt>
              <dd>{output.validation_summary.advisory_count}</dd>
            </dl>
            {output.compile_error ? <p className="blocked-reason">{output.compile_error}</p> : null}
            <div className="actions">
              {output.step_path ? (
                <a className="download compact-action" href={`${API_BASE}/revision-outputs/${output.id}/step`}>
                  STEP
                </a>
              ) : null}
              {output.stl_path ? (
                <a className="download compact-action" href={`${API_BASE}/revision-outputs/${output.id}/stl`}>
                  STL
                </a>
              ) : null}
              {output.compile_log_path ? (
                <a className="download compact-action" href={`${API_BASE}/revision-outputs/${output.id}/compile-log`}>
                  Log
                </a>
              ) : null}
              {canRetryOutput(output) ? (
                <button className="secondary compact" disabled={retryingOutputId === output.id} onClick={() => onRetryOutput(output)}>
                  {retryingOutputId === output.id ? "Retrying" : "Retry"}
                </button>
              ) : null}
            </div>
          </article>
        ))}
      </div>
    </div>
  );
}

function ComponentRevisionSummaryView({ summary }: { summary: ComponentRevisionSummary | null }) {
  if (!summary) {
    return null;
  }
  const counts = componentRevisionCounts(summary);
  const payload = summary.summary;
  return (
    <div className="candidate-findings component-revision-summary">
      <h3>Component revision</h3>
      <dl className="review-facts compact">
        <dt>Targets</dt>
        <dd>{counts.targetedOutputs}</dd>
        <dt>Protected</dt>
        <dd>{counts.protectedOutputs}</dd>
        <dt>Drift</dt>
        <dd>{counts.unexpectedProtectedChanges}</dd>
        <dt>Interfaces</dt>
        <dd>{counts.verifiedInterfaces}/{counts.verifiedInterfaces + counts.violatedInterfaces}</dd>
      </dl>
      <SummaryList
        title="Changed"
        items={(payload.targeted_outputs ?? []).map(
          (output) => `${output.output_id}: ${componentTargetStateLabel(output.change_state)}`,
        )}
      />
      <SummaryList
        title="Preserved"
        items={(payload.protected_outputs ?? []).map(
          (output) => `${output.output_id}: ${componentPreservationStateLabel(output.preservation_state)}`,
        )}
      />
      <SummaryList
        title="Interfaces"
        items={(payload.interfaces ?? []).map(
          (check) =>
            `${check.interface_id} ${check.parameter_id}: ${check.verification_state}${check.is_blocking ? " blocking" : ""}`,
        )}
      />
    </div>
  );
}

function componentTargetStateLabel(state: string): string {
  return state.replaceAll("_", " ");
}

function componentPreservationStateLabel(state: string): string {
  return state.replaceAll("_", " ");
}

function GeometricCheckSummary({
  analysis,
  showLegacyMessage,
  onReviseFromFinding,
}: {
  analysis: GeometricAnalysis | null;
  showLegacyMessage: boolean;
  onReviseFromFinding: (finding: GeometricFinding) => void;
}) {
  if (!analysis) {
    if (!showLegacyMessage) {
      return null;
    }
    return (
      <div className="candidate-findings geometric-checks">
        <h3>Geometric checks</h3>
        <p className="empty">Geometric invariants not evaluated</p>
      </div>
    );
  }

  const buckets = geometricFindingBuckets(analysis.findings);
  return (
    <div className="candidate-findings geometric-checks">
      <h3>Geometric checks</h3>
      <p className="empty">
        {`${buckets.verified.length} verified, ${buckets.violated.length} violated, ${buckets.unverifiable.length} unable to verify`}
      </p>
      <GeometricFindingGroup
        findings={buckets.verified}
        title="Verified"
        onReviseFromFinding={onReviseFromFinding}
      />
      <GeometricFindingGroup
        findings={buckets.violated}
        title="Violated"
        onReviseFromFinding={onReviseFromFinding}
      />
      <GeometricFindingGroup
        findings={buckets.unverifiable}
        title="Unable to verify"
        onReviseFromFinding={onReviseFromFinding}
      />
    </div>
  );
}

function GeometricFindingGroup({
  findings,
  title,
  onReviseFromFinding,
}: {
  findings: GeometricFinding[];
  title: string;
  onReviseFromFinding: (finding: GeometricFinding) => void;
}) {
  if (findings.length === 0) {
    return null;
  }
  return (
    <div className="geometry-group">
      <h4>{title}</h4>
      {findings.map((finding) => (
        <article className={`candidate-finding ${finding.severity}`} key={`${finding.rule_id}-${finding.requirement_id ?? finding.feature_id ?? finding.title}`}>
          <div className="result-row">
            <span className={`severity ${finding.severity}`}>{finding.verification_state}</span>
            <span className="rule-id">{finding.rule_id}</span>
          </div>
          <p>{finding.explanation}</p>
          <p className="correction">
            {finding.requirement_id ? `${finding.requirement_id}. ` : ""}
            {finding.expected_value !== null ? `Expected ${formatGeometryValue(finding.expected_value, finding.unit)}. ` : ""}
            {finding.detected_value !== null ? `Detected ${formatGeometryValue(finding.detected_value, finding.unit)}. ` : ""}
            {finding.tolerance !== null ? `Tolerance ${formatGeometryValue(finding.tolerance, finding.unit)}. ` : ""}
            Confidence {Math.round(finding.confidence * 100)}%.
          </p>
          {finding.suggested_correction ? <p className="correction">{finding.suggested_correction}</p> : null}
          {finding.validation_finding_id ? (
            <button className="text-action" onClick={() => onReviseFromFinding(finding)}>
              Revise from finding
            </button>
          ) : null}
        </article>
      ))}
    </div>
  );
}

function SourceContractRejection({ message }: { message: string | null }) {
  if (!message) {
    return null;
  }
  const lines = message.split("\n").filter(Boolean);
  return (
    <section className="candidate-review source-checks" aria-label="Source checks">
      <div className="section-heading">
        <h2>Source checks</h2>
        <span className="review-state blocked">Rejected</span>
      </div>
      <p className="blocked-reason">{lines[0]}</p>
      {lines.length > 1 ? (
        <ul className="source-check-list">
          {lines.slice(1).map((line) => (
            <li key={line}>{line.replace(/^- /, "")}</li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}

function SourceCheckSummary({
  findings,
  showPassed,
}: {
  findings: CandidateFinding[];
  showPassed: boolean;
}) {
  if (findings.length === 0) {
    if (!showPassed) {
      return null;
    }
    return (
      <div className="candidate-findings source-checks">
        <h3>Source checks</h3>
        <p className="empty">Passed required structure and protected dimensions</p>
      </div>
    );
  }
  const blockingCount = findings.filter((finding) => finding.is_blocking).length;
  return (
    <div className="candidate-findings source-checks">
      <h3>Source checks</h3>
      <p className="empty">
        {blockingCount > 0
          ? `${blockingCount} blocking source ${blockingCount === 1 ? "finding" : "findings"}`
          : `${findings.length} quality ${findings.length === 1 ? "finding" : "findings"}`}
      </p>
      {findings.map((finding) => (
        <article className={`candidate-finding ${finding.severity}`} key={finding.id}>
          <div className="result-row">
            <span className={`severity ${finding.severity}`}>{finding.severity}</span>
            <span className="rule-id">{finding.rule_id}</span>
          </div>
          <p>{finding.explanation}</p>
          {finding.threshold_value || finding.detected_value || finding.source_line_start ? (
            <p className="correction">
              {finding.threshold_value ? `Expected ${finding.threshold_value}. ` : ""}
              {finding.detected_value ? `Detected ${finding.detected_value}. ` : ""}
              {finding.source_line_start ? `Line ${finding.source_line_start}.` : ""}
            </p>
          ) : null}
        </article>
      ))}
    </div>
  );
}

function FindingGroup({
  findings,
  title,
  onDismissFinding,
  onRecoverFinding,
}: {
  findings: CandidateFinding[];
  title: string;
  onDismissFinding?: (findingId: string) => void;
  onRecoverFinding?: (
    finding: CandidateFinding,
    actionKind: CandidateFindingRecoveryActionKind,
  ) => void;
}) {
  return (
    <div className="candidate-findings">
      <h3>{title}</h3>
      {findings.map((finding) => (
        <article className={`candidate-finding ${finding.severity}`} key={finding.id}>
          <div className="result-row">
            <span className={`severity ${finding.severity}`}>{finding.severity}</span>
            <span className="rule-id">{finding.rule_id}</span>
          </div>
          <p>{finding.explanation}</p>
          <p className="correction">{finding.suggested_correction}</p>
          {onRecoverFinding
            ? candidateFindingRecoveryActions(finding).map((action) => (
                <button
                  className="text-action"
                  key={`${finding.id}-${action.kind}`}
                  title={action.description}
                  onClick={() => onRecoverFinding(finding, action.kind)}
                >
                  {action.label}
                </button>
              ))
            : null}
          {onDismissFinding && finding.finding_state !== "dismissed" ? (
            <button className="text-action" onClick={() => onDismissFinding(finding.id)}>
              Dismiss
            </button>
          ) : null}
          {finding.finding_state === "dismissed" ? <p className="empty">Dismissed</p> : null}
        </article>
      ))}
    </div>
  );
}

function PrintabilityInspector({
  canInspect,
  dismissedRuleIds,
  isInspecting,
  isSavingProfile,
  profile,
  report,
  savedProfiles,
  selectedProfileId,
  onDeleteProfile,
  onDismiss,
  onInspect,
  onNewProfile,
  onProfileChange,
  onProfileSelect,
  onSaveProfile,
}: {
  canInspect: boolean;
  dismissedRuleIds: Set<string>;
  isInspecting: boolean;
  isSavingProfile: boolean;
  profile: PrintabilityProfile;
  report: PrintabilityReport | null;
  savedProfiles: SavedPrintabilityProfile[];
  selectedProfileId: string;
  onDeleteProfile: () => void;
  onDismiss: (ruleId: string) => void;
  onInspect: () => void;
  onNewProfile: () => void;
  onProfileChange: (profile: PrintabilityProfile) => void;
  onProfileSelect: (profileId: string) => void;
  onSaveProfile: () => void;
}) {
  function setNumber(path: keyof PrintabilityProfile, value: string) {
    const parsed = Number(value);
    if (!Number.isFinite(parsed) || parsed <= 0) {
      return;
    }
    onProfileChange({ ...profile, [path]: parsed });
  }

  function setBuildVolume(axis: keyof BuildVolumeProfile, value: string) {
    const parsed = Number(value);
    if (!Number.isFinite(parsed) || parsed <= 0) {
      return;
    }
    onProfileChange({
      ...profile,
      build_volume: {
        ...profile.build_volume,
        [axis]: parsed,
      },
    });
  }

  const sortedResults = useMemo(
    () =>
      report
        ? [...report.results].sort(
            (left, right) => severityRank(right.severity) - severityRank(left.severity),
          )
        : [],
    [report],
  );

  return (
    <section className="printability" aria-label="Printability inspector">
      <div className="section-heading">
        <h2>Printability</h2>
        <button className="secondary compact" disabled={!canInspect || isInspecting} onClick={onInspect}>
          {isInspecting ? "Inspecting" : "Inspect"}
        </button>
      </div>
      <div className="printer-profile">
        <div className="profile-actions">
          <label>
            Saved profile
            <select
              value={selectedProfileId}
              onChange={(event) => onProfileSelect(event.target.value)}
            >
              <option value="">Unsaved profile</option>
              {savedProfiles.map((savedProfile) => (
                <option key={savedProfile.id} value={savedProfile.id}>
                  {savedProfile.printer_name}
                </option>
              ))}
            </select>
          </label>
          <div className="mini-actions profile-buttons">
            <button className="secondary compact" disabled={isSavingProfile} onClick={onNewProfile}>
              New
            </button>
            <button className="secondary compact" disabled={isSavingProfile} onClick={onSaveProfile}>
              {isSavingProfile ? "Saving" : "Save"}
            </button>
            <button
              className="secondary compact"
              disabled={!selectedProfileId || isSavingProfile}
              onClick={onDeleteProfile}
            >
              Delete
            </button>
          </div>
        </div>
        <label>
          Printer
          <input
            value={profile.printer_name}
            onChange={(event) => onProfileChange({ ...profile, printer_name: event.target.value })}
          />
        </label>
        <div className="profile-grid">
          <label>
            X mm
            <input
              min="1"
              step="1"
              type="number"
              value={profile.build_volume.x_mm}
              onChange={(event) => setBuildVolume("x_mm", event.target.value)}
            />
          </label>
          <label>
            Y mm
            <input
              min="1"
              step="1"
              type="number"
              value={profile.build_volume.y_mm}
              onChange={(event) => setBuildVolume("y_mm", event.target.value)}
            />
          </label>
          <label>
            Z mm
            <input
              min="1"
              step="1"
              type="number"
              value={profile.build_volume.z_mm}
              onChange={(event) => setBuildVolume("z_mm", event.target.value)}
            />
          </label>
          <label>
            Nozzle
            <input
              min="0.1"
              step="0.05"
              type="number"
              value={profile.nozzle_diameter_mm}
              onChange={(event) => setNumber("nozzle_diameter_mm", event.target.value)}
            />
          </label>
          <label>
            Layer
            <input
              min="0.05"
              step="0.05"
              type="number"
              value={profile.default_layer_height_mm}
              onChange={(event) => setNumber("default_layer_height_mm", event.target.value)}
            />
          </label>
        </div>
      </div>
      {!canInspect ? <p className="empty">Compile a successful revision to inspect printability.</p> : null}
      {report ? (
        <div className="printability-results">
          {sortedResults.map((result) => {
            const dismissed = result.dismissed || dismissedRuleIds.has(result.rule_id);
            return (
              <article
                className={`printability-result ${result.severity.toLowerCase()}${dismissed ? " dismissed" : ""}`}
                key={result.rule_id}
              >
                <div className="result-row">
                  <span className={`severity ${result.severity.toLowerCase()}`}>{result.severity}</span>
                  <span className="rule-id">{result.rule_id}</span>
                </div>
                <p>{result.explanation}</p>
                <p className="correction">{result.suggested_correction}</p>
                <dl className="result-facts">
                  <dt>Detected</dt>
                  <dd>{formatDetectedValue(result.detected_value.value, result.detected_value.units)}</dd>
                  <dt>Count</dt>
                  <dd>{result.affected_count ?? "n/a"}</dd>
                  <dt>Area</dt>
                  <dd>
                    {result.affected_area_mm2 === null
                      ? "n/a"
                      : `${result.affected_area_mm2.toFixed(2)} mm2`}
                  </dd>
                  <dt>Orientation</dt>
                  <dd>{result.orientation_dependent ? "Depends on orientation" : "Independent"}</dd>
                  <dt>Dismissed</dt>
                  <dd>{dismissed ? "Intentional" : "No"}</dd>
                </dl>
                {!dismissed ? (
                  <button className="text-action" onClick={() => onDismiss(result.rule_id)}>
                    Dismiss
                  </button>
                ) : null}
              </article>
            );
          })}
        </div>
      ) : null}
    </section>
  );
}

function MessageList({ compact = false, messages }: { compact?: boolean; messages: ProjectMessage[] }) {
  if (messages.length === 0) {
    return <p className="empty">No messages</p>;
  }
  return (
    <div className={compact ? "message-list compact-chat" : "message-list"}>
      {messages.slice(compact ? -5 : 0).map((message) => (
        <div className="project-message" key={message.id}>
          <span>{message.role.replace("_", " ")}</span>
          <p>{message.content}</p>
        </div>
      ))}
    </div>
  );
}

function WorkflowChatCards({
  designPlan,
  designSpecification,
  findings,
  revision,
  revisionPlan,
}: {
  designPlan: DesignPlan | null;
  designSpecification: DesignSpecification | null;
  findings: CandidateFinding[];
  revision: Revision | null;
  revisionPlan: RevisionPlan | null;
}) {
  const blockingFindings = findings.filter((finding) => finding.is_blocking);
  if (revisionPlan?.review_state === "clarification_required") {
    return (
      <ChatStageCard
        title="Revision clarification"
        body={revisionPlan.clarification_questions.map((question) => question.question).join(" ")}
      />
    );
  }
  if (revisionPlan?.review_state === "pending_review") {
    return (
      <ChatStageCard
        title="Revision plan ready"
        body="Review the scoped change, then approve it to generate a revised candidate."
      />
    );
  }
  if (revision?.review_state === "blocked" && blockingFindings.length > 0) {
    return (
      <ChatStageCard
        title="Candidate blocked"
        body={`${blockingFindings.length} blocking ${blockingFindings.length === 1 ? "finding needs" : "findings need"} a revision or clarification before acceptance.`}
      />
    );
  }
  if (designPlan?.review_state === "pending_review") {
    return (
      <ChatStageCard
        title="Design Plan ready"
        body="Review the product plan. Approving it will start model generation."
      />
    );
  }
  if (designPlan?.review_state === "clarification_required") {
    return (
      <ChatStageCard
        title="Plan clarification"
        body={(designPlan.plan.clarification_questions ?? []).map((question) => question.question ?? "").join(" ")}
      />
    );
  }
  if (designSpecification?.outcome === "clarification_required") {
    return (
      <ChatStageCard
        title="Clarification needed"
        body={designSpecification.clarification_questions.map((question) => question.question).join(" ")}
      />
    );
  }
  if (designSpecification?.outcome === "generation_ready" && !designPlan) {
    return (
      <ChatStageCard
        title="Requirements ready"
        body="Create a Design Plan to turn these requirements into components, parameters, and printable outputs."
      />
    );
  }
  return null;
}

function ChatStageCard({ body, title }: { body: string; title: string }) {
  return (
    <div className="chat-stage-card">
      <span>{title}</span>
      <p>{body}</p>
    </div>
  );
}

function severityRank(severity: PrintabilitySeverity): number {
  return {
    Pass: 0,
    Notice: 1,
    Warning: 2,
    Critical: 3,
  }[severity];
}

function formatDetectedValue(value: number | string, units: string): string {
  const formattedValue = typeof value === "number" ? value.toFixed(3).replace(/\.?0+$/, "") : value;
  return `${formattedValue} ${units}`;
}

function formatGeometryValue(value: number | string, unit: string | null): string {
  const formatted = typeof value === "number" ? value.toFixed(3).replace(/\.?0+$/, "") : value;
  return `${formatted}${unit ? ` ${unit}` : ""}`;
}

function toPrintabilityProfilePayload(profile: PrintabilityProfile): PrintabilityProfile {
  return {
    profile_version: profile.profile_version,
    printer_name: profile.printer_name,
    process: profile.process,
    material_behavior: profile.material_behavior,
    build_volume: {
      x_mm: profile.build_volume.x_mm,
      y_mm: profile.build_volume.y_mm,
      z_mm: profile.build_volume.z_mm,
    },
    nozzle_diameter_mm: profile.nozzle_diameter_mm,
    default_layer_height_mm: profile.default_layer_height_mm,
  };
}

function comparePrinterProfiles(left: SavedPrintabilityProfile, right: SavedPrintabilityProfile): number {
  return left.printer_name.localeCompare(right.printer_name);
}

function isOpenCandidate(revision: Revision): boolean {
  return revision.review_state === "ready" || revision.review_state === "ready_with_warnings" || revision.review_state === "blocked";
}

function Diagnostics({
  compileLog,
  aiOutput,
  revisionDiff,
}: {
  compileLog: string | null;
  aiOutput: string | null;
  revisionDiff: string | null;
}) {
  if (!compileLog?.trim() && !aiOutput?.trim() && !revisionDiff?.trim()) {
    return null;
  }
  return (
    <section className="diagnostics" aria-label="Compile diagnostics">
      <h2>Diagnostics</h2>
      {compileLog?.trim() ? (
        <>
          <h3>Compile</h3>
          <pre>{compileLog}</pre>
        </>
      ) : null}
      {aiOutput?.trim() ? (
        <>
          <h3>AI Output</h3>
          <pre>{aiOutput}</pre>
        </>
      ) : null}
      {revisionDiff?.trim() ? (
        <>
          <h3>Diff</h3>
          <pre>{revisionDiff}</pre>
        </>
      ) : null}
    </section>
  );
}

function Metadata({ metadata }: { metadata: MeshMetadata | null }) {
  const rows = useMemo(
    () =>
      metadata
        ? [
            ["X", `${metadata.size_x_mm.toFixed(2)} mm`],
            ["Y", `${metadata.size_y_mm.toFixed(2)} mm`],
            ["Z", `${metadata.size_z_mm.toFixed(2)} mm`],
            ["Volume", `${metadata.volume_mm3.toFixed(2)} mm3`],
            ["Triangles", metadata.triangle_count.toString()],
            ["Components", metadata.connected_components.toString()],
            ["Watertight", metadata.is_watertight ? "Yes" : "No"],
          ]
        : [],
    [metadata],
  );

  if (!metadata) {
    return <p className="empty">No mesh</p>;
  }

  return (
    <dl className="metadata-list">
      {rows.map(([label, value]) => (
        <React.Fragment key={label}>
          <dt>{label}</dt>
          <dd>{value}</dd>
        </React.Fragment>
      ))}
    </dl>
  );
}

function StlViewer({
  highlights,
  stlUrl,
}: {
  highlights: PrintabilityHighlight[];
  stlUrl: string | null;
}) {
  const mountRef = useRef<HTMLDivElement | null>(null);
  const gizmoRef = useRef<HTMLDivElement | null>(null);
  const fitViewRef = useRef<() => void>(() => undefined);
  const setViewRef = useRef<(view: ViewerCameraPreset) => void>(() => undefined);

  useEffect(() => {
    const mount = mountRef.current;
    if (!mount) {
      return;
    }

    mount.replaceChildren();
    const width = Math.max(1, mount.clientWidth);
    const height = Math.max(1, mount.clientHeight);
    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0xf5f7f4);
    const camera = new THREE.PerspectiveCamera(38, width / height, 0.1, 10000);
    camera.up.set(0, 0, 1);
    camera.position.set(180, -220, 135);
    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setSize(width, height);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    mount.appendChild(renderer.domElement);

    const gizmoMount = gizmoRef.current;
    const gizmoRenderer = gizmoMount
      ? new THREE.WebGLRenderer({ alpha: true, antialias: true })
      : null;
    const gizmoScene = createViewGizmoScene();
    const gizmoCamera = new THREE.OrthographicCamera(-1.6, 1.6, 1.6, -1.6, 0.1, 20);
    if (gizmoMount && gizmoRenderer) {
      gizmoMount.replaceChildren();
      gizmoRenderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
      gizmoRenderer.setSize(86, 86);
      gizmoMount.appendChild(gizmoRenderer.domElement);
    }

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.08;
    controls.enablePan = true;
    controls.enableZoom = true;
    controls.screenSpacePanning = true;
    controls.mouseButtons = {
      LEFT: THREE.MOUSE.ROTATE,
      MIDDLE: THREE.MOUSE.DOLLY,
      RIGHT: THREE.MOUSE.PAN,
    };
    controls.touches = {
      ONE: THREE.TOUCH.ROTATE,
      TWO: THREE.TOUCH.DOLLY_PAN,
    };

    const resizeObserver = new ResizeObserver(() => {
      const nextWidth = Math.max(1, mount.clientWidth);
      const nextHeight = Math.max(1, mount.clientHeight);
      if (nextWidth <= 0 || nextHeight <= 0) {
        return;
      }
      camera.aspect = nextWidth / nextHeight;
      camera.updateProjectionMatrix();
      renderer.setSize(nextWidth, nextHeight);
    });
    resizeObserver.observe(mount);

    const ambient = new THREE.HemisphereLight(0xffffff, 0x9aa39c, 2.0);
    scene.add(ambient);
    const keyLight = new THREE.DirectionalLight(0xffffff, 2.4);
    keyLight.position.set(180, -220, 260);
    keyLight.castShadow = true;
    scene.add(keyLight);
    const fillLight = new THREE.DirectionalLight(0xdde8ea, 0.9);
    fillLight.position.set(-160, 140, 140);
    scene.add(fillLight);

    const grid = createBuildPlateGrid(256);
    scene.add(grid);
    const axes = new THREE.AxesHelper(42);
    axes.position.set(0, 0, 0.4);
    scene.add(axes);

    let frame = 0;
    let modelGroup: THREE.Group | null = null;
    let modelBounds: THREE.Box3 | null = null;
    let disposed = false;
    let gizmoDragging = false;
    let lastGizmoPointer: { x: number; y: number } | null = null;

    const fitCameraToBounds = (preset: ViewerCameraPreset = "iso") => {
      const bounds = modelBounds ?? new THREE.Box3(
        new THREE.Vector3(-80, -80, 0),
        new THREE.Vector3(80, 80, 80),
      );
      const center = bounds.getCenter(new THREE.Vector3());
      const size = bounds.getSize(new THREE.Vector3());
      const maxDim = Math.max(size.x, size.y, size.z, 80);
      const fov = THREE.MathUtils.degToRad(camera.fov);
      const distance = Math.max(140, (maxDim / (2 * Math.tan(fov / 2))) * 1.55);
      const direction = cameraPresetDirection(preset);
      controls.target.copy(center);
      camera.near = Math.max(0.1, distance / 1000);
      camera.far = Math.max(2000, distance * 10);
      camera.position.copy(center).add(direction.multiplyScalar(distance));
      camera.updateProjectionMatrix();
      camera.lookAt(center);
      controls.update();
    };

    const orbitCameraFromGizmoDrag = (deltaX: number, deltaY: number) => {
      const offset = camera.position.clone().sub(controls.target);
      const spherical = new THREE.Spherical().setFromVector3(offset);
      spherical.theta -= deltaX * 0.012;
      spherical.phi = THREE.MathUtils.clamp(
        spherical.phi - deltaY * 0.012,
        0.08,
        Math.PI - 0.08,
      );
      offset.setFromSpherical(spherical);
      camera.position.copy(controls.target).add(offset);
      camera.lookAt(controls.target);
      controls.update();
    };

    const handleGizmoPointerDown = (event: PointerEvent) => {
      gizmoDragging = true;
      lastGizmoPointer = { x: event.clientX, y: event.clientY };
      gizmoRenderer?.domElement.setPointerCapture(event.pointerId);
      event.preventDefault();
    };
    const handleGizmoPointerMove = (event: PointerEvent) => {
      if (!gizmoDragging || !lastGizmoPointer) {
        return;
      }
      orbitCameraFromGizmoDrag(
        event.clientX - lastGizmoPointer.x,
        event.clientY - lastGizmoPointer.y,
      );
      lastGizmoPointer = { x: event.clientX, y: event.clientY };
      event.preventDefault();
    };
    const handleGizmoPointerUp = (event: PointerEvent) => {
      gizmoDragging = false;
      lastGizmoPointer = null;
      gizmoRenderer?.domElement.releasePointerCapture(event.pointerId);
    };
    gizmoRenderer?.domElement.addEventListener("pointerdown", handleGizmoPointerDown);
    gizmoRenderer?.domElement.addEventListener("pointermove", handleGizmoPointerMove);
    gizmoRenderer?.domElement.addEventListener("pointerup", handleGizmoPointerUp);
    gizmoRenderer?.domElement.addEventListener("pointercancel", handleGizmoPointerUp);

    fitViewRef.current = () => fitCameraToBounds("iso");
    setViewRef.current = (view: ViewerCameraPreset) => fitCameraToBounds(view);
    fitCameraToBounds("iso");

    if (stlUrl) {
      new STLLoader().load(stlUrl, (geometry) => {
        if (disposed) {
          geometry.dispose();
          return;
        }
        orientGeometryOnBuildPlate(geometry);
        geometry.computeBoundingSphere();
        const material = new THREE.MeshStandardMaterial({
          color: 0x6f8f3c,
          roughness: 0.58,
          metalness: 0.04,
        });
        const mesh = new THREE.Mesh(geometry, material);
        mesh.castShadow = true;
        mesh.receiveShadow = true;
        modelGroup = new THREE.Group();
        modelGroup.add(mesh);
        geometry.computeBoundingBox();
        const highlightSeverity = highestHighlightSeverity(highlights);
        const highlightBox = geometry.boundingBox?.clone();
        if (highlightSeverity && highlightBox) {
          highlightBox.expandByScalar(Math.max(1, (geometry.boundingSphere?.radius ?? 40) * 0.02));
          const helper = new THREE.Box3Helper(highlightBox, highlightColor(highlightSeverity));
          modelGroup.add(helper);
        }
        scene.add(modelGroup);
        modelBounds = new THREE.Box3().setFromObject(modelGroup);
        replaceBuildPlateGrid(scene, grid, modelBounds);
        fitCameraToBounds("iso");
      });
    }

    const animate = () => {
      frame = requestAnimationFrame(animate);
      controls.update();
      renderer.render(scene, camera);
      if (gizmoRenderer) {
        updateViewGizmoCamera(gizmoCamera, camera, controls.target);
        gizmoRenderer.render(gizmoScene, gizmoCamera);
      }
    };
    animate();

    return () => {
      disposed = true;
      cancelAnimationFrame(frame);
      resizeObserver.disconnect();
      controls.dispose();
      gizmoRenderer?.domElement.removeEventListener("pointerdown", handleGizmoPointerDown);
      gizmoRenderer?.domElement.removeEventListener("pointermove", handleGizmoPointerMove);
      gizmoRenderer?.domElement.removeEventListener("pointerup", handleGizmoPointerUp);
      gizmoRenderer?.domElement.removeEventListener("pointercancel", handleGizmoPointerUp);
      fitViewRef.current = () => undefined;
      setViewRef.current = () => undefined;
      scene.traverse((object) => {
        if (object instanceof THREE.Mesh || object instanceof THREE.LineSegments) {
          object.geometry.dispose();
          const material = object.material;
          if (Array.isArray(material)) {
            material.forEach((entry) => entry.dispose());
          } else {
            material.dispose();
          }
        }
      });
      disposeObject(gizmoScene);
      gizmoRenderer?.dispose();
      renderer.dispose();
      mount.replaceChildren();
      gizmoMount?.replaceChildren();
    };
  }, [highlights, stlUrl]);

  return (
    <div className="viewer-shell">
      <div className="viewer-toolbar" aria-label="Viewer controls">
        <button type="button" onClick={() => fitViewRef.current()}>
          Fit
        </button>
        <button type="button" onClick={() => setViewRef.current("front")}>
          Front
        </button>
        <button type="button" onClick={() => setViewRef.current("top")}>
          Top
        </button>
        <button type="button" onClick={() => setViewRef.current("iso")}>
          Iso
        </button>
      </div>
      <div className="viewer-help">Drag orbit · right drag pan · wheel zoom</div>
      <div
        aria-label="Orientation gizmo"
        className="viewer-gizmo"
        ref={gizmoRef}
        role="application"
      />
      <div className="viewer" ref={mountRef} />
    </div>
  );
}

type ViewerCameraPreset = "front" | "iso" | "top";

function orientGeometryOnBuildPlate(geometry: THREE.BufferGeometry) {
  geometry.computeBoundingBox();
  const bounds = geometry.boundingBox;
  if (!bounds) {
    return;
  }
  const center = bounds.getCenter(new THREE.Vector3());
  geometry.translate(-center.x, -center.y, -bounds.min.z);
}

function cameraPresetDirection(preset: ViewerCameraPreset) {
  if (preset === "front") {
    return new THREE.Vector3(0, -1, 0.28).normalize();
  }
  if (preset === "top") {
    return new THREE.Vector3(0, -0.001, 1).normalize();
  }
  return new THREE.Vector3(1.15, -1.35, 0.82).normalize();
}

function createBuildPlateGrid(size: number) {
  const divisions = Math.max(16, Math.round(size / 5));
  const grid = new THREE.GridHelper(size, divisions, 0x9aa49f, 0xd7deda);
  grid.rotation.x = Math.PI / 2;
  grid.position.z = 0;
  const material = grid.material;
  if (Array.isArray(material)) {
    material.forEach((entry) => {
      entry.transparent = true;
      entry.opacity = 0.58;
    });
  } else {
    material.transparent = true;
    material.opacity = 0.58;
  }
  return grid;
}

function createViewGizmoScene() {
  const scene = new THREE.Scene();
  scene.add(createGizmoAxis(new THREE.Vector3(1, 0, 0), 0xcf4f5d, "X"));
  scene.add(createGizmoAxis(new THREE.Vector3(0, 1, 0), 0x79a638, "Y"));
  scene.add(createGizmoAxis(new THREE.Vector3(0, 0, 1), 0x4d82d8, "Z"));
  const origin = new THREE.Mesh(
    new THREE.SphereGeometry(0.075, 16, 12),
    new THREE.MeshBasicMaterial({ color: 0x6c756f }),
  );
  scene.add(origin);
  return scene;
}

function createGizmoAxis(direction: THREE.Vector3, color: number, label: string) {
  const group = new THREE.Group();
  const material = new THREE.MeshBasicMaterial({ color });
  const lineGeometry = new THREE.CylinderGeometry(0.022, 0.022, 0.82, 12);
  const line = new THREE.Mesh(lineGeometry, material);
  const midpoint = direction.clone().multiplyScalar(0.41);
  line.position.copy(midpoint);
  line.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), direction);
  group.add(line);

  const head = new THREE.Mesh(new THREE.ConeGeometry(0.065, 0.18, 18), material);
  head.position.copy(direction.clone().multiplyScalar(0.88));
  head.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), direction);
  group.add(head);

  const labelSprite = createGizmoLabel(label, color);
  labelSprite.position.copy(direction.clone().multiplyScalar(1.14));
  group.add(labelSprite);
  return group;
}

function createGizmoLabel(label: string, color: number) {
  const canvas = document.createElement("canvas");
  canvas.width = 64;
  canvas.height = 64;
  const context = canvas.getContext("2d");
  if (context) {
    context.fillStyle = `#${color.toString(16).padStart(6, "0")}`;
    context.beginPath();
    context.arc(32, 32, 24, 0, Math.PI * 2);
    context.fill();
    context.fillStyle = "#ffffff";
    context.font = "bold 28px system-ui, sans-serif";
    context.textAlign = "center";
    context.textBaseline = "middle";
    context.fillText(label, 32, 33);
  }
  const texture = new THREE.CanvasTexture(canvas);
  const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: texture, transparent: true }));
  sprite.scale.set(0.36, 0.36, 0.36);
  return sprite;
}

function updateViewGizmoCamera(
  gizmoCamera: THREE.OrthographicCamera,
  mainCamera: THREE.PerspectiveCamera,
  target: THREE.Vector3,
) {
  const direction = mainCamera.position.clone().sub(target).normalize();
  gizmoCamera.position.copy(direction.multiplyScalar(4));
  gizmoCamera.up.copy(mainCamera.up);
  gizmoCamera.lookAt(0, 0, 0);
  gizmoCamera.updateProjectionMatrix();
}

function replaceBuildPlateGrid(scene: THREE.Scene, grid: THREE.GridHelper, bounds: THREE.Box3) {
  const size = bounds.getSize(new THREE.Vector3());
  const gridSize = Math.max(256, Math.ceil(Math.max(size.x, size.y) * 1.8 / 25) * 25);
  const nextGrid = createBuildPlateGrid(gridSize);
  scene.remove(grid);
  disposeObject(grid);
  scene.add(nextGrid);
}

function disposeObject(object: THREE.Object3D) {
  object.traverse((entry) => {
    if (entry instanceof THREE.Mesh || entry instanceof THREE.LineSegments) {
      entry.geometry.dispose();
      const material = entry.material;
      if (Array.isArray(material)) {
        material.forEach((item) => item.dispose());
      } else {
        material.dispose();
      }
    }
    if (entry instanceof THREE.Sprite) {
      const material = entry.material;
      material.map?.dispose();
      material.dispose();
    }
  });
}

function highestHighlightSeverity(highlights: PrintabilityHighlight[]): PrintabilitySeverity | null {
  if (highlights.length === 0) {
    return null;
  }
  return highlights.reduce<PrintabilitySeverity>(
    (highest, highlight) =>
      severityRank(highlight.severity) > severityRank(highest) ? highlight.severity : highest,
    highlights[0].severity,
  );
}

function highlightColor(severity: PrintabilitySeverity): number {
  return {
    Pass: 0x6f7a73,
    Notice: 0x7b6f2a,
    Warning: 0xb45d27,
    Critical: 0xb93232,
  }[severity];
}

async function request<T>(path: string, init: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...init.headers,
    },
  });
  if (!response.ok) {
    throw new Error(await responseErrorMessage(response));
  }
  return response.json() as Promise<T>;
}

async function requestEmpty(path: string, init: RequestInit): Promise<void> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...init.headers,
    },
  });
  if (!response.ok) {
    throw new Error(await responseErrorMessage(response));
  }
}

async function requestText(path: string, init: RequestInit): Promise<string> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: {},
    ...init,
  });
  if (!response.ok) {
    throw new Error(await response.text());
  }
  return response.text();
}

function normalizeConfigurationValue(
  parameter: ConfigurationParameter,
  value: string | number | boolean,
): string | number | boolean {
  if (parameter.type === "integer") {
    return Number.parseInt(String(value), 10);
  }
  if (parameter.type === "number") {
    return Number.parseFloat(String(value));
  }
  if (parameter.type === "boolean") {
    return Boolean(value);
  }
  return String(value);
}

function configurationDraftValues(values: Record<string, unknown>): Record<string, string | number | boolean> {
  return Object.fromEntries(
    Object.entries(values).filter((entry): entry is [string, string | number | boolean] => {
      const value = entry[1];
      return typeof value === "string" || typeof value === "number" || typeof value === "boolean";
    }),
  );
}

async function responseErrorMessage(response: Response): Promise<string> {
  if (response.status === 504) {
    return "Request timed out while waiting for the server. The model generation may still be running.";
  }

  const contentType = response.headers.get("content-type") ?? "";
  if (contentType.includes("application/json")) {
    const payload = (await response.json()) as { detail?: string };
    return payload.detail || `Request failed with ${response.status}`;
  }

  const detail = (await response.text()).trim();
  if (!detail || contentType.includes("text/html") || detail.startsWith("<!DOCTYPE") || detail.startsWith("<html")) {
    return `Request failed with ${response.status}`;
  }
  return detail;
}

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
