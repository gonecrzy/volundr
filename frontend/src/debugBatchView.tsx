import React, { useState } from "react";
import {
  buildDebugBatchStartPayload,
  debugBatchOutcomeLabel,
  debugBatchProjectCount,
  type DebugBatch,
  type DebugBatchComparison,
  type DebugBatchReport,
  type DebugBatchStartInput,
} from "./debugBatch";

export function debugBatchBannerText(batch: DebugBatch): string {
  return `Debug batch: ${batch.label}    ${debugBatchProjectCount(batch)} of ${batch.target_project_count} projects`;
}

export function debugBatchComparisonLabel(status: string | null | undefined): string {
  return {
    controlled: "Controlled comparison",
    uncontrolled: "Uncontrolled comparison",
    configuration_mismatch: "Uncontrolled comparison · configuration mismatch",
    identity_incomplete: "Uncontrolled comparison · identity incomplete",
    pending_identity: "Comparison pending identity",
    pending: "Comparison pending",
    not_applicable: "No comparison",
  }[status ?? "uncontrolled"] ?? "Uncontrolled comparison";
}

type Props = {
  enabled: boolean;
  activeBatch: DebugBatch | null;
  frozenBatches: DebugBatch[];
  report: DebugBatchReport | null;
  comparison: DebugBatchComparison | null;
  frontendBuildIdentity: string;
  onStart: (payload: DebugBatchStartInput & { frontendBuildIdentity: string }) => Promise<void>;
  onFinish: () => Promise<void>;
  onViewBatch: (batchId: string) => Promise<void>;
  onStartComparison: (baselineBatchId: string) => void;
};

type Dialog = "start" | "drawer" | "finish" | "result" | null;

