# TideWatch Release Smoke

Hard release gate. Builds the production image, brings up Postgres + 2
TideWatch instances (PG-backed and SQLite-backed) from scratch, and runs an
HTTP smoke test against both.

## Run

```bash
bash tests/release-smoke/run.sh
```

Takes ~90 seconds on a warm Docker cache. Always tears down on exit.

## What it covers

- All migrations apply cleanly on a fresh SQLite DB.
- Health endpoint responds.
- Auth setup → login → authenticated GET round-trip.

TideWatch's image is SQLite-only (no `asyncpg`/`psycopg2` in the production
deps), so the gate doesn't exercise PostgreSQL. If TideWatch ever ships
PG support, add a `pg` service + second app instance in `compose.yml`.

## Knobs

- `E2E_KEEP=1` — on failure, leave the stack up so you can poke at it.
  Run `bash tests/release-smoke/teardown.sh` when done.
- `E2E_NO_BUILD=1` — reuse the existing `tidewatch:release-smoke` image.

## Where it runs

- **Locally** as the release-coordinator's hard gate before tagging.
