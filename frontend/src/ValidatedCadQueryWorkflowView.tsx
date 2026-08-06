import React, { useEffect, useMemo, useRef, useState } from "react";
import {
  createValidatedRequestIdentityStore,
  createValidatedWorkflowApi,
  isDefinitiveValidatedRequestError,
  outputStateLabel,
  workflowStageLabel,
  workflowSummary,
  type ValidatedWorkflowArtifact,
  type ValidatedWorkflow,
} from "./validatedCadQueryWorkflow";
import { createWorkflowPoller } from "./validatedCadQueryPolling";

type ValidatedCadQueryWorkflowViewProps = {
  apiBase: string;
  enabled: boolean;
  projectId?: string;
  workflowId?: string;
  embedded?: boolean;
  showStartForm?: boolean;
  onWorkflowChange?: (workflow: ValidatedWorkflow | null) => void;
  onArtifactsChange?: (artifacts: ValidatedWorkflowArtifact[]) => void;
};

export function validatedRouteIds(pathname: string): { projectId?: string; workflowId?: string } {
  const match = pathname.match(/^\/projects\/([^/]+)\/designs\/([^/]+)/);
  return match ? { projectId: decodeURIComponent(match[1]), workflowId: decodeURIComponent(match[2]) } : {};
}

function apiDownloadUrl(apiBase: string, downloadUrl: string): string {
  return downloadUrl.startsWith("/") ? downloadUrl : `${apiBase}${downloadUrl}`;
}

function readableRequirement(value: unknown): string {
  return String(value ?? "requirement")
    .replace(/[_-]+/g, " ")
    .replace(/\b\w/g, (character) => character.toUpperCase());
}

function readableFailure(value: unknown): string {
  const labels: Record<string, string> = {
    provider_response_contract_failure: "Provider response format",
    python_syntax_error: "Source syntax",
    source_contract_violation: "Source contract",
    python_name_error: "Source name resolution",
    python_type_error: "Source type error",
    cadquery_selector_error: "CadQuery selection",
    worker_timeout: "Worker timeout",
    solid_count_mismatch: "Solid count",
    semantic_requirement_failed: "Design requirement mismatch",
    semantic_requirement_unverifiable: "Design requirement not proven",
    repair_budget_exhausted: "Repair budget exhausted",
  };
  return labels[String(value)] ?? "Bounded repair step";
}

