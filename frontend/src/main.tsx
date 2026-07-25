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
  revision_number: number;
  status: string;
  is_accepted: boolean;
  user_instruction: string | null;
  created_at: string;
  metadata: MeshMetadata | null;
  error_message: string | null;
};

function App() {
  const [projectName, setProjectName] = useState("Mounting bracket");
  const [intent, setIntent] = useState("A flat mounting bracket with two bolt holes.");
  const [instruction, setInstruction] = useState("Initial manual model.");
  const [source, setSource] = useState(DEFAULT_SOURCE);
  const [project, setProject] = useState<Project | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [revisions, setRevisions] = useState<Revision[]>([]);
  const [selectedRevision, setSelectedRevision] = useState<Revision | null>(null);
  const [isCompiling, setIsCompiling] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const activeMetadata = selectedRevision?.metadata ?? null;
  const stlUrl = selectedRevision?.is_accepted
    ? `${API_BASE}/revisions/${selectedRevision.id}/stl`
    : null;

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
      setProject({ ...currentProject, active_revision_id: revision.is_accepted ? revision.id : currentProject.active_revision_id });
      setMessage(revision.status === "succeeded" ? "Compiled" : revision.error_message ?? "Compile failed");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Request failed");
    } finally {
      setIsCompiling(false);
    }
  }

  async function selectRevision(revision: Revision) {
    setSelectedRevision(revision);
    const response = await fetch(`${API_BASE}/revisions/${revision.id}/source`);
    if (response.ok) {
      setSource(await response.text());
    }
  }

  async function selectProject(nextProject: Project) {
    setProject(nextProject);
    setProjectName(nextProject.name);
    setIntent(nextProject.original_intent);
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
    }
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
                <span>R{revision.revision_number}</span>
                <span>{revision.status}</span>
              </button>
            ))}
          </div>
          {message ? <p className="message">{message}</p> : null}
        </aside>

        <section className="viewer-panel" aria-label="STL preview">
          <StlViewer stlUrl={stlUrl} />
        </section>

        <section className="metadata-panel" aria-label="Metadata">
          <h2>Metadata</h2>
          <Metadata metadata={activeMetadata} />
          {stlUrl ? (
            <a className="download" href={stlUrl}>
              Download STL
            </a>
          ) : null}
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

function StlViewer({ stlUrl }: { stlUrl: string | null }) {
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
    let mesh: THREE.Mesh | null = null;
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
        mesh = new THREE.Mesh(geometry, material);
        scene.add(mesh);
        const radius = geometry.boundingSphere?.radius ?? 80;
        camera.position.set(radius * 1.8, -radius * 2.0, radius * 1.25);
        camera.lookAt(0, 0, 0);
      });
    }

    const animate = () => {
      frame = requestAnimationFrame(animate);
      if (mesh) {
        mesh.rotation.z += 0.004;
      }
      renderer.render(scene, camera);
    };
    animate();

    return () => {
      disposed = true;
      cancelAnimationFrame(frame);
      scene.traverse((object) => {
        if (object instanceof THREE.Mesh) {
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
  }, [stlUrl]);

  return <div className="viewer" ref={mountRef} />;
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