export function DebugBatchView({
  enabled,
  activeBatch,
  frozenBatches,
  report,
  comparison,
  frontendBuildIdentity,
  onStart,
  onFinish,
  onViewBatch,
  onStartComparison,
}: Props) {
  const [dialog, setDialog] = useState<Dialog>(null);
  const [label, setLabel] = useState("");
  const [targetProjectCount, setTargetProjectCount] = useState("5");
  const [notes, setNotes] = useState("");
  const [baselineBatchId, setBaselineBatchId] = useState("");
  const [error, setError] = useState<string | null>(null);
  const displayedBatch = report?.batch ?? activeBatch;
  const isComplete = displayedBatch?.state === "frozen";
  const authoritativeComparisonStatus = comparison?.status ?? displayedBatch?.comparison_status;

  const resetStartForm = (baseline?: string) => {
    setLabel(baseline ? "" : "");
    setTargetProjectCount("5");
    setNotes("");
    setBaselineBatchId(baseline ?? "");
    setError(null);
  };

  const submitStart = async (event: React.FormEvent) => {
    event.preventDefault();
    setError(null);
    try {
      const input = { label, targetProjectCount, notes, baselineBatchId };
      buildDebugBatchStartPayload(input, frontendBuildIdentity);
      await onStart({ ...input, frontendBuildIdentity });
      setDialog("drawer");
      resetStartForm();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Batch could not be started");
    }
  };

  const openBatch = async () => {
    if (!activeBatch && !report?.batch) return;
    const batchId = activeBatch?.id ?? report?.batch.id;
    if (!batchId) return;
    setError(null);
    try {
      await onViewBatch(batchId);
      setDialog("drawer");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Batch could not be loaded");
    }
  };

  const finishBatch = async () => {
    setError(null);
    try {
      await onFinish();
      setDialog("result");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Batch could not be finished");
    }
  };

  const startComparison = () => {
    if (!report?.batch.id) return;
    onStartComparison(report.batch.id);
    setDialog("start");
    resetStartForm(report.batch.id);
  };

  if (!enabled) return null;

  return (
    <>
      {activeBatch ? (
        <div className="debug-batch-banner" role="status" aria-label="Active debug batch">
          <span>{debugBatchBannerText(activeBatch)}</span>
          <span className="debug-batch-banner-actions">
            <button className="text-action" type="button" onClick={() => void openBatch()}>View batch</button>
            <button className="text-action" type="button" onClick={() => setDialog("finish")}>Finish batch</button>
          </span>
        </div>
      ) : null}

      <button className="secondary compact debug-batch-action" type="button" onClick={() => { resetStartForm(); setDialog("start"); }}>
        Debug batch
      </button>

      {dialog === "start" ? (
        <div className="drawer-backdrop debug-batch-overlay" role="presentation" onClick={() => setDialog(null)}>
          <section className="workspace-dialog debug-batch-modal" role="dialog" aria-modal="true" aria-labelledby="debug-batch-start-title" onClick={(event) => event.stopPropagation()}>
            <h2 id="debug-batch-start-title">Start live debug batch</h2>
            <p className="inspector-note">This batch uses the configured live AI provider and CAD worker. Project conversations, provider responses, generated source, worker outcomes, and redacted frontend errors will be retained locally for review.</p>
            <form onSubmit={(event) => void submitStart(event)}>
              <label>Batch name<input aria-label="Batch name" required value={label} onChange={(event) => setLabel(event.target.value)} /></label>
              <label>Target projects<input aria-label="Target projects" type="number" min={1} max={20} step={1} value={targetProjectCount} onChange={(event) => setTargetProjectCount(event.target.value)} /></label>
              <label>Notes<textarea aria-label="Batch notes" rows={3} value={notes} onChange={(event) => setNotes(event.target.value)} /></label>
              <label>Baseline batch<select aria-label="Baseline batch" value={baselineBatchId} onChange={(event) => setBaselineBatchId(event.target.value)}><option value="">None</option>{frozenBatches.map((batch) => <option key={batch.id} value={batch.id}>{batch.label}</option>)}</select></label>
              {error ? <p className="error" role="alert">{error}</p> : null}
              <div className="actions"><button className="secondary" type="button" onClick={() => setDialog(null)}>Cancel</button><button className="primary" type="submit">Start batch</button></div>
            </form>
          </section>
        </div>
      ) : null}

      {dialog === "drawer" && displayedBatch ? (
        <div className="drawer-backdrop debug-batch-overlay" role="presentation" onClick={() => setDialog(null)}>
          <aside className="project-drawer debug-batch-drawer" aria-label="Debug batch" onClick={(event) => event.stopPropagation()}>
            <div className="drawer-heading"><div><h2>{displayedBatch.label}</h2><p>{displayedBatch.notes || "Live debug batch"}</p></div><button className="text-action" type="button" onClick={() => setDialog(null)}>Close</button></div>
            <dl className="review-facts compact"><dt>Provider / model</dt><dd>{displayedBatch.provider} / {displayedBatch.configured_default_model}</dd><dt>Git</dt><dd>{displayedBatch.git_head.slice(0, 8)}</dd><dt>Projects</dt><dd>{debugBatchProjectCount(displayedBatch)} of {displayedBatch.target_project_count}</dd>{displayedBatch.baseline_batch_id ? <><dt>Baseline</dt><dd>{displayedBatch.baseline_batch_id}</dd><dt>Comparison</dt><dd>{debugBatchComparisonLabel(authoritativeComparisonStatus)}</dd></> : null}</dl>
            <ol className="debug-batch-project-list">{displayedBatch.memberships.map((member) => <li key={member.project_id} className="debug-batch-project"><div><strong>{member.project_name || "Missing project"}</strong><small>{member.project_id.slice(0, 8)} · {debugBatchOutcomeLabel(member.final_outcome || member.workflow_phase)}</small></div><div className="debug-batch-project-meta"><span>Worker: {member.worker_reached ? "yes" : "no"}</span><span>Generation attempts: {member.generation_attempt_count} · provider calls: {member.provider_call_count}</span><span>Provider retries: {member.provider_retry_count} · repairs: {member.content_repair_count}</span><span>Operations: {member.user_operation_count}</span><span>Current: {member.current_working_revision_id ? "created" : "none"}</span></div></li>)}</ol>
            {isComplete ? <div className="actions"><a className="download compact-action" href={`${"/api"}/debug-batches/${displayedBatch.id}/evidence.zip`}>Download redacted report</a><button className="secondary compact" type="button" onClick={startComparison}>Start comparison batch</button></div> : <button className="secondary full-width" type="button" onClick={() => setDialog("finish")}>Finish batch</button>}
          </aside>
        </div>
      ) : null}

      {dialog === "finish" && activeBatch ? (
        <div className="drawer-backdrop debug-batch-overlay" role="presentation" onClick={() => setDialog(null)}>
          <section className="workspace-dialog debug-batch-modal" role="dialog" aria-modal="true" aria-labelledby="debug-batch-finish-title" onClick={(event) => event.stopPropagation()}>
            <h2 id="debug-batch-finish-title">Finish debug batch?</h2>
            <p>Finishing freezes batch membership and creates a redacted review bundle. Projects and their normal history remain available in Volundr.</p>
            {activeBatch.memberships.length ? <p>{activeBatch.memberships.length} project workflow{activeBatch.memberships.length === 1 ? " is" : "s are"} still tracked. Finish anyway and record incomplete work?</p> : null}
            {error ? <p className="error" role="alert">{error}</p> : null}
            <div className="actions"><button className="secondary" type="button" onClick={() => setDialog(null)}>Cancel</button><button className="primary" type="button" onClick={() => void finishBatch()}>Finish batch</button></div>
          </section>
        </div>
      ) : null}

      {dialog === "result" && report?.batch ? (
        <div className="drawer-backdrop debug-batch-overlay" role="presentation" onClick={() => setDialog(null)}>
          <section className="workspace-dialog debug-batch-result" role="dialog" aria-modal="true" aria-labelledby="debug-batch-result-title" onClick={(event) => event.stopPropagation()}>
            <h2 id="debug-batch-result-title">Debug batch complete</h2>
            <p><strong>{report.batch.label}</strong> · {report.batch.memberships.length} projects · {debugBatchComparisonLabel(authoritativeComparisonStatus)}</p>
            <p>Redaction: {report.batch.redaction_status}. Integrity: {report.batch.integrity_status}.</p>
            <div className="actions"><button className="secondary" type="button" onClick={() => void openBatch()}>View summary</button><button className="secondary" type="button" onClick={() => navigator.clipboard?.writeText(report.batch.report_path || "data/debug-sessions/")}>Copy batch folder path</button><button className="secondary" type="button" onClick={() => navigator.clipboard?.writeText(report.codex_review_instruction || "Review the local redacted debug batch evidence.")}>Copy Codex review instruction</button><a className="download compact-action" href={`${"/api"}/debug-batches/${report.batch.id}/evidence.zip`}>Download redacted report</a><button className="primary" type="button" onClick={startComparison}>Start comparison batch</button></div>
            {comparison?.status === "controlled" ? <p className="inspector-note">{"Matched Git " + String(comparison.identity_evidence.git_head ?? "unknown").slice(0, 12) + " · migration " + String(comparison.identity_evidence.migration_head ?? "unknown") + " · provider/model " + String(comparison.identity_evidence.provider ?? "unknown") + " / " + String(comparison.identity_evidence.configured_default_model ?? "unknown") + " · configuration " + String(comparison.identity_evidence.configuration_hash ?? "unknown").slice(0, 12) + " · builds matched."}</p> : comparison ? <p className="error">{"Mismatches: " + (Object.keys(comparison.mismatches).join(", ") || "identity unavailable") + "."}</p> : null}
          </section>
        </div>
      ) : null}
    </>
  );
}