export function ValidatedCadQueryWorkflowView({
  apiBase,
  enabled,
  projectId,
  workflowId,
  embedded = false,
  showStartForm = true,
  onWorkflowChange,
  onArtifactsChange,
}: ValidatedCadQueryWorkflowViewProps) {
  const [name, setName] = useState("Validated design");
  const [intent, setIntent] = useState("");
  const [workflow, setWorkflow] = useState<ValidatedWorkflow | null>(null);
  const [clarification, setClarification] = useState("");
  const [revisionInstruction, setRevisionInstruction] = useState("");
  const [revisionDimension, setRevisionDimension] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [artifacts, setArtifacts] = useState<ValidatedWorkflowArtifact[]>([]);
  const [route, setRoute] = useState(() => validatedRouteIds(window.location.pathname));
  const pollerRef = useRef<ReturnType<typeof createWorkflowPoller> | null>(null);
  const recoveringStartRef = useRef(false);
  const api = useMemo(() => createValidatedWorkflowApi(apiBase), [apiBase]);
  const identities = useMemo(() => createValidatedRequestIdentityStore(), []);
  const currentProjectId = projectId ?? route.projectId;
  const currentWorkflowId = workflowId ?? route.workflowId;

  const executableProvenance = workflow?.provenance ?? {};
  const executableContract = executableProvenance.executable_design_contract as Record<string, unknown> | undefined;
  const semanticVerification = (
    workflow?.verification.semantic_verification ?? executableProvenance.semantic_verification
  ) as Record<string, unknown> | undefined;
  const repairHistory = Array.isArray(executableProvenance.repair_history)
    ? executableProvenance.repair_history.filter((item): item is Record<string, unknown> => Boolean(item && typeof item === "object"))
    : [];

  const clarificationQuestion = useMemo(() => {
    const questions = workflow?.requirements?.clarification_questions;
    return Array.isArray(questions) && typeof questions[0] === "object" && questions[0] !== null
      ? String((questions[0] as { id?: string; question?: string }).question ?? "")
      : null;
  }, [workflow]);

  function publishWorkflow(next: ValidatedWorkflow | null) {
    setWorkflow(next);
    onWorkflowChange?.(next);
  }

  function publishArtifacts(next: ValidatedWorkflowArtifact[]) {
    setArtifacts(next);
    onArtifactsChange?.(next);
  }

  useEffect(() => {
    if (!enabled) return undefined;
    const handleNavigation = () => setRoute(validatedRouteIds(window.location.pathname));
    window.addEventListener("popstate", handleNavigation);
    return () => window.removeEventListener("popstate", handleNavigation);
  }, [enabled]);

  useEffect(() => {
    if (!enabled || !currentWorkflowId) {
      pollerRef.current?.stop();
      pollerRef.current = null;
      return undefined;
    }
    const poller = createWorkflowPoller({
      workflowId: currentWorkflowId,
      fetchWorkflow: (id) => api.getWorkflow(id, currentProjectId),
      onWorkflow: (next) => {
        publishWorkflow(next);
        setError(null);
        void api.listArtifacts(next.id, currentProjectId).then(publishArtifacts).catch(() => undefined);
      },
      onError: (reason) => setError(reason instanceof Error ? reason.message : "The design could not be loaded."),
    });
    pollerRef.current = poller;
    poller.start();
    const onVisibilityChange = () => poller.setDocumentHidden(document.hidden);
    document.addEventListener("visibilitychange", onVisibilityChange);
    return () => {
      document.removeEventListener("visibilitychange", onVisibilityChange);
      poller.stop();
      if (pollerRef.current === poller) pollerRef.current = null;
    };
  }, [api, currentProjectId, currentWorkflowId, enabled]);

  useEffect(() => {
    if (!enabled || showStartForm || currentWorkflowId || recoveringStartRef.current) return;
    const pending = identities.getPending<{ name?: string; intent?: string }>("start_design", "new-design");
    if (!pending?.intent) return;
    recoveringStartRef.current = true;
    setBusy(true);
    void api.startDesign(pending.name ?? "Validated design", pending.intent, identities.getOrCreate("start_design", "new-design"))
      .then((next) => {
        identities.clear("start_design", "new-design");
        publishWorkflow(next);
        publishArtifacts([]);
        window.history.pushState({}, "", `/projects/${encodeURIComponent(next.project_id)}/designs/${encodeURIComponent(next.id)}`);
        setRoute({ projectId: next.project_id, workflowId: next.id });
      })
      .catch((reason) => {
        if (isDefinitiveValidatedRequestError(reason)) identities.clear("start_design", "new-design");
        setError(reason instanceof Error ? reason.message : "The design could not be recovered.");
      })
      .finally(() => {
        recoveringStartRef.current = false;
        setBusy(false);
      });
  }, [api, currentWorkflowId, enabled, identities, showStartForm]);

  async function startDesign() {
    if (!intent.trim() || busy) return;
    setBusy(true);
    setError(null);
    const scope = "new-design";
    identities.setPending("start_design", scope, { name, intent });
    try {
      const next = await api.startDesign(name, intent, identities.getOrCreate("start_design", scope));
      identities.clear("start_design", scope);
      publishWorkflow(next);
      publishArtifacts([]);
      window.history.pushState({}, "", `/projects/${encodeURIComponent(next.project_id)}/designs/${encodeURIComponent(next.id)}`);
      setRoute({ projectId: next.project_id, workflowId: next.id });
    } catch (reason) {
      if (isDefinitiveValidatedRequestError(reason)) identities.clear("start_design", scope);
      setError(reason instanceof Error ? reason.message : "The design could not be started.");
    } finally {
      setBusy(false);
    }
  }

  async function acceptCandidate() {
    if (!workflow || busy) return;
    setBusy(true);
    setError(null);
    try {
      let next = await api.acceptCandidate(workflow.id, identities.getOrCreate("acceptance", workflow.id));
      identities.clear("acceptance", workflow.id);
      if (!next.package_available) {
        next = await api.createPackage(workflow.id, identities.getOrCreate("package", workflow.id));
        identities.clear("package", workflow.id);
      }
      publishWorkflow(next);
      publishArtifacts(await api.listArtifacts(next.id, currentProjectId));
      pollerRef.current?.refresh();
    } catch (reason) {
      if (isDefinitiveValidatedRequestError(reason)) {
        identities.clear("acceptance", workflow.id);
        identities.clear("package", workflow.id);
      }
      setError(reason instanceof Error ? reason.message : "The candidate could not be accepted.");
    } finally {
      setBusy(false);
    }
  }

  async function submitClarification() {
    if (!workflow || !clarification.trim() || busy) return;
    const questions = workflow.requirements?.clarification_questions;
    const question = Array.isArray(questions) && typeof questions[0] === "object" && questions[0] !== null
      ? questions[0] as { id?: string }
      : null;
    if (!question?.id) return;
    setBusy(true);
    setError(null);
    const scope = `${workflow.id}:${question.id}`;
    try {
      const next = await api.submitClarification(workflow.id, question.id, clarification, identities.getOrCreate("clarification", scope));
      identities.clear("clarification", scope);
      publishWorkflow(next);
      setClarification("");
      pollerRef.current?.refresh();
    } catch (reason) {
      if (isDefinitiveValidatedRequestError(reason)) identities.clear("clarification", scope);
      setError(reason instanceof Error ? reason.message : "The clarification could not be submitted.");
    } finally {
      setBusy(false);
    }
  }

  async function startRevision() {
    if (!workflow || !revisionInstruction.trim() || busy) return;
    setBusy(true);
    setError(null);
    try {
      const next = await api.startRevision(workflow.id, {
        instruction: revisionInstruction,
        dimension_changes: revisionDimension.trim() ? { primary_dimension: revisionDimension.trim() } : {},
        added_features: [],
        protected_facts: workflow.outputs.map((output) => `${output.output_id} identity`),
      }, identities.getOrCreate("revision", workflow.id));
      identities.clear("revision", workflow.id);
      publishWorkflow(next);
      publishArtifacts(await api.listArtifacts(next.id, currentProjectId));
      window.history.pushState({}, "", `/projects/${encodeURIComponent(next.project_id)}/designs/${encodeURIComponent(next.id)}`);
      setRoute({ projectId: next.project_id, workflowId: next.id });
      setRevisionInstruction("");
      setRevisionDimension("");
      pollerRef.current?.refresh();
    } catch (reason) {
      if (isDefinitiveValidatedRequestError(reason)) identities.clear("revision", workflow.id);
      setError(reason instanceof Error ? reason.message : "The revision could not be started.");
    } finally {
      setBusy(false);
    }
  }

  if (!enabled) return null;

  const packageArtifact = artifacts.find((artifact) => artifact.available && artifact.download_url && /package/i.test(artifact.kind));
  const panelClass = embedded ? "validated-workflow-panel validated-workflow-panel-embedded" : "validated-workflow-panel";
  return (
    <section className={panelClass} aria-label="Validated design workflow">
      <div className="validated-workflow-heading">
        <div>
          <p className="eyebrow">Design workflow</p>
          <h2>{embedded ? "Validated design" : "Build a validated CadQuery design"}</h2>
        </div>
        {workflow ? <span className="validated-workflow-stage">{workflowStageLabel(workflow.state)}</span> : null}
        {currentWorkflowId ? <button className="text-action" type="button" onClick={() => pollerRef.current?.refresh()}>Refresh</button> : null}
      </div>

      {!workflow ? (
        showStartForm ? (
          <div className="validated-workflow-start">
            <label>Design name<input value={name} onChange={(event) => setName(event.target.value)} /></label>
            <label>Describe the design<textarea value={intent} onChange={(event) => setIntent(event.target.value)} placeholder="Include dimensions, features, and placement details." /></label>
            <button type="button" disabled={busy || !intent.trim()} onClick={() => void startDesign()}>{busy ? "Starting…" : "Start design"}</button>
          </div>
        ) : <p className="validated-workflow-empty">Describe the design in the conversation to begin the validated workflow.</p>
      ) : (
        <>
          <p className="validated-workflow-summary">{workflowSummary(workflow)}</p>
          {executableProvenance.source_generation_mode === "complete_source" || executableProvenance.source_generation_mode === "complete_source_revision" ? (
            <section className="validated-executable-summary" aria-label="Executable CadQuery experiment">
              <h3>Executable CadQuery experiment</h3>
              <p>Gemini supplied a complete CadQuery source file. Volundr executed that source and checked the final geometry.</p>
              <dl>
                <div><dt>Transport</dt><dd>Gemini API</dd></div>
                <div><dt>Automatic provider operations</dt><dd>{String(executableProvenance.automatic_provider_operation_count ?? 0)} / {String(executableProvenance.automatic_provider_operation_budget ?? 7)}</dd></div>
                <div><dt>Current repair level</dt><dd>{repairHistory.length ? readableFailure(repairHistory[repairHistory.length - 1].failure_class) : "Initial generation"}</dd></div>
                <div><dt>Protected facts</dt><dd>{Array.isArray(executableContract?.protected_facts) ? executableContract.protected_facts.length : 0} recorded</dd></div>
              </dl>
              {semanticVerification ? (
                <div className="validated-executable-checks">
                  <strong>Final-geometry checklist</strong>
                  {(["passed", "failed", "unverifiable"] as const).map((status) => {
                    const values = Array.isArray(semanticVerification[status]) ? semanticVerification[status] : [];
                    return values.length ? <p key={status}><span>{status === "passed" ? "Passed" : status === "failed" ? "Needs repair" : "Not proven"}</span> {values.map(readableRequirement).join(", ")}</p> : null;
                  })}
                </div>
              ) : null}
              {executableProvenance.source_generation_mode === "complete_source_revision" && workflow.verification.output_identity_preserved === true ? <p className="validated-executable-preservation">Output identity preserved for this revision.</p> : null}
              {repairHistory.length ? <div className="validated-executable-history"><strong>Repair history</strong>{repairHistory.map((attempt, index) => <p key={`${String(attempt.operation_id ?? index)}`}>Attempt {String(attempt.attempt_number ?? index + 1)} · {readableFailure(attempt.failure_class)}</p>)}</div> : null}
            </section>
          ) : null}
          <div className="validated-workflow-sections">
            <section><h3>Requirements</h3><p>{String(workflow.requirements.purpose ?? workflow.requirements.object_type ?? "Requirements captured")}</p>
              {clarificationQuestion && workflow.state === "awaiting_clarification" ? <div className="validated-workflow-clarification"><label>{clarificationQuestion}<input value={clarification} onChange={(event) => setClarification(event.target.value)} /></label><button type="button" disabled={busy || !clarification.trim()} onClick={() => void submitClarification()}>Submit detail</button></div> : null}
            </section>
            <section><h3>Plan</h3><p>{String(workflow.plan.product_type ?? "Plan is being prepared")}</p><span>{Array.isArray(workflow.plan.parameters) ? workflow.plan.parameters.length : 0} parameters · {Array.isArray(workflow.plan.printable_outputs) ? workflow.plan.printable_outputs.length : workflow.outputs.length} outputs</span></section>
          </div>
          <div className="validated-output-grid" aria-label="Validated outputs">
            {workflow.outputs.map((output) => <article className="validated-output-card" key={output.output_id}><div><h3>{output.output_id}</h3><span>{outputStateLabel(output.state)}</span></div><p>{output.solid_count == null ? "Solid count pending" : `${output.solid_count} solid${output.solid_count === 1 ? "" : "s"}`} · topology {output.topology_status ?? "pending"}</p><div className="validated-output-artifacts">{artifacts.filter((artifact) => artifact.output_id === output.output_id && artifact.available && artifact.download_url).map((artifact) => <a key={artifact.artifact_id} href={apiDownloadUrl(apiBase, artifact.download_url!)}>Download {artifact.kind.toUpperCase()}</a>)}</div>{output.safe_diagnostic ? <p className="validated-diagnostic">{output.safe_diagnostic}</p> : null}</article>)}
          </div>
          {workflow.state === "candidate_ready" || workflow.state === "revision_ready" ? <div className="validated-workflow-actions"><button type="button" disabled={busy} onClick={() => void acceptCandidate()}>Accept candidate</button></div> : null}
          {packageArtifact?.download_url ? <a className="download" href={apiDownloadUrl(apiBase, packageArtifact.download_url)}>Download design package</a> : workflow.package_available ? <span className="validated-workflow-package">Design package is being prepared.</span> : workflow.state === "partially_completed" ? <span className="validated-workflow-package">Incomplete package unavailable until every required output passes.</span> : null}
          {workflow.revision_id && workflow.package_available ? <div className="validated-workflow-revision"><h3>Make a bounded revision</h3><label>What should change?<input value={revisionInstruction} onChange={(event) => setRevisionInstruction(event.target.value)} placeholder="Change one dimension and add a feature" /></label><label>New dimension value (optional)<input value={revisionDimension} onChange={(event) => setRevisionDimension(event.target.value)} placeholder="96 mm" /></label><button type="button" disabled={busy || !revisionInstruction.trim()} onClick={() => void startRevision()}>Start revision</button></div> : null}
          {workflow.diagnostics.message ? <p className="validated-diagnostic">{String(workflow.diagnostics.message)}</p> : null}
        </>
      )}
      {error ? <p className="validated-diagnostic" role="alert">{error}</p> : null}
    </section>
  );
}

export function ValidatedWorkflowOutputArea({
  apiBase,
  workflow,
  artifacts,
}: {
  apiBase: string;
  workflow: ValidatedWorkflow | null;
  artifacts: ValidatedWorkflowArtifact[];
}) {
  if (!workflow) return null;
  return (
    <section className="inspector-section validated-output-area" aria-label="Validated printable outputs">
      <h2 className="inspector-section-title">Validated printable parts</h2>
      {workflow.outputs.map((output) => (
        <article className="validated-inspector-output" key={output.output_id}>
          <div><strong>{output.output_id}</strong><span>{outputStateLabel(output.state)}</span></div>
          <p>{output.topology_status ?? "Topology pending"} · {output.semantic_verification ?? "Verification pending"}</p>
          {artifacts.filter((artifact) => artifact.output_id === output.output_id && artifact.available && artifact.download_url).map((artifact) => (
            <a key={artifact.artifact_id} href={apiDownloadUrl(apiBase, artifact.download_url!)}>{artifact.kind.toUpperCase()}</a>
          ))}
        </article>
      ))}
    </section>
  );
}
