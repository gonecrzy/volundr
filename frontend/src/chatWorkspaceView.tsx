import React, { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import {
  canExportRevision,
  classifyProjectMessage,
  layoutModeForWidth,
  type ChatDisplayKind,
  type SubmissionErrorPresentation,
} from "./chatWorkspace";

export type ChatWorkspaceMessage = {
  id: string;
  project_id?: string;
  revision_id: string | null;
  role: string;
  content: string;
  created_at: string;
};

export type ChatWorkspaceProject = {
  id: string;
  name: string;
  status: string;
  active_revision_id: string | null;
  updated_at?: string;
};

export type ChatWorkspaceRevision = {
  id: string;
  revision_number: number;
  parent_revision_id?: string | null;
  status: string;
  review_state: string | null;
  is_accepted: boolean;
  created_at: string;
  user_instruction: string | null;
  error_message: string | null;
  stl_path: string | null;
  expected_output_count: number | null;
  successful_output_count: number | null;
  validation_summary: {
    blocking_count: number;
    advisory_count: number;
    dismissed_count?: number;
  };
  functional_status?: string;
};

export type ChatWorkspaceOutput = {
  id: string;
  label: string;
  execution_state: string;
  stl_path: string | null;
  step_path?: string | null;
  warning_count?: number;
};

export type ChatWorkspacePendingMessage = {
  id: string;
  content: string;
  state: "pending" | "failed";
};

type ChatWorkspaceProps = {
  project: ChatWorkspaceProject | null;
  projects: ChatWorkspaceProject[];
  messages: ChatWorkspaceMessage[];
  revisions: ChatWorkspaceRevision[];
  selectedRevision: ChatWorkspaceRevision | null;
  currentWorkingRevisionId: string | null;
  activeRequirements: Array<Record<string, unknown>>;
  designPlan: { plan?: Record<string, unknown> } | null;
  outputs: ChatWorkspaceOutput[];
  activeWorkflow: Record<string, unknown> | null;
  selectedOutputId: string | null;
  saveStatus: "idle" | "saving" | "saved" | "failed" | "offline";
  generationPrompt: string;
  chatPlaceholder: string;
  chatButtonLabel: string;
  isChatActionPending: boolean;
  canAskAi: boolean;
  pendingMessage: ChatWorkspacePendingMessage | null;
  submissionError: SubmissionErrorPresentation | null;
  viewer: ReactNode;
  hasModel: boolean;
  technicalDetails: ReactNode;
  onPromptChange: (value: string) => void;
  onPromptKeyDown: (event: React.KeyboardEvent<HTMLTextAreaElement>) => void;
  onSubmitPrompt: () => void;
  onRetrySubmission: () => void;
  onClearSubmissionError: () => void;
  onSelectProject: (project: ChatWorkspaceProject) => void;
  onStartProject: () => void;
  onSelectRevision: (revision: ChatWorkspaceRevision) => void;
  onViewRevision: (revisionId: string) => void;
  onOpenExport: () => void;
  onExport: () => void;
  onRename: (name: string) => Promise<void>;
  onArchive: () => void;
  onDelete: () => void;
  onDownloadOutput: (output: ChatWorkspaceOutput, format: "stl" | "step") => void;
};

export function ChatWorkspace({
  project,
  projects,
  messages,
  revisions,
  selectedRevision,
  currentWorkingRevisionId,
  activeRequirements,
  designPlan,
  outputs,
  activeWorkflow,
  selectedOutputId,
  saveStatus,
  generationPrompt,
  chatPlaceholder,
  chatButtonLabel,
  isChatActionPending,
  canAskAi,
  pendingMessage,
  submissionError,
  viewer,
  hasModel,
  technicalDetails,
  onPromptChange,
  onPromptKeyDown,
  onSubmitPrompt,
  onRetrySubmission,
  onClearSubmissionError,
  onSelectProject,
  onStartProject,
  onSelectRevision,
  onViewRevision,
  onOpenExport,
  onExport,
  onRename,
  onArchive,
  onDelete,
  onDownloadOutput,
}: ChatWorkspaceProps) {
  const [layoutMode, setLayoutMode] = useState(() => layoutModeForWidth(window.innerWidth));
  const [activeTab, setActiveTab] = useState<"conversation" | "model" | "details">("conversation");
  const [projectMenuOpen, setProjectMenuOpen] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [exportOpen, setExportOpen] = useState(false);
  const [overflowOpen, setOverflowOpen] = useState(false);
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [renameOpen, setRenameOpen] = useState(false);
  const [renameValue, setRenameValue] = useState(project?.name ?? "");
  const [renameSaving, setRenameSaving] = useState(false);

  useEffect(() => {
    const handleResize = () => setLayoutMode(layoutModeForWidth(window.innerWidth));
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, []);

  useEffect(() => {
    setRenameValue(project?.name ?? "");
  }, [project?.id, project?.name]);

  useEffect(() => {
    if (!projectMenuOpen && !historyOpen && !exportOpen && !detailsOpen && !renameOpen && !overflowOpen) {
      return undefined;
    }
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") {
        return;
      }
      setProjectMenuOpen(false);
      setHistoryOpen(false);
      setExportOpen(false);
      setDetailsOpen(false);
      setRenameOpen(false);
      setOverflowOpen(false);
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [detailsOpen, exportOpen, historyOpen, overflowOpen, projectMenuOpen, renameOpen]);

  const currentRevision = revisions.find((revision) => revision.id === currentWorkingRevisionId) ?? null;
  const selectedIsCurrent = selectedRevision?.id === currentWorkingRevisionId;
  const exportable = canExportRevision(selectedRevision ?? currentRevision);
  const saveLabel = saveStatus === "saving" ? "Saving…" : saveStatus === "failed" ? "Save failed" : saveStatus === "offline" ? "Disconnected" : project ? "Saved" : "";
  const visibleMessages = useMemo(
    () => messages.filter((message) => classifyProjectMessage(message) !== "hidden"),
    [messages],
  );

  async function saveRename() {
    const nextName = renameValue.trim();
    if (!nextName || renameSaving) {
      return;
    }
    setRenameSaving(true);
    try {
      await onRename(nextName);
      setRenameOpen(false);
    } catch {
      // The top-bar save state remains "Save failed" and the dialog keeps the
      // user's attempted name available for another try.
    } finally {
      setRenameSaving(false);
    }
  }

  return (
    <main className="chat-workspace" data-layout={layoutMode}>
      <header className="chat-topbar">
        <div className="chat-topbar-left">
          <button className="topbar-link" type="button" onClick={() => setProjectMenuOpen(true)}>
            Projects
          </button>
          <span className="breadcrumb-separator" aria-hidden="true">/</span>
          <button
            className="project-title-button"
            type="button"
            onClick={() => {
              if (project) {
                setRenameValue(project.name);
                setRenameOpen(true);
              }
            }}
            aria-label={project ? `Rename ${project.name}` : "Project title"}
          >
            {project?.name || "Untitled project"}
          </button>
        </div>
        <div className="chat-topbar-actions">
          <span className={`save-state save-state-${saveStatus}`} aria-label="Save status">
            {saveLabel}
          </span>
          {layoutMode === "drawer" ? (
            <button className="topbar-button" type="button" onClick={() => setDetailsOpen(true)}>Details</button>
          ) : null}
          <button className="topbar-button" type="button" onClick={() => setHistoryOpen(true)}>History</button>
          <button
            className="topbar-button topbar-export"
            type="button"
            disabled={!exportable}
            title={exportable ? "Export the selected successful revision" : "Create a successful working version before exporting"}
            onClick={() => setExportOpen(true)}
          >
            Export
          </button>
          <button
            aria-expanded={overflowOpen}
            aria-label="Project menu"
            className="topbar-button overflow-button"
            type="button"
            onClick={() => setOverflowOpen((current) => !current)}
          >
            ⋯
          </button>
          {overflowOpen ? (
            <div className="topbar-menu" role="menu">
              <button type="button" role="menuitem" onClick={() => { setOverflowOpen(false); setRenameValue(project?.name ?? ""); setRenameOpen(true); }}>Rename</button>
              <button type="button" role="menuitem" disabled={!project} onClick={() => { setOverflowOpen(false); onArchive(); }}>Archive</button>
              <button type="button" role="menuitem" disabled={!project} onClick={() => { setOverflowOpen(false); onDelete(); }}>Delete</button>
            </div>
          ) : null}
        </div>
      </header>

      <section className="chat-project-workspace">
        {layoutMode === "tabs" ? (
          <nav className="mobile-tabs" aria-label="Project workspace tabs">
            {(["conversation", "model", "details"] as const).map((tab) => (
              <button key={tab} className={activeTab === tab ? "active" : ""} type="button" onClick={() => setActiveTab(tab)}>
                {tab === "conversation" ? "Conversation" : tab === "model" ? "Model" : "Details"}
              </button>
            ))}
          </nav>
        ) : null}

        <section className={`workspace-column conversation-column ${layoutMode === "tabs" && activeTab !== "conversation" ? "mobile-hidden" : ""}`} aria-label="Conversation">
          <ConversationPanel
            messages={visibleMessages}
            pendingMessage={pendingMessage}
            submissionError={submissionError}
            activeWorkflow={activeWorkflow}
            isChatActionPending={isChatActionPending}
            generationPrompt={generationPrompt}
            placeholder={project ? chatPlaceholder : "Describe the part you need"}
            buttonLabel={chatButtonLabel}
            canAskAi={canAskAi}
            onPromptChange={onPromptChange}
            onPromptKeyDown={onPromptKeyDown}
            onSubmit={onSubmitPrompt}
            onRetry={onRetrySubmission}
            onClearError={onClearSubmissionError}
            onViewRevision={onViewRevision}
            onOpenExport={() => setExportOpen(true)}
          />
        </section>

        <section className={`workspace-column viewer-column ${layoutMode === "tabs" && activeTab !== "model" ? "mobile-hidden" : ""}`} aria-label="3D Viewer">
          <ViewerPanel viewer={viewer} hasModel={hasModel} selectedRevision={selectedRevision} currentRevision={currentRevision} selectedIsCurrent={selectedIsCurrent} onReturnToCurrent={() => { if (currentRevision) onSelectRevision(currentRevision); }} />
        </section>

        <aside className={`workspace-column inspector-column ${layoutMode === "tabs" && activeTab !== "details" ? "mobile-hidden" : ""} ${layoutMode === "drawer" && !detailsOpen ? "drawer-closed" : ""}`} aria-label="Design summary">
          <InspectorPanel
            project={project}
            currentRevision={currentRevision}
            selectedRevision={selectedRevision}
            revisions={revisions}
            activeRequirements={activeRequirements}
            designPlan={designPlan}
            outputs={outputs}
            selectedOutputId={selectedOutputId}
            onSelectRevision={onSelectRevision}
            onOpenExport={() => setExportOpen(true)}
            onDownloadOutput={onDownloadOutput}
            technicalDetails={technicalDetails}
          />
        </aside>
      </section>

      {projectMenuOpen ? (
        <div className="workspace-overlay" onClick={() => setProjectMenuOpen(false)}>
          <aside className="workspace-drawer project-list-drawer" role="dialog" aria-modal="true" aria-label="Projects" onClick={(event) => event.stopPropagation()}>
            <div className="drawer-heading">
              <div><h2>Projects</h2><p>{projects.length} active</p></div>
              <button className="text-action" type="button" onClick={() => setProjectMenuOpen(false)}>Close</button>
            </div>
            <button className="secondary full-width" type="button" onClick={onStartProject}>New project</button>
            <div className="project-list">
              {projects.length === 0 ? <p className="empty">No projects yet.</p> : null}
              {projects.map((entry) => (
                <button className={entry.id === project?.id ? "project-item selected" : "project-item"} key={entry.id} type="button" onClick={() => { setProjectMenuOpen(false); onSelectProject(entry); }}>
                  <span>{entry.name}</span>
                  <small>{entry.active_revision_id ? "Current working version" : "No working version"}</small>
                </button>
              ))}
            </div>
          </aside>
        </div>
      ) : null}

      {layoutMode === "drawer" && detailsOpen ? (
        <div className="workspace-overlay" onClick={() => setDetailsOpen(false)}>
          <aside className="workspace-drawer inspector-drawer" role="dialog" aria-modal="true" aria-label="Design details" onClick={(event) => event.stopPropagation()}>
            <div className="drawer-heading"><h2>Details</h2><button className="text-action" type="button" onClick={() => setDetailsOpen(false)}>Close</button></div>
            <InspectorPanel
              project={project}
              currentRevision={currentRevision}
              selectedRevision={selectedRevision}
              revisions={revisions}
              activeRequirements={activeRequirements}
              designPlan={designPlan}
              outputs={outputs}
              selectedOutputId={selectedOutputId}
              onSelectRevision={onSelectRevision}
              onOpenExport={() => setExportOpen(true)}
              onDownloadOutput={onDownloadOutput}
              technicalDetails={technicalDetails}
            />
          </aside>
        </div>
      ) : null}

      {historyOpen ? (
        <div className="workspace-overlay" onClick={() => setHistoryOpen(false)}>
          <aside className="workspace-drawer history-drawer" role="dialog" aria-modal="true" aria-label="Version history" onClick={(event) => event.stopPropagation()}>
            <div className="drawer-heading"><div><h2>History</h2><p>Previous versions remain recoverable.</p></div><button className="text-action" type="button" onClick={() => setHistoryOpen(false)}>Close</button></div>
            <VersionHistory revisions={revisions} currentWorkingRevisionId={currentWorkingRevisionId} onSelectRevision={(revision) => { setHistoryOpen(false); onSelectRevision(revision); }} />
          </aside>
        </div>
      ) : null}

      {exportOpen ? (
        <div className="workspace-overlay" onClick={() => setExportOpen(false)}>
          <aside className="workspace-drawer export-drawer" role="dialog" aria-modal="true" aria-label="Export" onClick={(event) => event.stopPropagation()}>
            <div className="drawer-heading"><div><h2>Export</h2><p>{selectedRevision && selectedIsCurrent ? `Exporting Version ${selectedRevision.revision_number} — Current working version` : selectedRevision ? `Exporting Version ${selectedRevision.revision_number} — Previous version` : "No successful revision selected"}</p></div><button className="text-action" type="button" onClick={() => setExportOpen(false)}>Close</button></div>
            <ExportPanel revision={selectedRevision ?? currentRevision} outputs={outputs} selectedOutputId={selectedOutputId} onExport={() => { setExportOpen(false); onExport(); }} onDownloadOutput={onDownloadOutput} />
          </aside>
        </div>
      ) : null}

      {renameOpen ? (
        <div className="workspace-overlay" onClick={() => setRenameOpen(false)}>
          <div className="workspace-dialog" role="dialog" aria-modal="true" aria-labelledby="rename-title" onClick={(event) => event.stopPropagation()}>
            <h2 id="rename-title">Rename project</h2>
            <input autoFocus value={renameValue} onChange={(event) => setRenameValue(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") void saveRename(); if (event.key === "Escape") setRenameOpen(false); }} />
            <div className="actions"><button className="secondary" type="button" onClick={() => setRenameOpen(false)}>Cancel</button><button className="primary" type="button" disabled={!renameValue.trim() || renameSaving} onClick={() => void saveRename()}>{renameSaving ? "Saving…" : "Save"}</button></div>
          </div>
        </div>
      ) : null}
    </main>
  );
}

function ConversationPanel({
  messages,
  pendingMessage,
  submissionError,
  activeWorkflow,
  isChatActionPending,
  generationPrompt,
  placeholder,
  buttonLabel,
  canAskAi,
  onPromptChange,
  onPromptKeyDown,
  onSubmit,
  onRetry,
  onClearError,
  onViewRevision,
  onOpenExport,
}: {
  messages: ChatWorkspaceMessage[];
  pendingMessage: ChatWorkspacePendingMessage | null;
  submissionError: SubmissionErrorPresentation | null;
  activeWorkflow: Record<string, unknown> | null;
  isChatActionPending: boolean;
  generationPrompt: string;
  placeholder: string;
  buttonLabel: string;
  canAskAi: boolean;
  onPromptChange: (value: string) => void;
  onPromptKeyDown: (event: React.KeyboardEvent<HTMLTextAreaElement>) => void;
  onSubmit: () => void;
  onRetry: () => void;
  onClearError: () => void;
  onViewRevision: (revisionId: string) => void;
  onOpenExport: () => void;
}) {
  const listRef = useRef<HTMLDivElement | null>(null);
  const nearBottomRef = useRef(true);
  const [newMessages, setNewMessages] = useState(false);
  const allMessages = pendingMessage
    ? [...messages, { id: pendingMessage.id, revision_id: null, role: pendingMessage.state === "failed" ? "assistant_error" : "user", content: pendingMessage.content, created_at: new Date().toISOString() }]
    : messages;

  useEffect(() => {
    const list = listRef.current;
    if (!list) return;
    if (nearBottomRef.current) {
      list.scrollTop = list.scrollHeight;
      setNewMessages(false);
    } else if (allMessages.length > 0) {
      setNewMessages(true);
    }
  }, [allMessages.length]);

  function onScroll() {
    const list = listRef.current;
    if (!list) return;
    nearBottomRef.current = list.scrollHeight - list.scrollTop - list.clientHeight < 72;
    if (nearBottomRef.current) setNewMessages(false);
  }

  function jumpToLatest() {
    const list = listRef.current;
    if (!list) return;
    list.scrollTop = list.scrollHeight;
    nearBottomRef.current = true;
    setNewMessages(false);
  }

  return (
    <section className="conversation-panel">
      <header className="conversation-header"><h2>Conversation</h2>{activeWorkflow ? <span className="connection-indicator" aria-label="Connected">●</span> : null}</header>
      <div className="message-list-shell">
        <div className="message-list" ref={listRef} onScroll={onScroll} aria-live="polite">
          {allMessages.length === 0 ? <EmptyConversation /> : null}
          {allMessages.map((message) => (
            <ChatMessage key={message.id} message={message} onViewRevision={onViewRevision} onOpenExport={onOpenExport} />
          ))}
          {isChatActionPending && !pendingMessage ? <ProgressMessage /> : null}
        </div>
        {newMessages ? <button className="new-messages-button" type="button" onClick={jumpToLatest}>New messages</button> : null}
      </div>
      {submissionError ? (
        <div className="submission-error" role="alert">
          <strong>{submissionError.title}</strong>
          <p>{submissionError.body}</p>
          <div className="error-actions"><button className="text-action" type="button" onClick={onRetry}>{submissionError.action}</button><button className="text-action" type="button" onClick={onClearError}>Dismiss</button></div>
        </div>
      ) : null}
      <form className="chat-composer" onSubmit={(event) => { event.preventDefault(); onSubmit(); }}>
        <textarea aria-label="AI chat message" placeholder={placeholder} rows={2} value={generationPrompt} onKeyDown={onPromptKeyDown} onChange={(event) => onPromptChange(event.target.value)} />
        <div className="composer-footer"><span>Enter to send · Shift+Enter for a new line</span><button className="primary" type="submit" disabled={isChatActionPending || !canAskAi}>{buttonLabel}</button></div>
      </form>
    </section>
  );
}

function EmptyConversation() {
  return (
    <div className="empty-conversation">
      <h3>Describe the part you need</h3>
      <p>Include what it must fit, hold, mount to, or avoid. Add the measurements you already know. Volundr will ask only for details needed to begin.</p>
      <div className="conversation-examples"><span>Create a wall-mounted holder for…</span><span>Design an enclosure for…</span><span>Make a replacement bracket that…</span></div>
    </div>
  );
}

function ChatMessage({ message, onViewRevision, onOpenExport }: { message: ChatWorkspaceMessage; onViewRevision: (revisionId: string) => void; onOpenExport: () => void }) {
  const kind = classifyProjectMessage(message);
  if (kind === "hidden") return null;
  const assistant = kind !== "user";
  const label = assistant ? "Volundr" : "You";
  return (
    <article className={`chat-message chat-message-${kind}`} data-message-kind={kind}>
      <div className="message-meta"><span>{label}</span><time dateTime={message.created_at}>{formatMessageTime(message.created_at)}</time></div>
      <p>{message.content}</p>
      {kind === "success" && message.revision_id ? <div className="message-actions"><button className="text-action" type="button" onClick={() => onViewRevision(message.revision_id!)}>View version</button><button className="text-action" type="button" onClick={onOpenExport}>Export</button></div> : null}
      {kind === "blocked" ? <p className="message-subtle">Your Current working version is unchanged.</p> : null}
    </article>
  );
}

function ProgressMessage() {
  return <article className="chat-message chat-message-progress" aria-live="polite"><div className="message-meta"><span>Volundr</span><span>Working</span></div><p>Creating the model…</p><div className="progress-steps"><span className="complete">Understanding</span><span className="active">Planning</span><span>Creating</span><span>Checking</span></div></article>;
}

function ViewerPanel({ viewer, hasModel, selectedRevision, currentRevision, selectedIsCurrent, onReturnToCurrent }: { viewer: ReactNode; hasModel: boolean; selectedRevision: ChatWorkspaceRevision | null; currentRevision: ChatWorkspaceRevision | null; selectedIsCurrent: boolean; onReturnToCurrent: () => void }) {
  return (
    <section className="viewer-panel chat-viewer-panel">
      {viewer}
      {!hasModel ? <div className="viewer-empty-state"><h2>Your model will appear here</h2><p>Describe the part in the conversation. Volundr will create a model after it has enough information.</p></div> : null}
      {selectedRevision && !selectedIsCurrent ? <div className="version-banner">Viewing Version {selectedRevision.revision_number} — Current working version is Version {currentRevision?.revision_number ?? "not created"}<button type="button" onClick={onReturnToCurrent}>Return to current</button></div> : null}
      {selectedRevision?.review_state === "blocked" ? <div className="version-banner blocked-banner">Viewing blocked attempt — not the Current working version</div> : null}
      <div className="viewer-statusbar"><span>{selectedRevision ? `Version ${selectedRevision.revision_number}` : "No version selected"}</span><span>Selected part · mm</span></div>
    </section>
  );
}

function InspectorPanel({ project, currentRevision, selectedRevision, revisions, activeRequirements, designPlan, outputs, selectedOutputId, onSelectRevision, onOpenExport, onDownloadOutput, technicalDetails }: { project: ChatWorkspaceProject | null; currentRevision: ChatWorkspaceRevision | null; selectedRevision: ChatWorkspaceRevision | null; revisions: ChatWorkspaceRevision[]; activeRequirements: Array<Record<string, unknown>>; designPlan: { plan?: Record<string, unknown> } | null; outputs: ChatWorkspaceOutput[]; selectedOutputId: string | null; onSelectRevision: (revision: ChatWorkspaceRevision) => void; onOpenExport: () => void; onDownloadOutput: (output: ChatWorkspaceOutput, format: "stl" | "step") => void; technicalDetails: ReactNode }) {
  return (
    <div className="inspector-scroll">
      <section className="inspector-section current-version-section"><SectionTitle title="Current working version" />{currentRevision ? <><strong>Version {currentRevision.revision_number}</strong><p>{formatDate(currentRevision.created_at)} · {currentRevision.expected_output_count ?? outputs.length} printable part{(currentRevision.expected_output_count ?? outputs.length) === 1 ? "" : "s"}</p><span className="readiness-pill">{currentRevision.review_state === "ready_with_warnings" ? "Ready with warnings" : "Ready"}</span></> : <p>No working version yet.</p>}{selectedRevision && currentRevision && selectedRevision.id !== currentRevision.id ? <p className="inspector-note">Viewing Version {selectedRevision.revision_number}</p> : null}</section>
      <RequirementsSection requirements={activeRequirements} />
      <ProposalsSection plan={designPlan} />
      <ChecksSection revision={selectedRevision ?? currentRevision} />
      <PrintablePartsSection revision={selectedRevision ?? currentRevision} outputs={outputs} selectedOutputId={selectedOutputId} onOpenExport={onOpenExport} onDownloadOutput={onDownloadOutput} />
      <section className="inspector-section"><SectionTitle title="Version history" /><VersionHistory revisions={revisions} currentWorkingRevisionId={project?.active_revision_id ?? null} onSelectRevision={onSelectRevision} /></section>
      <section className="inspector-section technical-section"><details><summary>Technical details</summary><div className="technical-details-content">{technicalDetails}</div></details></section>
    </div>
  );
}

function SectionTitle({ title }: { title: string }) { return <h2 className="inspector-section-title">{title}</h2>; }

function RequirementsSection({ requirements }: { requirements: Array<Record<string, unknown>> }) {
  const [expanded, setExpanded] = useState(false);
  const lines = requirements.map((requirement) => String(requirement.description ?? requirement.label ?? requirement.requirement_id ?? "Active requirement"));
  return <section className="inspector-section"><SectionTitle title="Active requirements" />{lines.length ? <><ul className="plain-list">{lines.slice(0, expanded ? lines.length : 6).map((line, index) => <li key={`${line}-${index}`}>{line}</li>)}</ul>{lines.length > 6 ? <button className="text-action" type="button" onClick={() => setExpanded((current) => !current)}>{expanded ? "Show less" : "Show all"}</button> : null}</> : <p>No requirements yet.</p>}</section>;
}

function ProposalsSection({ plan }: { plan: { plan?: Record<string, unknown> } | null }) {
  const payload = plan?.plan ?? {};
  const parameters = Array.isArray(payload.parameters) ? payload.parameters : [];
  const proposals = parameters.filter((parameter) => typeof parameter === "object" && parameter !== null && (parameter as Record<string, unknown>).source !== "user").slice(0, 6).map((parameter) => { const item = parameter as Record<string, unknown>; return `${String(item.label ?? item.id ?? "Choice")}: ${String(item.value ?? "proposed")}${item.unit ? ` ${String(item.unit)}` : ""}`; });
  const features = Array.isArray(payload.features) ? payload.features.slice(0, 4).map((feature) => typeof feature === "object" && feature !== null ? String((feature as Record<string, unknown>).description ?? (feature as Record<string, unknown>).type ?? "Design feature") : String(feature)) : [];
  const lines = [...proposals, ...features];
  return <section className="inspector-section"><SectionTitle title="Proposed choices" /><p className="inspector-note">These were selected by Volundr and can be changed in chat.</p>{lines.length ? <ul className="plain-list">{lines.map((line, index) => <li key={`${line}-${index}`}>{line}</li>)}</ul> : <p>No proposals yet.</p>}</section>;
}

function ChecksSection({ revision }: { revision: ChatWorkspaceRevision | null }) {
  if (!revision) return <section className="inspector-section"><SectionTitle title="Checks and warnings" /><p>Checks will appear after a version is created.</p></section>;
  const blocked = revision.review_state === "blocked" || revision.validation_summary.blocking_count > 0;
  return <section className="inspector-section"><SectionTitle title="Checks and warnings" /><ul className="plain-list checks-list"><li className={blocked ? "check-blocked" : "check-passed"}>{blocked ? revision.error_message ?? "Design checks need attention" : "Solid-body and artifact checks passed"}</li>{revision.validation_summary.advisory_count > 0 ? <li className="check-warning">{revision.validation_summary.advisory_count} warning{revision.validation_summary.advisory_count === 1 ? "" : "s"} remain{revision.validation_summary.advisory_count === 1 ? "s" : ""}</li> : null}{revision.functional_status && revision.functional_status !== "functionally_verified" ? <li className="check-warning">Functional behavior requires a test print or review</li> : revision.functional_status ? <li className="check-passed">Functional checks reported</li> : null}</ul></section>;
}

function PrintablePartsSection({ revision, outputs, selectedOutputId, onOpenExport, onDownloadOutput }: { revision: ChatWorkspaceRevision | null; outputs: ChatWorkspaceOutput[]; selectedOutputId: string | null; onOpenExport: () => void; onDownloadOutput: (output: ChatWorkspaceOutput, format: "stl" | "step") => void }) {
  if (!revision || !canExportRevision(revision) || outputs.length === 0) return <section className="inspector-section"><SectionTitle title="Printable parts" /><p>Printable parts will appear after a valid working version is created.</p></section>;
  return <section className="inspector-section"><SectionTitle title="Printable parts" /><div className="printable-parts-list">{outputs.map((output) => <article className={output.id === selectedOutputId ? "printable-part selected" : "printable-part"} key={output.id}><div><strong>{output.label}</strong><small>{output.execution_state === "ready_with_warnings" ? "Ready with warnings" : "Ready"}</small></div><div className="part-actions">{output.stl_path ? <button className="text-action" type="button" onClick={() => onDownloadOutput(output, "stl")}>Download STL</button> : null}{output.step_path ? <button className="text-action" type="button" onClick={() => onDownloadOutput(output, "step")}>Download STEP</button> : null}</div></article>)}</div><button className="secondary full-width" type="button" onClick={onOpenExport}>Download all parts</button></section>;
}

function VersionHistory({ revisions, currentWorkingRevisionId, onSelectRevision }: { revisions: ChatWorkspaceRevision[]; currentWorkingRevisionId: string | null; onSelectRevision: (revision: ChatWorkspaceRevision) => void }) {
  if (revisions.length === 0) return <p className="empty">No previous versions.</p>;
  return <div className="version-history">{[...revisions].sort((a, b) => a.revision_number - b.revision_number).map((revision) => { const current = revision.id === currentWorkingRevisionId; const blocked = revision.review_state === "blocked"; return <button className="version-history-entry" key={revision.id} type="button" onClick={() => onSelectRevision(revision)}><span>Version {revision.revision_number}</span><small>{current ? "Current" : blocked ? "Blocked" : revision.is_accepted ? "Previous" : "Creating"} · {formatDate(revision.created_at)}</small></button>; })}</div>;
}

function ExportPanel({ revision, outputs, selectedOutputId, onExport, onDownloadOutput }: { revision: ChatWorkspaceRevision | null; outputs: ChatWorkspaceOutput[]; selectedOutputId: string | null; onExport: () => void; onDownloadOutput: (output: ChatWorkspaceOutput, format: "stl" | "step") => void }) {
  if (!revision || !canExportRevision(revision)) return <p className="empty">Choose a successful version before exporting.</p>;
  return <div className="export-panel"><h3>Printable parts</h3>{outputs.map((output) => <div className={output.id === selectedOutputId ? "export-part selected" : "export-part"} key={output.id}><span>{output.label}</span><div>{output.stl_path ? <button className="text-action" type="button" onClick={() => onDownloadOutput(output, "stl")}>STL</button> : null}{output.step_path ? <button className="text-action" type="button" onClick={() => onDownloadOutput(output, "step")}>STEP</button> : null}</div></div>)}<p className="inspector-note">Project package includes the selected revision, requirements, source, and printable artifacts.</p><button className="primary full-width" type="button" onClick={onExport}>Create project package</button></div>;
}

function formatMessageTime(value: string): string { const date = new Date(value); return Number.isNaN(date.valueOf()) ? "" : date.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }); }
function formatDate(value: string): string { const date = new Date(value); return Number.isNaN(date.valueOf()) ? "" : date.toLocaleDateString([], { month: "short", day: "numeric", year: "numeric" }); }
