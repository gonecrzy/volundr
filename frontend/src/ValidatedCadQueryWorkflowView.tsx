import React, { useEffect, useMemo, useState } from "react";
import {
  createValidatedWorkflowApi,
  outputStateLabel,
  workflowStageLabel,
  workflowSummary,
  type ValidatedWorkflowArtifact,
  type ValidatedWorkflow,
} from "./validatedCadQueryWorkflow";

type ValidatedCadQueryWorkflowViewProps = {
  apiBase: string;
  enabled: boolean;
  projectId?: string;
  workflowId?: string;
  actorId?: string;
};

function routeIds(pathname: string): { projectId?: string; workflowId?: string } {
  const match = pathname.match(/^\/projects\/([^/]+)\/designs\/([^/]+)/);
  return match ? { projectId: decodeURIComponent(match[1]), workflowId: decodeURIComponent(match[2]) } : {};
}

export function ValidatedCadQueryWorkflowView({ apiBase, enabled, projectId, workflowId, actorId }: ValidatedCadQueryWorkflowViewProps) {
  const [name, setName] = useState("Validated design");
  const [intent, setIntent] = useState("");
  const [workflow, setWorkflow] = useState<ValidatedWorkflow | null>(null);
  const [clarification, setClarification] = useState("");
  const [revisionInstruction, setRevisionInstruction] = useState("");
  const [revisionDimension, setRevisionDimension] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [artifacts, setArtifacts] = useState<ValidatedWorkflowArtifact[]>([]);
  const [route, setRoute] = useState(() => routeIds(window.location.pathname));
  const api = useMemo(
    () => createValidatedWorkflowApi(apiBase, actorId ?? window.sessionStorage.getItem("volundr.actor_id") ?? ""),
    [actorId, apiBase],
  );

  const clarificationQuestion = useMemo(() => {
    const questions = workflow?.requirements?.clarification_questions;
    return Array.isArray(questions) && typeof questions[0] === "object" && questions[0] !== null
      ? String((questions[0] as { id?: string; question?: string }).question ?? "")
      : null;
  }, [workflow]);

  useEffect(() => {
    if (!enabled) return undefined;
    const handleNavigation = () => setRoute(routeIds(window.location.pathname));
    window.addEventListener("popstate", handleNavigation);
    return () => window.removeEventListener("popstate", handleNavigation);
  }, [enabled]);

  useEffect(() => {
    const currentWorkflowId = workflowId ?? route.workflowId;
    if (!enabled || !currentWorkflowId) return undefined;
    let cancelled = false;
    const load = async () => {
      try {
        const next = await api.getWorkflow(currentWorkflowId, projectId ?? route.projectId);
        const nextArtifacts = await api.listArtifacts(currentWorkflowId).catch(() => []);
        if (!cancelled) {
          setWorkflow(next);
          setArtifacts(nextArtifacts);
          setError(null);
        }
      } catch (reason) {
        if (!cancelled) setError(reason instanceof Error ? reason.message : "The design could not be loaded.");
      }
    };
    void load();
    const timer = window.setInterval(() => void load(), 3000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [api, enabled, projectId, route.projectId, route.workflowId, workflowId]);

  if (!enabled) {
    return null;
  }

  async function startDesign() {
    if (!intent.trim() || busy) return;
    setBusy(true);
    setError(null);
    try {
      const next = await api.startDesign(name, intent, `start-${name.trim()}-${intent.trim()}`);
      setWorkflow(next);
      setArtifacts([]);
      window.history.pushState({}, "", `/projects/${encodeURIComponent(next.project_id)}/designs/${encodeURIComponent(next.id)}`);
      setRoute({ projectId: next.project_id, workflowId: next.id });
    } catch (reason) {
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
      setWorkflow(await api.acceptCandidate(workflow.id, `accept-${workflow.id}`));
    } catch (reason) {
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
    try {
      setWorkflow(await api.submitClarification(workflow.id, question.id, clarification, `clarification-${workflow.id}-${question.id}`));
      setClarification("");
    } catch (reason) {
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
        }, `revision-${workflow.id}-${revisionInstruction.trim()}`);
      setWorkflow(next);
      setRevisionInstruction("");
      setRevisionDimension("");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "The revision could not be started.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="validated-workflow-panel" aria-label="Validated design workflow">
      <div className="validated-workflow-heading">
        <div>
          <p className="eyebrow">Design workflow</p>
          <h2>Build a validated CadQuery design</h2>
        </div>
        {workflow ? <span className="validated-workflow-stage">{workflowStageLabel(workflow.state)}</span> : null}
      </div>

      {!workflow ? (
        <div className="validated-workflow-start">
          <label>
            Design name
            <input value={name} onChange={(event) => setName(event.target.value)} />
          </label>
          <label>
            Describe the design
            <textarea value={intent} onChange={(event) => setIntent(event.target.value)} placeholder="Include dimensions, features, and placement details." />
          </label>
          <button type="button" disabled={busy || !intent.trim()} onClick={() => void startDesign()}>
            {busy ? "Starting…" : "Start design"}
          </button>
        </div>
      ) : (
        <>
          <p className="validated-workflow-summary">{workflowSummary(workflow)}</p>
          <div className="validated-workflow-sections">
            <section>
              <h3>Requirements</h3>
              <p>{String(workflow.requirements.purpose ?? workflow.requirements.object_type ?? "Requirements captured")}</p>
              {clarificationQuestion && workflow.state === "awaiting_clarification" ? (
                <div className="validated-workflow-clarification">
                  <label>
                    {clarificationQuestion}
                    <input value={clarification} onChange={(event) => setClarification(event.target.value)} />
                  </label>
                  <button type="button" disabled={busy || !clarification.trim()} onClick={() => void submitClarification()}>Submit detail</button>
                </div>
              ) : null}
            </section>
            <section>
              <h3>Plan</h3>
              <p>{String(workflow.plan.product_type ?? "Plan is being prepared")}</p>
              <span>{Array.isArray(workflow.plan.parameters) ? workflow.plan.parameters.length : 0} parameters · {Array.isArray(workflow.plan.printable_outputs) ? workflow.plan.printable_outputs.length : workflow.outputs.length} outputs</span>
            </section>
          </div>
          <div className="validated-output-grid">
            {workflow.outputs.map((output) => (
              <article className="validated-output-card" key={output.output_id}>
                <div>
                  <h3>{output.output_id}</h3>
                  <span>{outputStateLabel(output.state)}</span>
                </div>
                <p>{output.solid_count == null ? "Solid count pending" : `${output.solid_count} solid${output.solid_count === 1 ? "" : "s"}`} · topology {output.topology_status ?? "pending"}</p>
                <div className="validated-output-artifacts">
                  {artifacts.filter((artifact) => artifact.output_id === output.output_id && artifact.available && artifact.download_url).map((artifact) => (
                    <a key={artifact.artifact_id} href={`${apiBase}${artifact.download_url}`}>Download {artifact.kind.toUpperCase()}</a>
                  ))}
                </div>
                {output.safe_diagnostic ? <p className="validated-diagnostic">{output.safe_diagnostic}</p> : null}
              </article>
            ))}
          </div>
          {workflow.state === "candidate_ready" ? (
            <div className="validated-workflow-actions">
              <button type="button" disabled={busy} onClick={() => void acceptCandidate()}>Accept candidate</button>
            </div>
          ) : null}
          {workflow.package_available ? (
            <a className="download" href={`${apiBase}/validated-cadquery/workflows/${workflow.id}/artifacts/design-package/download`}>Download design package</a>
          ) : null}
          {workflow.revision_id && workflow.package_available ? (
            <div className="validated-workflow-revision">
              <h3>Make a bounded revision</h3>
              <label>
                What should change?
                <input value={revisionInstruction} onChange={(event) => setRevisionInstruction(event.target.value)} placeholder="Change one dimension and add a feature" />
              </label>
              <label>
                New dimension value (optional)
                <input value={revisionDimension} onChange={(event) => setRevisionDimension(event.target.value)} placeholder="96 mm" />
              </label>
              <button type="button" disabled={busy || !revisionInstruction.trim()} onClick={() => void startRevision()}>Start revision</button>
            </div>
          ) : null}
          {workflow.diagnostics.message ? <p className="validated-diagnostic">{String(workflow.diagnostics.message)}</p> : null}
        </>
      )}
      {error ? <p className="validated-diagnostic" role="alert">{error}</p> : null}
    </section>
  );
}
