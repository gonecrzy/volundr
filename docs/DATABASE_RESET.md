# Non-production database reset

Volundr’s supported Compose deployment uses one SQLite database at
`{VOLUNDR_DATA_DIR}/app.db`. The reset command is a guarded operator workflow
for a disposable development, test, or staging target. It is not a backup or
production administration tool.

The command defaults to dry-run mode. It requires all of the following before
it can remove the database:

- `--environment` is exactly `development`, `test`, or `staging` (case is
  normalized; production values are rejected);
- `--confirm-database` exactly matches the configured database filename;
- `--allow-destructive-reset` is explicitly supplied for removal;
- the target is not an administrative database or production-denylisted path;
- Docker proves the Volundr API and CadQuery worker are stopped;
- `lsof` proves no process holds the target database; and
- Docker mount inspection proves the data root is not shared with another
  Compose project.

The command holds an advisory lock at `.volundr-reset.lock`, writes redacted
machine-readable evidence, removes only `app.db` and its SQLite `-wal`/`-shm`
sidecars, and runs `alembic upgrade head` from the migration base. It never
stamps a revision, restores application rows, logs a DSN, or deletes the
artifact/evidence directories.

## Local or staging procedure

From the repository root, first stop all Volundr writers through Compose:

```bash
docker compose stop volundr-api volundr-cad-worker volundr-web
```

Run the default dry-run and inspect the report:

```bash
python3 backend/scripts/reset_nonproduction_database.py \
  --environment staging \
  --confirm-database app.db
```

Only after the target and report are certified, run the destructive operation:

```bash
python3 backend/scripts/reset_nonproduction_database.py \
  --environment staging \
  --confirm-database app.db \
  --allow-destructive-reset
```

The migration runner uses a local Alembic installation when available;
otherwise it invokes the rebuilt `volundr-api` Compose image. Start the stack
only after the reset and migration reports succeed:

```bash
docker compose up -d
docker compose ps
```

The default `VOLUNDR_VALIDATED_CADQUERY_FLOW_ENABLED=false` must remain in
place for normal startup. Enable the validated flow only for a separately
controlled staging smoke run. For that run, use the repository `.env` as the
credential source and a separate ignored overlay for the feature flags. The
later `--env-file` overrides only those flags; it must not replace `.env`:

```bash
STAGING_FLAGS=data/debug-sessions/database-rebuild/clean-database-baseline-01/staging-enable.env
docker compose --env-file .env --env-file "$STAGING_FLAGS" build volundr-api volundr-web
docker compose --env-file .env --env-file "$STAGING_FLAGS" up -d
```

Never copy credential values into the overlay, evidence, shell history, or
committed files. The normal `docker compose up -d` command continues to use
the default-disabled flags.

The evidence root is
`data/debug-sessions/database-rebuild/clean-database-baseline-01/`. It may
contain counts, table names, revisions, and test outcomes, but must never
contain credentials, passwords, full DSNs, user messages, provider response
bodies, artifact contents, or personal application data.
