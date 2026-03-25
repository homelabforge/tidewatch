"""Support duplicate service names across compose files.

Migration: 052
Description: Rebuilds the containers table to:
    - Add docker_name column (actual Docker runtime container name)
    - Replace UNIQUE constraint on name with UNIQUE(service_name, compose_file)
    - name becomes a display-only label (indexed, not unique)
    - Detect and rename duplicate names using compose_file parent dir prefix
    - Cascade renamed names to all denormalized container_name columns via container_id

    SQLite cannot ALTER TABLE to change constraints, so this does a full
    table rebuild following the pattern from migration 050.

    NOTE: Old-style migration (no parameters) because SQLite requires
    PRAGMA foreign_keys=OFF outside any transaction.
"""

import json
import logging
from pathlib import PurePosixPath

from sqlalchemy import text

from app.database import engine

logger = logging.getLogger(__name__)


def _compute_display_name(service_name: str, compose_file: str) -> str:
    """Compute a prefixed display name from compose file path.

    Uses parent directory name as prefix (matches Docker Compose project naming).
    """
    parent = PurePosixPath(compose_file).parent.name
    if parent and parent != ".":
        return f"{parent}-{service_name}"
    # Flat layout — use file stem
    stem = PurePosixPath(compose_file).stem
    if stem and stem not in ("compose", "docker-compose"):
        return f"{stem}-{service_name}"
    return service_name


