import Editor from "@monaco-editor/react";
import React, { useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { STLLoader } from "three/examples/jsm/loaders/STLLoader.js";
import "./styles.css";

const API_BASE = "/api";

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

type SourceParameter = {
  name: string;
  value: string;
  type: "number" | "boolean";
  lineIndex: number;
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
  revision_number: number;
  source_type: string;
  status: string;
  is_accepted: boolean;
  user_instruction: string | null;
  ai_output_path: string | null;
  created_at: string;
  metadata: MeshMetadata | null;
  error_message: string | null;
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
  const [isInspectingPrintability, setIsInspectingPrintability] = useState(false);
  const [dismissedPrintabilityResults, setDismissedPrintabilityResults] = useState<Set<string>>(
    () => new Set(),
  );
  const [isProjectDrawerOpen, setIsProjectDrawerOpen] = useState(false);

  const activeMetadata = selectedRevision?.metadata ?? null;
  const stlUrl = selectedRevision?.is_accepted
    ? `${API_BASE}/revisions/${selectedRevision.id}/stl`
    : null;
  const sourceUrl = selectedRevision ? `${API_BASE}/revisions/${selectedRevision.id}/source` : null;
  const sourceParameters = useMemo(() => parseSourceParameters(source), [source]);
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
      setPrintabilityReport(null);
      setDismissedPrintabilityResults(new Set());
      setCompileLog(null);
      setAiOutput(null);
      setRevisionDiff(null);
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
      setPrintabilityReport(null);
      setDismissedPrintabilityResults(new Set());
      setCompileLog(null);
      setAiOutput(null);
      setRevisionDiff(null);
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
      setMessage("Enter OpenSCAD source before compiling");
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
          scad_source: source,
          user_instruction: instruction,
        }),
      });
      const nextRevisions = [...revisions, revision];
      setRevisions(nextRevisions);
      setSelectedRevision(revision);
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
    if (!canAskAi) {
      setMessage("Enter an AI prompt before asking AI");
      return;
    }
    setIsGenerating(true);
    setMessage(null);
    try {
      const currentProject = project ?? (await createDraftProject());

      if (!project || project.id !== currentProject.id) {
        setProject(currentProject);
      }

      const revision = await request<Revision>(`/projects/${currentProject.id}/generate`, {
        method: "POST",
        body: JSON.stringify({ user_instruction: generationPrompt }),
      });
      const nextRevisions = await request<Revision[]>(`/projects/${currentProject.id}/revisions`, {
        method: "GET",
      });
      setRevisions(nextRevisions);
      setSelectedRevision(revision);
      setPrintabilityReport(null);
      setDismissedPrintabilityResults(new Set());
      setProject({ ...currentProject, active_revision_id: revision.is_accepted ? revision.id : currentProject.active_revision_id });
      setMessage(revision.status === "succeeded" ? "Generated" : revision.error_message ?? "Generation failed");
      await selectRevision(revision);
      await loadProjectMessages(currentProject.id);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Generation failed");
    } finally {
      setIsGenerating(false);
    }
  }

  async function selectRevision(revision: Revision) {
    setSelectedRevision(revision);
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
      setPrintabilityReport(null);
      setDismissedPrintabilityResults(new Set());
      setCompileLog(null);
      setAiOutput(null);
      setRevisionDiff(null);
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
    setCompileLog(null);
    setAiOutput(null);
    setRevisionDiff(null);
    setPrintabilityReport(null);
    setDismissedPrintabilityResults(new Set());
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
                ? `R${selectedRevision.revision_number} - ${selectedRevision.status}`
                : "Draft workspace"}
            </p>
          </div>
        </div>
        <div className="topbar-actions">
          {sourceUrl ? (
            <a className="download compact-action" href={sourceUrl}>
              SCAD
            </a>
          ) : null}
          {stlUrl ? (
            <a className="download compact-action" href={stlUrl}>
              STL
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
              {message ? <p className="message">{message}</p> : null}
            </div>
            <div className="prompt-row">
              <input
                aria-label="Ask AI prompt"
                placeholder="Describe the model change for AI"
                value={generationPrompt}
                onChange={(event) => setGenerationPrompt(event.target.value)}
              />
              <button className="secondary" disabled={isGenerating || !canAskAi} onClick={() => void generateSource()}>
                {isGenerating ? "Asking AI" : "Ask AI"}
              </button>
            </div>
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
                  <span>{revision.source_type.replace("_", " ")} - {revision.status}</span>
                </button>
              ))}
            </div>
          </section>

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
          <ParameterControls
            parameters={sourceParameters}
            onChange={(parameter, value) => setSource(updateSourceParameter(source, parameter, value))}
          />
          {selectedRevision?.is_accepted && selectedRevision.id !== project?.active_revision_id ? (
            <div className="actions">
              <button className="download" onClick={() => void restoreSelectedRevision()}>
                Restore revision
              </button>
            </div>
          ) : null}
          <section className="source-panel" aria-label="OpenSCAD source">
            <div className="section-heading">
              <h2>Source</h2>
            </div>
            <Editor
              defaultLanguage="scad"
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

