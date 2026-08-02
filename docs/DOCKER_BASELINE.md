# Volundr Docker Baseline

This document defines the canonical Docker names and deployment boundaries for V1.

`docs/CADQUERY_BACKEND.md` supersedes this baseline where it describes OpenSCAD execution or weaker CAD-worker isolation. The completed transition requires an isolated non-root no-network CadQuery worker with no provider credentials.

## Services

| Service | Container | Purpose |
|---|---|---|
| `volundr-web` | `volundr-web` | React frontend and browser entrypoint |
| `volundr-api` | `volundr-api` | FastAPI, SQLite, provider orchestration, projects, revisions |
| `volundr-cad-worker` | `volundr-cad-worker` | Isolated CadQuery execution, topology validation, STEP/STL export, and mesh inspection |

## Network

```text
volundr-internal
```

`volundr-web` and `volundr-api` join the internal network. The CAD worker should have the minimum network access required by the selected job transport. Outbound internet access is not required for CAD execution.

## Host Data

```text
/opt/volundr/
├── data/
│   ├── app.db
│   ├── projects/
│   ├── jobs/
│   └── thumbnails/
└── gemini/
```

## Credential Boundary

Only `volundr-api` mounts:

```text
/opt/volundr/gemini:/home/volundr/.gemini
```

`volundr-cad-worker` must never mount Gemini credentials or the Docker socket.

## Example Skeleton

```yaml
services:
  volundr-web:
    container_name: volundr-web
    build: ./frontend
    restart: unless-stopped
    depends_on:
      - volundr-api
    networks:
      - volundr-internal

  volundr-api:
    container_name: volundr-api
    build: ./backend
    restart: unless-stopped
    volumes:
      - /opt/volundr/data:/app/data
      - /opt/volundr/gemini:/home/volundr/.gemini
    networks:
      - volundr-internal

  volundr-cad-worker:
    container_name: volundr-cad-worker
    build: ./cad-worker
    restart: unless-stopped
    volumes:
      - /opt/volundr/data/jobs:/work/jobs
    networks:
      - volundr-internal

networks:
  volundr-internal:
    name: volundr-internal
```

This is a baseline, not a finished production Compose file. Codex may add health checks, read-only mounts, capability restrictions, and resource limits while preserving the canonical names and trust boundaries.
