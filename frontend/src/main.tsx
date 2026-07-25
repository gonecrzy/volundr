import React from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";

function App() {
  return (
    <main className="shell">
      <section className="status-panel" aria-labelledby="title">
        <p className="eyebrow">Milestone 1</p>
        <h1 id="title">Volundr CAD Execution Foundation</h1>
        <p>
          The V1 browser workspace is intentionally deferred until the secure
          OpenSCAD execution path is proven.
        </p>
      </section>
    </main>
  );
}

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