function ParameterControls({
  parameters,
  onChange,
}: {
  parameters: SourceParameter[];
  onChange: (parameter: SourceParameter, value: string) => void;
}) {
  if (parameters.length === 0) {
    return null;
  }
  return (
    <section className="parameters" aria-label="User parameters">
      <h2>Parameters</h2>
      <div className="parameter-list">
        {parameters.map((parameter) => (
          <label className="parameter-control" key={`${parameter.lineIndex}-${parameter.name}`}>
            {parameter.name}
            {parameter.type === "boolean" ? (
              <input
                checked={parameter.value === "true"}
                type="checkbox"
                onChange={(event) => onChange(parameter, event.target.checked ? "true" : "false")}
              />
            ) : (
              <input
                step="any"
                type="number"
                value={parameter.value}
                onChange={(event) => {
                  if (isValidParameterValue(parameter, event.target.value)) {
                    onChange(parameter, event.target.value);
                  }
                }}
              />
            )}
          </label>
        ))}
      </div>
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

function parseSourceParameters(source: string): SourceParameter[] {
  const lines = source.split("\n");
  const sectionStart = lines.findIndex((line) => /USER PARAMETERS/i.test(line));
  if (sectionStart === -1) {
    return [];
  }

  const parameters: SourceParameter[] = [];
  for (let index = sectionStart + 1; index < lines.length; index += 1) {
    const line = lines[index];
    if (/^\s*\/\/\s*=+\s*$/.test(line)) {
      continue;
    }
    if (/^\s*\/\/\s*(?:=+\s*)?[A-Za-z][A-Za-z0-9 _-]*(?:\s*=+)?\s*$/.test(line)) {
      break;
    }
    const match = line.match(/^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(-?\d+(?:\.\d+)?|true|false)\s*;/);
    if (!match) {
      continue;
    }
    const value = match[2];
    parameters.push({
      name: match[1],
      value,
      type: value === "true" || value === "false" ? "boolean" : "number",
      lineIndex: index,
    });
  }
  return parameters;
}

function updateSourceParameter(source: string, parameter: SourceParameter, value: string): string {
  const lines = source.split("\n");
  const line = lines[parameter.lineIndex];
  if (!line) {
    return source;
  }
  lines[parameter.lineIndex] = line.replace(
    /^(\s*[A-Za-z_][A-Za-z0-9_]*\s*=\s*)(-?\d+(?:\.\d+)?|true|false)(\s*;)/,
    `$1${value}$3`,
  );
  return lines.join("\n");
}

function isValidParameterValue(parameter: SourceParameter, value: string): boolean {
  if (parameter.type === "boolean") {
    return value === "true" || value === "false";
  }
  return /^-?\d+(?:\.\d*)?$/.test(value);
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
    const contentType = response.headers.get("content-type") ?? "";
    if (contentType.includes("application/json")) {
      const payload = (await response.json()) as { detail?: string };
      throw new Error(payload.detail || `Request failed with ${response.status}`);
    }
    const detail = await response.text();
    throw new Error(detail || `Request failed with ${response.status}`);
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
    const contentType = response.headers.get("content-type") ?? "";
    if (contentType.includes("application/json")) {
      const payload = (await response.json()) as { detail?: string };
      throw new Error(payload.detail || `Request failed with ${response.status}`);
    }
    const detail = await response.text();
    throw new Error(detail || `Request failed with ${response.status}`);
  }
}

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
