# Volundr CAD Execution Security

This document defines how Volundr treats AI-generated OpenSCAD as untrusted input and how compilation must be isolated, limited, logged, and failed safely.

## Container Boundaries

The V1 trust boundaries are:

```text
volundr-web
  - untrusted browser input
  - no CAD execution
  - no AI credentials

volundr-api
  - application orchestration
  - Gemini CLI credentials
  - database and project metadata

volundr-cad-worker
  - untrusted generated OpenSCAD
  - restricted CAD execution
  - no Gemini credentials
  - no Docker socket
```

Container names are part of the operational contract and should remain stable for logs, health checks, backup procedures, and Traefik configuration.

## Threat Model

Even in a single-user application, AI-generated source is untrusted input.

The system must assume generated code may:

- be syntactically invalid
- consume excessive CPU
- consume excessive memory
- create enormous output
- recursively expand geometry
- reference unauthorized files
- attempt unsupported import paths
- produce malformed or empty geometry

## Execution Rules

OpenSCAD must be launched using:

- a fixed executable path
- a fixed argument list
- no shell interpolation
- a per-job temporary directory
- a hard timeout
- limited memory and CPU where supported
- output file-size limits
- restricted filesystem visibility

Never run:

```python
subprocess.run(user_generated_string, shell=True)
```

Use:

```python
subprocess.run(
    [OPENSCAD_BINARY, "-o", output_path, source_path],
    shell=False,
    ...
)
```

## Filesystem

The runner should see only:

- the generated source file
- the job working directory
- approved read-only libraries, if introduced later
- the output directory

It should not see:

- host home directories
- application secrets
- Docker socket
- Gemini credentials
- unrelated project files
- network mounts

## Network

The CAD runner does not require network access.

Disable network access for the isolated worker when practical.

## Limits

Initial configurable limits should include:

```text
compile timeout: 60 seconds
maximum source size: 500 KB
maximum STL size: 100 MB
maximum job directory size: 150 MB
maximum model dimension: 2000 mm
minimum non-zero dimension: configurable warning
maximum triangle count: warning and hard ceiling
```

These values are defaults and may be adjusted after testing.

## Source Screening

Before compilation, reject or flag:

- `import(`
- `surface(`
- unexpected absolute paths
- parent directory traversal
- disallowed `use` or `include` paths
- source beyond size limits

OpenSCAD is more constrained than general-purpose Python, but source validation is still required.

## Logging

Store:

- job identifier
- start and end time
- exit code
- timeout status
- stdout
- stderr
- source hash
- output hash
- output size

Do not log Google OAuth tokens or environment secrets.

## Gemini CLI Isolation

Gemini credentials must be mounted only where the AI provider needs them.

The `volundr-cad-worker` container must not have access to the Gemini profile directory. Only `volundr-api` may mount it.

## Failure Behavior

On timeout or resource violation:

- terminate the process tree
- mark the attempt failed
- retain safe diagnostic information
- remove oversized temporary files
- do not automatically retry the exact same source
