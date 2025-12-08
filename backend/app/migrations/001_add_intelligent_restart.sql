-- Migration: Add Intelligent Container Restart Support
-- Date: 2025-11-06
-- Description: Adds restart state tracking, restart logs, container restart fields, and restart settings

-- ============================================================================
-- STEP 1: Add restart configuration columns to containers table
-- ============================================================================

-- Check if columns exist and add them if they don't
-- Note: SQLite doesn't support ALTER TABLE IF NOT EXISTS, so we use a simpler approach

ALTER TABLE containers ADD COLUMN auto_restart_enabled BOOLEAN DEFAULT 0;
ALTER TABLE containers ADD COLUMN restart_policy TEXT DEFAULT 'manual';
ALTER TABLE containers ADD COLUMN restart_max_attempts INTEGER DEFAULT 10;
ALTER TABLE containers ADD COLUMN restart_backoff_strategy TEXT DEFAULT 'exponential';
ALTER TABLE containers ADD COLUMN restart_success_window INTEGER DEFAULT 300;

-- ============================================================================
-- STEP 2: Create container_restart_state table
-- ============================================================================

CREATE TABLE IF NOT EXISTS container_restart_state (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    container_id INTEGER NOT NULL UNIQUE,
    container_name TEXT NOT NULL,

    -- Restart tracking
    consecutive_failures INTEGER DEFAULT 0 NOT NULL,
    total_restarts INTEGER DEFAULT 0 NOT NULL,
    last_exit_code INTEGER,
    last_failure_reason TEXT,

    -- Backoff state
    current_backoff_seconds REAL DEFAULT 0.0 NOT NULL,
    next_retry_at TIMESTAMP,
    max_retries_reached BOOLEAN DEFAULT 0 NOT NULL,

    -- Success tracking
    last_successful_start TIMESTAMP,
    last_failure_at TIMESTAMP,
    success_window_seconds INTEGER DEFAULT 300 NOT NULL,

    -- Configuration (per-container overrides)
    enabled BOOLEAN DEFAULT 1 NOT NULL,
    max_attempts INTEGER DEFAULT 10 NOT NULL,
    backoff_strategy TEXT DEFAULT 'exponential' NOT NULL,
    base_delay_seconds REAL DEFAULT 2.0 NOT NULL,
    max_delay_seconds REAL DEFAULT 300.0 NOT NULL,

    -- Health check configuration
    health_check_enabled BOOLEAN DEFAULT 1 NOT NULL,
    health_check_timeout INTEGER DEFAULT 60 NOT NULL,
    rollback_on_health_fail BOOLEAN DEFAULT 0 NOT NULL,

    -- Circuit breaker
    paused_until TIMESTAMP,
    pause_reason TEXT,

    -- Metadata
    restart_history TEXT DEFAULT '[]' NOT NULL,  -- JSON array of timestamps
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,

    FOREIGN KEY (container_id) REFERENCES containers (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_restart_state_container_id ON container_restart_state(container_id);
CREATE INDEX IF NOT EXISTS idx_restart_state_container_name ON container_restart_state(container_name);
CREATE INDEX IF NOT EXISTS idx_restart_state_next_retry ON container_restart_state(next_retry_at);

-- ============================================================================
-- STEP 3: Create container_restart_log table
-- ============================================================================

CREATE TABLE IF NOT EXISTS container_restart_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    container_id INTEGER NOT NULL,
    container_name TEXT NOT NULL,

    -- Attempt details
    attempt_number INTEGER NOT NULL,
    trigger_reason TEXT NOT NULL,
    exit_code INTEGER,

    -- Execution details
    backoff_delay_seconds REAL NOT NULL,
    success BOOLEAN NOT NULL,
    health_check_passed BOOLEAN,
    error_message TEXT,

    -- Timestamps
    scheduled_at TIMESTAMP NOT NULL,
    executed_at TIMESTAMP NOT NULL,
    completed_at TIMESTAMP,

    FOREIGN KEY (container_id) REFERENCES containers (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_restart_log_container_id ON container_restart_log(container_id);
CREATE INDEX IF NOT EXISTS idx_restart_log_scheduled_at ON container_restart_log(scheduled_at);
CREATE INDEX IF NOT EXISTS idx_restart_log_success ON container_restart_log(success);

-- ============================================================================
-- STEP 4: Insert default restart settings
-- ============================================================================

INSERT OR IGNORE INTO settings (key, value, encrypted, category, description)
VALUES
    ('restart_monitor_enabled', 'true', 0, 'restart', 'Enable automatic container restart monitoring'),
    ('restart_monitor_interval', '30', 0, 'restart', 'Interval in seconds to check container health (default: 30)'),
    ('restart_default_strategy', 'exponential', 0, 'restart', 'Default backoff strategy: exponential, linear, or fixed'),
    ('restart_default_max_attempts', '10', 0, 'restart', 'Default maximum restart attempts before giving up'),
    ('restart_base_delay', '2', 0, 'restart', 'Base delay in seconds for exponential backoff (default: 2)'),
    ('restart_max_delay', '300', 0, 'restart', 'Maximum delay in seconds between restart attempts (default: 300)'),
    ('restart_success_window', '300', 0, 'restart', 'Seconds a container must run successfully to reset failure count (default: 300)'),
    ('restart_health_check_timeout', '60', 0, 'restart', 'Timeout in seconds for health checks after restart (default: 60)'),
    ('restart_enable_notifications', 'true', 0, 'restart', 'Send ntfy notifications for restart events'),
    ('restart_max_concurrent', '10', 0, 'restart', 'Maximum number of concurrent restart operations (default: 10)'),
    ('restart_cleanup_interval', '3600', 0, 'restart', 'Interval in seconds to cleanup old restart state (default: 3600)'),
    ('restart_log_retention_days', '30', 0, 'restart', 'Number of days to retain restart logs (default: 30)');

-- ============================================================================
-- STEP 5: Create trigger to update updated_at timestamp
-- ============================================================================

CREATE TRIGGER IF NOT EXISTS update_restart_state_timestamp
AFTER UPDATE ON container_restart_state
BEGIN
    UPDATE container_restart_state
    SET updated_at = CURRENT_TIMESTAMP
    WHERE id = NEW.id;
END;

-- ============================================================================
-- Migration Complete
-- ============================================================================

-- Verify tables were created
SELECT 'Migration complete. Tables created:' AS status;
SELECT name FROM sqlite_master WHERE type='table' AND (name LIKE '%restart%' OR name = 'containers') ORDER BY name;

-- Verify settings were added
SELECT 'Settings added:' AS status;
SELECT key, value FROM settings WHERE category = 'restart' ORDER BY key;
