# TideWatch Database Migrations

This directory contains database migration scripts for TideWatch.

## Migration Files

### 001_add_intelligent_restart

Adds intelligent container restart support with exponential backoff.

**What it adds:**
- Restart configuration columns to `containers` table
- `container_restart_state` table for tracking restart state and backoff
- `container_restart_log` table for audit trail
- 12 new restart-related settings

**Files:**
- `001_add_intelligent_restart.sql` - Raw SQL migration
- `001_add_intelligent_restart.py` - Python migration script (recommended)

## Running Migrations

### Option 1: Python Script (Recommended)

The Python script is safer as it checks for existing tables/columns before making changes:

```bash
cd /srv/raid0/docker/build/tidewatch/backend
python migrations/001_add_intelligent_restart.py
```

### Option 2: Direct SQL

If you prefer to run the SQL directly:

```bash
cd /srv/raid0/docker/build/tidewatch/backend
sqlite3 data/tidewatch.db < migrations/001_add_intelligent_restart.sql
```

### Option 3: Automatic Migration via SQLAlchemy

TideWatch uses SQLAlchemy's `Base.metadata.create_all()`, which will automatically create any missing tables when the application starts. However, it **will not** add columns to existing tables.

If you're starting fresh, simply start the application and it will create all tables automatically.

If you're upgrading an existing installation, you **must** run the migration script to add the new columns to the `containers` table.

## Verifying Migration

After running the migration, verify it succeeded:

```bash
sqlite3 data/tidewatch.db "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%restart%';"
```

You should see:
- `container_restart_state`
- `container_restart_log`

Check for new columns in containers table:

```bash
sqlite3 data/tidewatch.db "PRAGMA table_info(containers);" | grep restart
```

You should see:
- `auto_restart_enabled`
- `restart_policy`
- `restart_max_attempts`
- `restart_backoff_strategy`
- `restart_success_window`

Check for restart settings:

```bash
sqlite3 data/tidewatch.db "SELECT key FROM settings WHERE category = 'restart';"
```

You should see 12 restart-related settings.

## Rollback

If you need to rollback the migration:

```sql
-- Remove restart columns from containers (SQLite doesn't support DROP COLUMN easily)
-- Instead, you would need to recreate the table without those columns

-- Drop restart tables
DROP TABLE IF EXISTS container_restart_log;
DROP TABLE IF EXISTS container_restart_state;

-- Remove restart settings
DELETE FROM settings WHERE category = 'restart';

-- Drop trigger
DROP TRIGGER IF EXISTS update_restart_state_timestamp;
```

## Migration Best Practices

1. **Always backup your database before running migrations:**
   ```bash
   cp data/tidewatch.db data/tidewatch.db.backup
   ```

2. **Test migrations on a copy of your production database first**

3. **Run migrations when the application is stopped** to avoid conflicts

4. **Verify the migration succeeded** before restarting the application

## Future Migrations

When creating new migrations:

1. Number them sequentially: `002_migration_name.sql` and `002_migration_name.py`
2. Document what the migration does in this README
3. Make the migration idempotent (safe to run multiple times)
4. Include rollback instructions

### 002_update_history_reason_fields

Adds reason context to the `update_history` table so TideWatch can surface why a deploy happened inside the UI and notifications.

**What it adds:**
- `reason_type` column (security, feature, bugfix, maintenance, etc.)
- `reason_summary` column mirroring the summary shown on updates
- Backfills the new columns using the legacy `reason` field and `updates.reason_type`

**Run it with:**

```bash
cd /srv/raid0/docker/build/tidewatch/backend
python migrations/002_update_history_reason_fields.py
```

### 003_add_health_check_method

Adds a `health_check_method` column to `containers`, enabling TideWatch to force
HTTP-based checks, Docker/engine checks, or leave it on automatic detection.

**Run it with:**

```bash
cd /srv/raid0/docker/build/tidewatch/backend
python migrations/003_add_health_check_method.py
```

### 004_add_health_check_auth

Adds a `health_check_auth` column to `containers` for storing optional sensitive
tokens/headers used only during HTTP health probes (never exposed via API).

**Run it with:**

```bash
cd /srv/raid0/docker/build/tidewatch/backend
python migrations/004_add_health_check_auth.py
```

### 005_add_release_source

Adds a `release_source` column to `containers` so each tracked image can reference
its upstream changelog feed (e.g., GitHub repo or custom URL) for reason classification.

**Run it with:**

```bash
cd /srv/raid0/docker/build/tidewatch/backend
python migrations/005_add_release_source.py
```

### 006_add_dockerfile_severity

Adds a `severity` column to `dockerfile_dependencies` to track update severity (patch/minor/major)
for Dockerfile base images, enabling the UI to display update type badges like "Major Update".

**Run it with:**

```bash
cd /srv/raid0/docker/build/tidewatch/backend
python migrations/006_add_dockerfile_severity.py
```
