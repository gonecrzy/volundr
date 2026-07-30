# CadQuery Backend Architecture

This document is the authoritative architecture direction for the CadQuery-primary transition. Older documents that describe OpenSCAD as the V1 kernel, Ollama as the intended default provider, the simple prompt-to-source workflow as the primary path, or the current CAD worker as an already-effective sandbox are superseded by this document.

## Strategic Decisions

- Primary CAD backend: CadQuery.
- Strategic geometry kernel: OpenCascade B-Rep through CadQuery.
- Runtime AI provider: Gemini API.
- Optional development provider: Ollama may remain as an adapter, but it is not the product default.
- Authoritative source: CadQuery Python that satisfies the `cadquery-v1` Volundr contract.
- Primary interoperable geometry artifact: STEP.
- Optional internal geometry artifact: BREP when useful and reliable.
- Derived print and preview artifact: STL.
- Normal product lifecycle: staged Design Specification and Parametric Design Plan before source generation.
- Generated CAD execution boundary: isolated, non-root, no-network CAD worker with no provider credentials.

## Current Implementation Status

The current checkout has working OpenSCAD product paths and an experimental CadQuery source probe. CadQuery is not yet the normal project backend. CAD execution still occurs from the API process for product workflows, and the `volundr-cad-worker` container is idle. Phase 1 documentation must not be read as claiming the transition is complete.

OpenSCAD may remain temporarily only to keep intermediate commits runnable and testable. There is no compatibility obligation for existing development databases, old artifact directories, SCAD source paths, OpenSCAD prompts, or SCAD API names.

## Product Lifecycle

Normal generation must use this staged lifecycle:

```text
user request
  -> requirement extraction
  -> Design Specification
  -> user review or clarification
  -> Parametric Design Plan
  -> user approval
  -> Gemini CadQuery generation
  -> source security validation
  -> isolated CadQuery execution
  -> B-Rep topology validation
  -> STEP and STL generation
  -> printability validation
  -> candidate review
  -> explicit acceptance
```

The simple raw prompt-to-source bypass is transitional implementation debt and must not remain the default product path.

## CadQuery Source Authority

Accepted CadQuery Python is the regeneration authority. Provider raw output and extracted source are stored separately. The generated source must declare:

- typed parameters,
- a single `build(params)` entry point,
- one structured `Product`,
- named `PrintableOutput` entries,
- component IDs,
- expected solid counts,
- disconnected-solid policy,
- no top-level geometry execution,
- no direct artifact writing.

The worker owns exports and artifact paths.

## Internal Runtime Contract

Volundr provides a small internal runtime package for generated CadQuery source at `backend/volundr_cad`. It owns:

- `ParameterSpec` definitions,
- validated parameter object creation,
- `Product`,
- `PrintableOutput`,
- validation exceptions,
- output metadata.

The runtime should not hide CadQuery modeling APIs. Generated code may use approved CadQuery modeling operations, but source ownership, output registration, parameter validation, execution, topology checks, and artifact writing belong to Volundr.

Current implementation: Phase 4 introduces the runtime containers and strict AST validation for `cadquery-v1` source. The transitional probe runner still accepts `build_model()` until the Phase 5 execution path calls `build(params)` and exports each `PrintableOutput`.

## Multi-Output Product Model

The same CadQuery contract covers one output or many outputs. Each output has:

- `output_id`,
- `component_id`,
- label,
- quantity,
- required flag,
- output key or entry point,
- STEP path and hash,
- optional BREP path and hash,
- STL path and hash,
- topology metadata,
- mesh metadata,
- validation summary,
- execution state,
- expected solid count,
- detected solid count,
- disconnected-solid policy.

Successful CadQuery outputs must include STEP and STL. BREP is optional until persistence proves worthwhile.

## Typed Parameter Execution

Configuration changes are deterministic and provider-free:

```text
accepted CadQuery source
  + validated parameter values
  -> isolated execution
  -> topology and mesh validation
  -> candidate
```

The application must validate type, range, enum membership, editability, protected values, dependencies, and unsupported structural changes before execution. It must not rewrite source or use command-line expressions for parameter changes.

## Topology Validation

B-Rep topology validation happens before meshing. Each output must be checked for:

- requested output existence,
- supported CadQuery/OpenCascade shape data,
- non-null shape,
- shape validity,
- nonzero volume,
- detected solid count,
- expected solid count,
- disconnected-body policy,
- bounding box,
- component and output identity.

Normal single-piece outputs use `expected_solid_count = 1` and `allow_disconnected_solids = false`. Intentional multiple-body or print-in-place outputs must declare both an expected count greater than one and `allow_disconnected_solids = true`.

STL mesh analysis remains useful for preview, build-volume checks, printability checks, and coarse geometry evidence, but it is not a substitute for B-Rep topology validation.

## Security Boundary

Generated CadQuery Python is untrusted code. AST validation is defense in depth, not the sandbox.

The production execution boundary is:

```text
volundr-api
  -> structured CAD execution job
  -> volundr-cad-worker
  -> isolated CadQuery process
  -> result manifest
  -> API persistence and candidate lifecycle
```

The worker must:

- run as a dedicated non-root user,
- have no Gemini profile mount,
- have no Gemini API key,
- have no Ollama or provider credentials,
- have no Docker socket,
- avoid mounting the whole application data directory,
- receive only job input and output paths,
- use a read-only root filesystem where practical,
- have only required writable temporary paths,
- run with network disabled or equivalent egress isolation,
- use bounded CPU, memory, process, and wall-clock limits,
- scrub inherited environment variables,
- emit structured success and failure manifests.

## OpenSCAD Removal Plan

OpenSCAD remains temporary implementation debt during the transition. The completed architecture removes these normal product paths:

- OpenSCAD packages in Docker images,
- OpenSCAD runner,
- OpenSCAD source extraction,
- OpenSCAD scanner and markers,
- OpenSCAD parameter parser,
- `-D` override logic,
- `selected_output` dispatch,
- SCAD prompt and repair modes,
- SCAD API schemas and UI labels,
- permanent dual-backend compatibility fields.

Historical benchmark notes may remain when they are clearly labeled as historical.

## Non-Goals

- Preserve existing development database contents.
- Preserve existing artifact directory contents.
- Build a permanent OpenSCAD/CadQuery dual-backend product.
- Keep SCAD canonical fields as long-term aliases.
- Call live Gemini before deterministic execution and fake-provider lifecycle tests are reliable.
- Add fishing-tray-specific architecture.
- Treat mesh-only validation as proof of valid B-Rep topology.
- Allow generated code to choose export paths or write artifacts directly.