async def upgrade() -> None:
    """Rebuild containers table with composite unique and docker_name."""
    async with engine.connect() as conn:
        # Disable FK enforcement BEFORE starting the transaction
        await conn.execute(text("PRAGMA foreign_keys=OFF"))

        # Begin explicit transaction for the rebuild
        await conn.execute(text("BEGIN"))

        try:
            # ── Step 1: Detect duplicates ─────────────────────────────
            dupes = (
                await conn.execute(
                    text(
                        "SELECT name, COUNT(*) as cnt FROM containers GROUP BY name HAVING cnt > 1"
                    )
                )
            ).fetchall()

            rename_map: dict[int, str] = {}  # container_id -> new display name

            if dupes:
                logger.warning(
                    "Found %d duplicate container name(s) — will disambiguate",
                    len(dupes),
                )
                for dupe_name, _count in dupes:
                    # Get all containers with this name
                    rows = (
                        await conn.execute(
                            text(
                                "SELECT id, service_name, compose_file FROM containers "
                                "WHERE name = :name"
                            ),
                            {"name": dupe_name},
                        )
                    ).fetchall()

                    # Compute new names
                    new_names: dict[int, str] = {}
                    seen: set[str] = set()
                    for cid, svc_name, comp_file in rows:
                        candidate = _compute_display_name(svc_name, comp_file)
                        if candidate in seen:
                            # Still collides — use full path derivation
                            parent = PurePosixPath(comp_file).parent.name
                            stem = PurePosixPath(comp_file).stem
                            candidate = f"{parent}-{stem}-{svc_name}"
                        seen.add(candidate)
                        new_names[cid] = candidate

                    rename_map.update(new_names)

                logger.info(
                    "Renaming %d containers: %s",
                    len(rename_map),
                    ", ".join(f"id={k} -> {v}" for k, v in rename_map.items()),
                )

            # ── Step 2: Apply renames to old table before copy ────────
            for cid, new_name in rename_map.items():
                await conn.execute(
                    text("UPDATE containers SET name = :name WHERE id = :id"),
                    {"name": new_name, "id": cid},
                )

            # ── Step 3: Cascade renames to denormalized tables via ID ─
            for cid, new_name in rename_map.items():
                # updates
                await conn.execute(
                    text("UPDATE updates SET container_name = :name WHERE container_id = :id"),
                    {"name": new_name, "id": cid},
                )
                # update_history
                await conn.execute(
                    text(
                        "UPDATE update_history SET container_name = :name WHERE container_id = :id"
                    ),
                    {"name": new_name, "id": cid},
                )
                # container_restart_state
                await conn.execute(
                    text(
                        "UPDATE container_restart_state SET container_name = :name "
                        "WHERE container_id = :id"
                    ),
                    {"name": new_name, "id": cid},
                )
                # container_restart_log
                await conn.execute(
                    text(
                        "UPDATE container_restart_log SET container_name = :name "
                        "WHERE container_id = :id"
                    ),
                    {"name": new_name, "id": cid},
                )
                # pending_scan_jobs (via update_id → updates.container_id)
                await conn.execute(
                    text(
                        "UPDATE pending_scan_jobs SET container_name = :name "
                        "WHERE update_id IN ("
                        "  SELECT id FROM updates WHERE container_id = :id"
                        ")"
                    ),
                    {"name": new_name, "id": cid},
                )
                # check_jobs
                await conn.execute(
                    text(
                        "UPDATE check_jobs SET current_container_name = :name "
                        "WHERE current_container_id = :id"
                    ),
                    {"name": new_name, "id": cid},
                )

            # ── Step 4: Update dependencies/dependents JSON arrays ────
            if rename_map:
                # Fetch ALL containers and fix their JSON deps.
                all_containers = (
                    await conn.execute(
                        text(
                            "SELECT id, dependencies, dependents FROM containers "
                            "WHERE dependencies IS NOT NULL OR dependents IS NOT NULL"
                        )
                    )
                ).fetchall()

                # Build name mapping: we renamed service_name -> new display name
                # but deps store old display names (which were = service_name)
                # We need old service_name -> new display name for renamed containers
                old_to_new = {}
                for cid, new_name in rename_map.items():
                    row = (
                        await conn.execute(
                            text("SELECT service_name FROM containers WHERE id = :id"),
                            {"id": cid},
                        )
                    ).fetchone()
                    if row:
                        old_to_new[row[0]] = new_name

                for cid, deps_json, dependents_json in all_containers:
                    if deps_json:
                        try:
                            dep_list = (
                                json.loads(deps_json) if isinstance(deps_json, str) else deps_json
                            )
                            if isinstance(dep_list, list):
                                new_deps = [old_to_new.get(d, d) for d in dep_list]
                                if new_deps != dep_list:
                                    await conn.execute(
                                        text(
                                            "UPDATE containers SET dependencies = :deps "
                                            "WHERE id = :id"
                                        ),
                                        {"deps": json.dumps(new_deps), "id": cid},
                                    )
                        except (json.JSONDecodeError, TypeError):
                            pass

                    if dependents_json:
                        try:
                            dep_list = (
                                json.loads(dependents_json)
                                if isinstance(dependents_json, str)
                                else dependents_json
                            )
                            if isinstance(dep_list, list):
                                new_deps = [old_to_new.get(d, d) for d in dep_list]
                                if new_deps != dep_list:
                                    await conn.execute(
                                        text(
                                            "UPDATE containers SET dependents = :deps "
                                            "WHERE id = :id"
                                        ),
                                        {"deps": json.dumps(new_deps), "id": cid},
                                    )
                        except (json.JSONDecodeError, TypeError):
                            pass

            # ── Step 5: Rebuild containers table ──────────────────────
            # Get current columns to handle schema variations
            cols_info = (await conn.execute(text("PRAGMA table_info(containers)"))).fetchall()
            existing_cols = {row[1] for row in cols_info}

            # Columns present in all versions
            base_columns = [
                "id",
                "name",
                "image",
                "current_tag",
                "current_digest",
                "registry",
                "compose_file",
                "service_name",
                "policy",
                "scope",
                "include_prereleases",
                "vulnforge_enabled",
                "current_vuln_count",
                "is_my_project",
                "update_available",
                "latest_tag",
                "last_checked",
                "last_updated",
                "labels",
                "health_check_url",
                "health_check_method",
                "health_check_auth",
                "release_source",
                "auto_restart_enabled",
                "restart_policy",
                "restart_max_attempts",
                "restart_backoff_strategy",
                "restart_success_window",
                "update_window",
                "dependencies",
                "dependents",
                "created_at",
                "updated_at",
            ]

            # Optional columns added by later migrations
            optional_columns = [
                "latest_major_tag",
                "compose_project",
                "calver_blocked_tag",
                "version_track",
            ]

            # Build column list based on what actually exists
            copy_columns = list(base_columns)
            for col in optional_columns:
                if col in existing_cols:
                    copy_columns.append(col)

            copy_cols_str = ", ".join(copy_columns)

            # Build new table DDL with all columns including docker_name
            await conn.execute(
                text("""
                    CREATE TABLE containers_new (
                        id INTEGER NOT NULL PRIMARY KEY,
                        name VARCHAR NOT NULL,
                        image VARCHAR NOT NULL,
                        current_tag VARCHAR NOT NULL,
                        current_digest VARCHAR,
                        registry VARCHAR NOT NULL,
                        compose_file VARCHAR NOT NULL,
                        service_name VARCHAR NOT NULL,
                        docker_name VARCHAR NULL,
                        policy VARCHAR,
                        scope VARCHAR,
                        include_prereleases BOOLEAN,
                        vulnforge_enabled BOOLEAN,
                        current_vuln_count INTEGER,
                        is_my_project BOOLEAN,
                        update_available BOOLEAN,
                        latest_tag VARCHAR,
                        latest_major_tag VARCHAR,
                        calver_blocked_tag VARCHAR,
                        last_checked DATETIME,
                        last_updated DATETIME,
                        labels JSON,
                        health_check_url VARCHAR,
                        health_check_method VARCHAR DEFAULT 'auto' NOT NULL,
                        health_check_auth VARCHAR,
                        release_source VARCHAR,
                        version_track VARCHAR,
                        auto_restart_enabled BOOLEAN,
                        restart_policy VARCHAR,
                        restart_max_attempts INTEGER,
                        restart_backoff_strategy VARCHAR,
                        restart_success_window INTEGER,
                        update_window VARCHAR,
                        compose_project VARCHAR,
                        dependencies VARCHAR,
                        dependents VARCHAR,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(service_name, compose_file)
                    )
                """)
            )

            # Copy data — docker_name defaults to NULL
            await conn.execute(
                text(f"""
                    INSERT INTO containers_new ({copy_cols_str}, docker_name)
                    SELECT {copy_cols_str}, NULL
                    FROM containers
                """)
            )

            await conn.execute(text("DROP TABLE containers"))
            await conn.execute(text("ALTER TABLE containers_new RENAME TO containers"))

            # ── Step 6: Recreate indexes ──────────────────────────────
            for idx_sql in [
                "CREATE INDEX ix_containers_name ON containers(name)",
                "CREATE INDEX ix_containers_last_checked ON containers(last_checked)",
                "CREATE INDEX ix_containers_policy ON containers(policy)",
                "CREATE INDEX ix_containers_is_my_project ON containers(is_my_project)",
                "CREATE INDEX ix_containers_update_available ON containers(update_available)",
            ]:
                await conn.execute(text(idx_sql))

            logger.info(
                "Rebuilt containers table: docker_name added, "
                "UNIQUE(service_name, compose_file) constraint, "
                "name is now display-only (indexed, not unique)"
            )

            # Commit
            await conn.execute(text("COMMIT"))

        except Exception:
            await conn.execute(text("ROLLBACK"))
            raise

        # ── Step 7: Re-enable FK and verify integrity ─────────────
        await conn.execute(text("PRAGMA foreign_keys=ON"))

        referencing_tables = [
            "updates",
            "update_history",
            "container_restart_state",
            "container_restart_log",
            "pending_scan_jobs",
            "dockerfile_dependencies",
            "app_dependencies",
            "http_servers",
            "metrics_history",
            "check_jobs",
            "vulnerability_scans",
        ]

        for tbl in referencing_tables:
            # Table may not exist in all deployments
            exists = (
                await conn.execute(
                    text("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=:name"),
                    {"name": tbl},
                )
            ).scalar_one()
            if not exists:
                continue

            violations = (await conn.execute(text(f"PRAGMA foreign_key_check({tbl})"))).fetchall()
            if violations:
                logger.error("FK violations in %s after rebuild: %d rows", tbl, len(violations))
                raise RuntimeError(f"FK check failed on {tbl}: {len(violations)} violations")

        logger.info("Foreign key integrity verified across all referencing tables")


async def downgrade() -> None:
    """Downgrade not supported — table rebuilds are not reversible without backup."""
    raise NotImplementedError(
        "Downgrade not supported. Restore from pre-migration backup if needed."
    )
