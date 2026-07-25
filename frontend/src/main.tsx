import Editor from "@monaco-editor/react";
import React, { useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import * as THREE from "three";
import { STLLoader } from "three/examples/jsm/loaders/STLLoader.js";
import "./styles.css";

const API_BASE = "/api";
const DEFAULT_SOURCE = `// ===== QUALITY =====
$fn = 48;

// ===== USER PARAMETERS =====
part_width = 80;
part_depth = 35;
part_height = 8;
hole_diameter = 5;
hole_spacing = 55;

// ===== MODULES =====
module main_body() {
  difference() {
    cube([part_width, part_depth, part_height], center = true);
    translate([-hole_spacing / 2, 0, 0])
      cylinder(h = part_height + 2, d = hole_diameter, center = true);
    translate([hole_spacing / 2, 0, 0])
      cylinder(h = part_height + 2, d = hole_diameter, center = true);
  }
}

module main_model() {
  translate([0, 0, part_height / 2])
    main_body();
}

main_model();
`;

type Project = {
  id: string;
  name: string;
  original_intent: string;
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
  const [projectName, setProjectName] = useState("Mounting bracket");
  const [intent, setIntent] = useState("A flat mounting bracket with two bolt holes.");
  const [instruction, setInstruction] = useState("Initial manual model.");
  const [generationPrompt, setGenerationPrompt] = useState(
    "Create a flat mounting bracket with two bolt holes and named parameters.",
  );
  const [source, setSource] = useState(DEFAULT_SOURCE);
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
  const [printabilityReport, setPrintabilityReport] = useState<PrintabilityReport | null>(null);
  const [isInspectingPrintability, setIsInspectingPrintability] = useState(false);
  const [dismissedPrintabilityResults, setDismissedPrintabilityResults] = useState<Set<string>>(
    () => new Set(),
  );

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

  useEffect(() => {
    void refreshProjects();
  }, []);

  async function refreshProjects() {
    try {
      setProjects(await request<Project[]>("/projects", { method: "GET" }));
    } catch {
      setProjects([]);
    }
  }

  async function saveProject() {
    if (!project) {
      return;
    }
    setIsSavingProject(true);
    setMessage(null);
    try {
      const updatedProject = await request<Project>(`/projects/${project.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          name: projectName,
          original_intent: intent,
        }),
      });
      setProject(updatedProject);
      setProjects((current) =>
        current.map((entry) => (entry.id === updatedProject.id ? updatedProject : entry)),
      );
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
      setRevisions([]);
      setProjectMessages([]);
      setSelectedRevision(null);
      setPrintabilityReport(null);
      setDismissedPrintabilityResults(new Set());
      setCompileLog(null);
      setAiOutput(null);
      setRevisionDiff(null);
      setMessage("Project archived");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Project archive failed");
    } finally {
      setIsSavingProject(false);
    }
  }

  async function compileSource() {
    setIsCompiling(true);
    setMessage(null);
    try {
      const currentProject =
        project ??
        (await request<Project>("/projects", {
          method: "POST",
          body: JSON.stringify({
            name: projectName,
            original_intent: intent,
          }),
        }));

      if (!project) {
        setProject(currentProject);
        setProjects((current) => [currentProject, ...current]);
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
    setIsGenerating(true);
    setMessage(null);
    try {
      const currentProject =
        project ??
        (await request<Project>("/projects", {
          method: "POST",
          body: JSON.stringify({
            name: projectName,
            original_intent: intent,
          }),
        }));

      if (!project) {
        setProject(currentProject);
        setProjects((current) => [currentProject, ...current]);
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

  async function selectProject(nextProject: Project) {
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

  function dismissPrintabilityResult(ruleId: string) {
    setDismissedPrintabilityResults((current) => {
      const next = new Set(current);
      next.add(ruleId);
      return next;
    });
  }

  return (
    <main className="workspace">
      <header className="topbar">
        <div>
          <h1>Volundr</h1>
          <p>{project ? project.name : "Manual OpenSCAD workspace"}</p>
        </div>
        <button className="primary" disabled={isCompiling} onClick={compileSource}>
          {isCompiling ? "Compiling" : "Compile"}
        </button>
      </header>

      <section className="project-strip" aria-label="Project">
        <label>
          Name
          <input value={projectName} onChange={(event) => setProjectName(event.target.value)} />
        </label>
        <label>
          Intent
          <input value={intent} onChange={(event) => setIntent(event.target.value)} />
        </label>
        <label>
          Revision
          <input value={instruction} onChange={(event) => setInstruction(event.target.value)} />
        </label>
        <div className="project-actions" aria-label="Project actions">
          <button className="secondary" disabled={!project || isSavingProject} onClick={() => void saveProject()}>
            {isSavingProject ? "Saving" : "Save"}
          </button>
          <button className="secondary" disabled={!project || isSavingProject} onClick={() => void archiveProject()}>
            Archive
          </button>
        </div>
      </section>

      <section className="generation-strip" aria-label="AI generation">
        <label>
          Generate
          <input value={generationPrompt} onChange={(event) => setGenerationPrompt(event.target.value)} />
        </label>
        <button className="secondary" disabled={isGenerating} onClick={() => void generateSource()}>
          {isGenerating ? "Generating" : "Generate"}
        </button>
      </section>

      <section className="main-grid">
        <aside className="sidebar" aria-label="Revisions">
          <h2>Projects</h2>
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
          <h2>Messages</h2>
          <MessageList messages={projectMessages} />
          {message ? <p className="message">{message}</p> : null}
        </aside>

        <section className="viewer-panel" aria-label="STL preview">
          <StlViewer stlUrl={stlUrl} highlights={printabilityHighlights} />
        </section>

        <section className="metadata-panel" aria-label="Metadata">
          <h2>Metadata</h2>
          <Metadata metadata={activeMetadata} />
          <PrintabilityInspector
            canInspect={Boolean(selectedRevision?.is_accepted)}
            dismissedRuleIds={dismissedPrintabilityResults}
            isInspecting={isInspectingPrintability}
            profile={printabilityProfile}
            report={printabilityReport}
            onDismiss={dismissPrintabilityResult}
            onInspect={() => void inspectSelectedRevisionPrintability()}
            onProfileChange={updatePrintabilityProfile}
          />
          <ParameterControls
            parameters={sourceParameters}
            onChange={(parameter, value) => setSource(updateSourceParameter(source, parameter, value))}
          />
          <div className="actions">
            {sourceUrl ? (
              <a className="download" href={sourceUrl}>
                Download SCAD
              </a>
            ) : null}
            {stlUrl ? (
              <a className="download" href={stlUrl}>
                Download STL
              </a>
            ) : null}
            {selectedRevision?.is_accepted && selectedRevision.id !== project?.active_revision_id ? (
              <button className="download" onClick={() => void restoreSelectedRevision()}>
                Restore
              </button>
            ) : null}
          </div>
          <Diagnostics compileLog={compileLog} aiOutput={aiOutput} revisionDiff={revisionDiff} />
        </section>

        <section className="editor-panel" aria-label="OpenSCAD source">
          <Editor
            defaultLanguage="scad"
            height="100%"
            options={{
              minimap: { enabled: false },
              fontSize: 14,
              wordWrap: "on",
              scrollBeyondLastLine: false,
            }}
            theme="vs-dark"
            value={source}
            onChange={(value) => setSource(value ?? "")}
          />
        </section>
      </section>
    </main>
  );
}

function PrintabilityInspector({
  canInspect,
  dismissedRuleIds,
  isInspecting,
  profile,
  report,
  onDismiss,
  onInspect,
  onProfileChange,
}: {
  canInspect: boolean;
  dismissedRuleIds: Set<string>;
  isInspecting: boolean;
  profile: PrintabilityProfile;
  report: PrintabilityReport | null;
  onDismiss: (ruleId: string) => void;
  onInspect: () => void;
  onProfileChange: (profile: PrintabilityProfile) => void;
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

function MessageList({ messages }: { messages: ProjectMessage[] }) {
  if (messages.length === 0) {
    return <p className="empty">No messages</p>;
  }
  return (
    <div className="message-list">
      {messages.map((message) => (
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

  useEffect(() => {
    const mount = mountRef.current;
    if (!mount) {
      return;
    }

    mount.replaceChildren();
    const width = mount.clientWidth;
    const height = mount.clientHeight;
    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0xf4f6f2);
    const camera = new THREE.PerspectiveCamera(40, width / height, 0.1, 5000);
    camera.position.set(120, -140, 90);
    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setSize(width, height);
    renderer.setPixelRatio(window.devicePixelRatio);
    mount.appendChild(renderer.domElement);

    scene.add(new THREE.HemisphereLight(0xffffff, 0x879083, 2.4));
    const grid = new THREE.GridHelper(180, 18, 0x93a19a, 0xd0d6cf);
    scene.add(grid);

    let frame = 0;
    let modelGroup: THREE.Group | null = null;
    let disposed = false;

    if (stlUrl) {
      new STLLoader().load(stlUrl, (geometry) => {
        if (disposed) {
          geometry.dispose();
          return;
        }
        geometry.center();
        geometry.computeBoundingSphere();
        const material = new THREE.MeshStandardMaterial({
          color: 0x2f6f6d,
          roughness: 0.55,
          metalness: 0.08,
        });
        const mesh = new THREE.Mesh(geometry, material);
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
        const radius = geometry.boundingSphere?.radius ?? 80;
        camera.position.set(radius * 1.8, -radius * 2.0, radius * 1.25);
        camera.lookAt(0, 0, 0);
      });
    }

    const animate = () => {
      frame = requestAnimationFrame(animate);
      if (modelGroup) {
        modelGroup.rotation.z += 0.004;
      }
      renderer.render(scene, camera);
    };
    animate();

    return () => {
      disposed = true;
      cancelAnimationFrame(frame);
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
      renderer.dispose();
      mount.replaceChildren();
    };
  }, [highlights, stlUrl]);

  return <div className="viewer" ref={mountRef} />;
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

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
