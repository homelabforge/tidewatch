# Changelog

All notable changes to TideWatch will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [3.5.3] - 2025-12-10

### Fixed
- **CRITICAL: Concurrent Update Race Condition** - Fixed race conditions when multiple updates are applied simultaneously
  - Root cause: Single `applyingUpdateId` state variable caused concurrent operations to overwrite each other's busy/blur indicators
  - Database race conditions in `batch_approve_updates()`, `approve_update()`, `batch_reject_updates()` functions due to check-then-commit pattern without transaction locks
  - Backend: Implemented optimistic locking with `version` column on updates table
  - Backend: Wrapped all status updates in nested transactions (`db.begin_nested()`) for atomicity
  - Backend: Added idempotency checks to allow safe retries (approve → approve transitions)
  - Backend: Proper `OperationalError` handling for concurrent modification detection
  - Backend: Version increments on every status change for race detection
  - Frontend: Changed from single `applyingUpdateId` to Set-based tracking (`applyingUpdateIds`, `approvingUpdateIds`, `rejectingUpdateIds`)
  - Frontend: Duplicate-click prevention with early return if operation already in progress
  - Frontend: Enhanced error messages for concurrent modification scenarios
  - Frontend: Independent busy/blur indicators per update card using `isAnyOperationInProgress` helper
  - Frontend: All buttons disabled during any operation to prevent conflicts
  - Migration: Created `029_add_optimistic_locking.py` to add version column
  - Migration: Created `030_add_version_index.py` for performance optimization on (status, version)
  - Impact: Users can now safely apply multiple updates in parallel without UI state corruption or database errors
  - Result: Each update maintains its own loading state, operations process correctly in parallel
  - **Files modified:**
    - `backend/app/models/update.py` - Added version column (line 66)
    - `backend/app/api/updates.py` - Fixed 5 functions with nested transactions and idempotency
    - `backend/app/services/update_engine.py` - Added version increments at lines 331, 471
    - `frontend/src/pages/Updates.tsx` - Set-based state tracking for concurrent operations
    - `frontend/src/components/UpdateCard.tsx` - Multiple operation props and unified loading state

### Added
- **Optimistic Locking Infrastructure** - Version-based concurrency control
  - New `version` column on updates table (defaults to 1)
  - Automatic version increment on every status change
  - Database index on (status, version) for faster concurrent queries
  - Migration system handles automatic schema updates on container restart

## [3.5.2] - 2025-12-10

### Fixed
- Fixed migration runner to support multiple migration function signatures
  - Now supports `upgrade()`, `migrate()`, and `up()` function names
  - Automatically detects if migration function expects a database connection parameter
  - Fixes startup errors with newer migrations that use different naming conventions
- Fixed migration 027 to properly wrap SQL statements with `text()` for SQLAlchemy 2.0 compatibility
- Fixed duplicate migration numbers caused by parallel development
  - Renamed `006_add_dockerfile_severity.py` → `018_add_dockerfile_severity.py`
  - Renamed `007_update_restart_log_schema.py` → `028_update_restart_log_schema.py`
  - Migration sequence now properly ordered: 001-028 without gaps or duplicates

## [3.5.1] - 2025-12-10

### Fixed
- Fixed `ResponseValidationError` in settings API endpoint when `encrypted` field was `null`
  - Changed `SettingSchema.encrypted` from `bool` to `Optional[bool]` to handle existing database records with null values
  - Maintains backward compatibility with settings having `true`, `false`, or `null` encrypted values

### Added
- Added `compose.dev.yaml` to `.gitignore` for local development customization
  - Developers can now create custom local compose files without affecting git

## [3.5.0] - 2025-12-10

### Changed
- **[BREAKING]** Migrated frontend from Node.js 24 to Bun 1.3.4 runtime
  - Package manager: npm → bun
  - Lockfile: package-lock.json → bun.lock
  - Docker base image: node:24-alpine → oven/bun:1.3.4-alpine
  - ~10-25x faster dependency installation
  - ~40-60% smaller Docker images
  - All development commands now use `bun` instead of `npm`

### Developer Impact
- Install Bun 1.3.4+ for local development: https://bun.sh/docs/installation
- Run `bun install` instead of `npm ci`
- Run `bun dev` instead of `npm run dev`
- Run `bun test` instead of `npm test`
- See [DEVELOPMENT.md](DEVELOPMENT.md) for full guide

### Infrastructure
- Vite 7.2.6 bundler retained (no changes to build output)
- Vitest 4.0.15 test runner retained (all tests unchanged)
- Backend unchanged (Python 3.14 + FastAPI)
- Zero application code changes
- Production deployment compatible (same Docker interface)

### Performance Improvements
- Package install: ~10-25x faster
- Build time: ~1.5-2x faster
- Docker image: ~40-60% smaller
- CI/CD runtime: ~2x faster

### Fixed
- Fixed TypeScript compilation errors in frontend type definitions
  - Added missing `id` property to `UserProfile` interface
  - Fixed CSRF header type incompatibility in API client
  - Removed unused variables in test files
- Fixed CodeQL security and code quality issues
  - Fixed illegal raise of potentially None exception in retry decorators
  - Removed redundant json import in docker_stats.py
  - Removed unused imports across backend and frontend

### Changed
- Updated GitHub Actions workflows to latest versions
  - actions/upload-artifact v4 → v5
  - actions/checkout v4 → v6
  - actions/setup-python v5 → v6
- Added comprehensive GitHub repository configuration
  - Issue templates (bug reports, feature requests)
  - Pull request template with testing checklist
  - Dependabot configuration for automated dependency updates
  - GitHub release workflow with changelog extraction
  - Docker build workflow for multi-platform images

## [3.4.0] - 2025-12-06

### Security
- **CRITICAL:** Fixed 9 path injection vulnerabilities in file operations
  - Database path validation (prevents access outside `/data` or `/tmp`)
  - JWT secret key file validation
  - Compose directory validation (restricted to `/compose`, `/tmp`, or configured paths)
  - Projects directory validation (restricted to `/projects`, `/tmp`, or `/srv/raid0/docker/build`)
  - Added `sanitize_path()` utility to validate paths against allowed base directories
  - Rejects path traversal attempts (`../`, symlinks escaping base directory)
- **CRITICAL:** Fixed clear text storage of sensitive data in database
  - Implemented Fernet encryption for 14 sensitive database fields
  - Encrypted fields: API keys (Docker Hub, GitHub, VulnForge), notification tokens (ntfy, Gotify, Pushover, Slack, Discord, Telegram), passwords (SMTP, VulnForge, admin), webhook URLs, OIDC client secrets
  - Automatic encryption/decryption in SettingsService (transparent to application code)
  - Migration `024_mark_sensitive_settings_encrypted.py` marks sensitive settings
  - Requires `TIDEWATCH_ENCRYPTION_KEY` environment variable (Fernet key)
- **CRITICAL:** Fixed stack trace exposure in API error responses
  - Added global exception handler to prevent information leakage
  - Production mode (`TIDEWATCH_DEBUG=false`): Returns generic "internal error" messages
  - Development mode (`TIDEWATCH_DEBUG=true`): Returns full stack traces for debugging
  - Removed `traceback.print_exc()` from database initialization
  - Internal logging preserves full error details regardless of mode
- **CRITICAL:** Enhanced SSRF protection for all webhook/notification URLs
  - Validates all webhook URLs to prevent Server-Side Request Forgery
  - Blocks private IP ranges (RFC 1918), loopback addresses, link-local addresses
  - Blocks cloud metadata services (169.254.169.254)
  - Validates DNS to prevent DNS rebinding attacks
  - Public webhooks (Slack, Discord): Strict validation (HTTPS only, no private IPs)
  - Self-hosted services (ntfy, Gotify): Flexible validation (allows HTTP, private IPs, localhost)
- Fixed log injection vulnerabilities across codebase
  - Added `sanitize_log_message()` utility to remove control characters (`\n`, `\r`, `\t`, 0x00-0x1f, 0x7f-0x9f)
  - Applied to user-controlled data before logging (container names, image names, error messages)
  - Prevents log forgery and log file poisoning attacks
- Added sensitive data masking in logs
  - Created `mask_sensitive()` utility to show only last 4 characters of secrets
  - Applied to: JWT tokens, API keys, passwords, webhook URLs, bot tokens
  - Format: `***abcd` (3 asterisks + last 4 visible characters)

### Added
- **Database Encryption Infrastructure**
  - New `EncryptionService` class in `app/utils/encryption.py`
  - Singleton pattern with environment-based key management
  - Automatic key loading from `TIDEWATCH_ENCRYPTION_KEY`
  - Error handling for missing encryption keys (warns but doesn't break)
- **Path Validation Infrastructure**
  - New `sanitize_path()` function in `app/utils/security.py`
  - Validates paths are within allowed base directories
  - Optional symlink rejection for maximum security
  - Clear error messages for path traversal attempts
- **Log Security Infrastructure**
  - New `sanitize_log_message()` function in `app/utils/security.py`
  - New `mask_sensitive()` function in `app/utils/security.py`
  - Applied to Slack notification service (template for other services)
- **Debug Mode Configuration**
  - New `TIDEWATCH_DEBUG` environment variable
  - Controls stack trace exposure in API responses
  - Defaults to `false` (secure by default)
  - Documented in `.env` and `SECURITY.md`

### Changed
- Updated `SECURITY.md` with comprehensive v3.4.0 documentation
  - Secrets encryption configuration and field list
  - SSRF protection mechanisms and service configurations
  - Path traversal protection details
  - Log injection prevention implementation
  - Stack trace protection configuration

### Migration
- Run migration `024_mark_sensitive_settings_encrypted.py` on startup
  - Automatically marks 14 sensitive settings as encrypted
  - Existing plain-text values remain until re-saved through UI/API
  - Safe to run multiple times (idempotent)

### Configuration Required
- **Generate encryption key**: `python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`
- **Set environment variable**: `export TIDEWATCH_ENCRYPTION_KEY=<generated-key>`
- **Re-save sensitive settings** through UI to encrypt existing plain-text values
- **Set debug mode** (production): `export TIDEWATCH_DEBUG=false`

### Files Created
- `backend/app/utils/security.py` - Security utilities (sanitization, validation, masking)
- `backend/app/utils/encryption.py` - Encryption service (Fernet-based)
- `backend/app/migrations/024_mark_sensitive_settings_encrypted.py` - Database migration

### Files Modified
- `backend/app/db.py` - Path validation, removed traceback exposure
- `backend/app/main.py` - Path validation, global exception handler
- `backend/app/services/auth.py` - JWT secret file path validation
- `backend/app/services/settings_service.py` - Automatic encryption/decryption logic
- `backend/app/services/compose_parser.py` - Compose directory path validation
- `backend/app/services/dockerfile_parser.py` - Projects directory path validation
- `backend/app/services/project_scanner.py` - Projects directory path validation
- `backend/app/services/notifications/slack.py` - SSRF validation, log sanitization
- `backend/app/services/notifications/discord.py` - SSRF validation
- `backend/app/services/notifications/ntfy.py` - SSRF validation
- `backend/app/services/notifications/gotify.py` - SSRF validation
- `.env` - Added `TIDEWATCH_DEBUG` configuration
- `SECURITY.md` - Comprehensive v3.4.0 security documentation

## [3.3.2] - 2025-12-06

### Added
- **Unified History Page** - History page now shows both container updates and restart events
  - Changed page title from "Update History" to "History"
  - Changed subtitle to "View container updates and restart events"
  - Unified event stream merges `update_history` and `container_restart_log` tables
  - New backend schema: `UnifiedHistoryEventSchema` combining both event types
  - Conditional rendering: Updates show `from_tag → to_tag`, Restarts show trigger reason
  - Enhanced status badges:
    - `restarted`: Blue badge - successful restart, container running
    - `crashed`: Orange badge - container exited after restart
    - `failed_to_restart`: Red badge - restart command failed
  - Trigger reason formatting with user-friendly names:
    - `exit_code` → "Container Exited"
    - `health_check` → "Health Check Failed"
    - `oom_killed` → "Out of Memory"
    - `signal_killed_SIGKILL` → "Killed (SIGKILL)"
    - `signal_killed_SIGTERM` → "Terminated (SIGTERM)"
    - `manual:reason` → extracts custom reason
  - Exit codes displayed for crashed containers (e.g., "exit 137")
  - Visual indicators: Arrow icon for updates, RefreshCw icon for restarts
  - API endpoint: `GET /api/v1/history/` returns unified event list
  - Chronological sorting by `started_at` timestamp
  - **Files modified:**
    - `backend/app/schemas/history.py` - Added `UnifiedHistoryEventSchema`
    - `backend/app/api/history.py` - Modified endpoint to merge both tables
    - `frontend/src/types/index.ts` - Added `UnifiedHistoryEvent` type
    - `frontend/src/services/api.ts` - Updated API service return type
    - `frontend/src/components/StatusBadge.tsx` - Added restart status colors
    - `frontend/src/pages/History.tsx` - Complete rewrite with conditional rendering

### Fixed
- **CRITICAL: Database Schema Mismatch** - Fixed container restart logging failure
  - Root cause: Production database had only 13 columns, code expected 26 columns
  - Error: `sqlite3.OperationalError: table container_restart_log has no column named restart_state_id`
  - Impact: Auto-restart system could not log restart attempts, blocking feature entirely
  - Created migration: `007_update_restart_log_schema.py`
  - Added 13 missing columns:
    - `restart_state_id` - FK to container_restart_state
    - `failure_reason` - Detailed failure description
    - `backoff_strategy` - Strategy used (exponential/linear/fixed)
    - `restart_method` - docker_compose or docker_restart
    - `docker_command` - Actual command executed
    - `duration_seconds` - Execution duration
    - `health_check_enabled` - Whether health check was enabled
    - `health_check_duration` - Health check duration
    - `health_check_method` - http or docker_inspect
    - `health_check_error` - Health check error message
    - `final_container_status` - Container status after restart
    - `final_exit_code` - Exit code after restart
    - `created_at` - Timestamp when log entry was created
  - Result: Auto-restart logging now functional, all restart attempts tracked

### Testing
- **Auto-Restart Feature Validation** - Comprehensive testing of auto-restart system
  - Test container: `dozzle` (log viewer)
  - Test methods: SIGKILL, SIGTERM, multiple consecutive failures
  - Validated behaviors:
    - Failure detection within 30-second monitoring interval
    - Exponential backoff: 2s → 4s → 8s → 16s → 32s (with jitter)
    - Success window resets failure counters after 120 seconds
    - Circuit breaker triggers on restart command failures (not container crashes)
    - Self-healing for dependency failures
  - Logged 13 restart attempts during testing (now visible in unified history)
  - **Detailed test plan:** `/home/jamey/.claude/plans/cached-tickling-parasol.md`
  - **Comprehensive analysis:** `/srv/raid0/docker/documents/history/tidewatch/2025-12-06-unified-history-autorestart-testing.md`

## [3.3.1] - 2025-12-06

### Fixed
- **CRITICAL: CVE Tracking Bug** - Fixed SQLAlchemy JSON column deserialization issue causing CVE data loss
  - Root cause: `Column(JSON, default=list)` created shared mutable default across all instances
  - Changed to `default=lambda: []` with `server_default='[]'` in both Update and UpdateHistory models
  - Added defensive CVE data loading with `db.refresh()` and sanity checks before creating UpdateHistory records
  - Post-update VulnForge rescans now backfill both Update and UpdateHistory tables (previously only Update)
  - Created migration script `023_fix_cve_tracking_json_defaults.py` to backfill historical data
  - Impact: Dashboard was showing 0 CVEs resolved despite successful security updates being applied
  - Result: All 27 CVEs from last 30 days now correctly displayed (12 from recent updates + 15 from prior updates)
  - **Files modified:**
    - `backend/app/models/update.py` - Fixed JSON column default (line 38)
    - `backend/app/models/history.py` - Fixed JSON column default (line 39)
    - `backend/app/services/update_engine.py` - Added defensive loading (lines 127-150) and backfill logic (lines 1703-1715)
    - `backend/app/migrations/023_fix_cve_tracking_json_defaults.py` - New migration script
  - **Detailed analysis:** `/srv/raid0/docker/documents/history/tidewatch/2025-12-06-cve-tracking-bug-fix.md`

## [3.3.0] - 2025-12-06

### Added
- **Update Loading UI** - Visual feedback during manual container updates
  - Large centered spinner (Loader2 icon, 64px) appears over update card
  - Blur effect (`blur-sm`) applied to card content beneath spinner
  - Semi-transparent overlay with backdrop blur for depth
  - All action buttons disabled during update process to prevent double-clicks
  - Polling logic ensures spinner persists until update fully completes (up to 30s)
  - Prevents premature state refresh before backend processing finishes
  - Particularly valuable for large image updates (e.g., OpenWebUI: 8+ minutes)
  - Added `get(id)` method to frontend update API for status polling
  - **Files modified:**
    - `frontend/src/components/UpdateCard.tsx` - Loading overlay and blur effects
    - `frontend/src/pages/Updates.tsx` - State management and polling logic
    - `frontend/src/services/api.ts` - Added update status endpoint

### Security
- **CRITICAL:** Updated React 19.2.1 and React-DOM 19.2.1 to patch CVE-2025-55182 (CVSS 10.0 RCE vulnerability in React Server Components)
  - While Tidewatch uses React for SPA only (not affected), update recommended for security posture

### Updated - Dockerfile
- Node.js 22-alpine → 24-alpine (Latest LTS "Krypton", supported until April 2028)
  - V8 engine improvements, better performance, enhanced security
  - Longer support period than Node.js 25 (non-LTS)

### Updated - Frontend Dependencies
- lucide-react: 0.555.0 → 0.556.0 (new icons: book-search, scooter, plug, thermometer-sun, estimated-weight, flashlight, bubbles, van)
- react: 19.2.0 → 19.2.1 (security patch)
- react-dom: 19.2.0 → 19.2.1 (security patch)
- react-router-dom: 7.9.6 → 7.10.1 (bug fixes)
- typescript-eslint: 8.48.0 → 8.48.1 (linting fixes)
- vite: 7.2.4 → 7.2.6 (patch fixes)

### Updated - Backend Dependencies
- pytest: 8.3.0 → 9.0.1 (terminal progress display, strict parameter IDs, Python 3.9 dropped)
- pytest-asyncio: 0.24.0 → 1.3.0 (event loop scoping improvements, strict mode default)
- pytest-cov: 4.1.0 → 7.0.0 (simplified packaging, requires coverage ≥7.10.6)
- httpx: 0.27.2 → 0.28.1 (JSON compact format, SSL API deprecations, WHATWG spec compliance)
- ruff: 0.7.0 → 0.14.8 (7 minor versions, many new rules and fixes, improved linting)

### Fixed
- **Update Status Synchronization** - Resolved timing issues between frontend and backend
  - Frontend now polls for confirmed completion instead of assuming immediate success
  - Prevents "applied but still showing pending" confusion
  - Ensures update history accurately reflects completion before clearing loading state

## [3.2.0] - 2025-12-06

### Added
- **OIDC/SSO Authentication** - OpenID Connect single sign-on support
  - OAuth 2.0 authorization code flow with PKCE
  - Full OIDC provider integration (Authentik, Keycloak, Auth0, etc.)
  - OIDC configuration UI in Settings → System → Authentication
  - Test Connection button to validate provider connectivity
  - Secure secret masking with `is_masked_secret()` function
  - Session-based state and nonce management for CSRF protection
  - JWT ID token verification with issuer, audience, and nonce claims
  - Userinfo endpoint support for additional claims
  - Single-user mode: OIDC accounts link to admin account
  - New API endpoints: `GET/PUT /api/v1/auth/oidc/config`, `POST /api/v1/auth/oidc/test`, `GET /api/v1/auth/oidc/login`, `GET /api/v1/auth/oidc/callback`
  - CSRF exemptions for OIDC callback and test endpoints
  - New dependencies: `authlib>=1.6.5` for OIDC/JWT, `cryptography>=46.0.0` for key validation
  - Backend: `/backend/app/api/oidc.py` (12 endpoints), `/backend/app/services/oidc.py` (600+ lines)
  - Frontend: OIDC configuration panel in Settings.tsx with masked secret fields

### Changed
- **Version Management** - Implemented single-source-of-truth versioning
  - Backend version now read from `pyproject.toml` at runtime using `tomllib`
  - Added `get_version()` function in `main.py` with fallback to "0.0.0-dev"
  - Eliminated version drift between `pyproject.toml` and `main.py`
  - Matches MyGarage implementation pattern from dev-sop.md

### Fixed
- **OIDC Token Exchange** - Fixed client authentication method for Authentik compatibility
  - Changed from HTTP Basic Auth to form-encoded credentials (`client_id` and `client_secret` in POST body)
  - Resolved "invalid_client" errors during token exchange
  - Added `get_userinfo()` function (was missing, causing AttributeError)
  - Fixed `link_oidc_to_admin()` signature to accept `userinfo` parameter

## [3.1.0] - 2025-11-28

### Added
- **Multi-Service Notification System** - Support for 7 notification services beyond ntfy
  - **Gotify** - Self-hosted push notification server support
  - **Pushover** - Cross-platform push notification service ($5 one-time)
  - **Slack** - Incoming webhooks for team notifications
  - **Discord** - Webhook integration for server notifications
  - **Telegram** - Bot API integration with HTML formatting
  - **Email** - SMTP support with HTML emails and TLS
  - All services share unified architecture with abstract base class
  - Event-based routing via NotificationDispatcher
  - Per-service enable toggles with validation
  - Test Connection buttons for all services
  - Expandable event group UI (Updates, Restarts, System)
  - Service sub-tabs with enabled indicators (green dot)
  - Backend: `/backend/app/services/notifications/` (8 files)
  - Frontend: `/frontend/src/components/notifications/` (9 components)
  - New API endpoints: `POST /api/v1/settings/test/{service}` for all 7 services
  - New dependency: `aiosmtplib>=3.0.0` for async SMTP

### Changed
- **Notification Architecture** - Migrated from single-service to multi-service pattern
  - All notification call sites now use `NotificationDispatcher` instead of direct `NtfyService`
  - Updated: `update_checker.py`, `update_engine.py`, `restart_service.py`, `restart_scheduler.py`, `scheduler.py`
  - Removed: `ntfy_service.py` (replaced by notifications module)

### Fixed
- **Update Notification Timing** - Ntfy notifications now sent after database commit
  - Previously, notifications were sent before `db.commit()` completed
  - This caused race conditions where users received phone notifications but updates weren't visible in UI
  - Now commits per-container instead of batching, ensuring notifications match persisted state
  - Added rollback handling for failed container checks to prevent partial transaction issues

## [3.0.0] - 2025-11-24

### Security
- **CSRF Protection** - Session-based double-submit pattern
  - SessionMiddleware with secure, HttpOnly cookies
  - Constant-time token comparison prevents timing attacks
  - SameSite=Lax for additional protection
- **Rate Limiting** - Endpoint-specific limits
  - Container operations: 5 req/min (prevents restart spam)
  - Update operations: 3 req/min (prevents update flooding)
  - Settings changes: 10 req/min
- **Command Injection Prevention** - Centralized input validation
  - Container names, service names validated against shell metacharacters
  - Docker compose commands use whitelist-based validation
  - List-based subprocess calls (no shell=True)
- **Path Traversal Protection** - Multi-layer path validation
  - Dangerous pattern detection (`..`, `//`, `\`, null bytes)
  - Base directory containment checks
  - Symlink escape prevention
  - Extension validation for compose files
- **Security Headers** - Comprehensive header implementation
  - X-Content-Type-Options: nosniff
  - X-Frame-Options: DENY (clickjacking protection)
  - X-XSS-Protection: 1; mode=block
  - Strict-Transport-Security (HTTPS only in production)
  - Content-Security-Policy

### Added
- **Database Indexes** - Performance optimization for frequently queried columns
  - Container indexes: policy, update_available, name
  - Update indexes: status, container_id, created_at, snoozed_until
  - UpdateHistory indexes: container_id, status, created_at, started_at
  - Migration 019 adds all indexes on startup
- **Retry Logic** - Exponential backoff for network failures
  - Decorator utilities for async and sync functions
  - Configurable max attempts, backoff base, and exceptions
  - Applied to registry HTTP requests
- **Test Suite** - pytest configuration and initial tests
  - Validator tests for command injection prevention
  - Retry logic tests for exponential backoff
  - API endpoint tests (partial coverage)
  - Test database isolation with in-memory SQLite

### Fixed
- **CRITICAL: Missing Dependency** - Added `itsdangerous>=2.1.0`
  - Required by SessionMiddleware but not in dependencies
  - Application crashed on startup without it
- **Migration 019 Signature** - Fixed function signature mismatch
  - Migration runner expects `upgrade()` without parameters
  - Migration had `upgrade(conn: AsyncConnection)` which failed
  - Now matches existing migration pattern
- **Test Suite Database Path** - Fixed permission errors in tests
  - Tests tried to create `/data` directory on import
  - Now sets DATABASE_URL environment variable before importing
  - Uses in-memory SQLite for test isolation
- **Test Import Errors** - Fixed incorrect retry API usage
  - test_retry.py used non-existent `with_retry` and `RetryConfig`
  - Updated to use actual `async_retry` decorator API

### Changed
- **CORS Configuration** - Fixed security issues
  - Wildcard origins now properly disable credentials
  - Explicit method whitelist (no wildcards)
  - Explicit header whitelist
  - Exposes rate limit headers to frontend
  - Configurable via CORS_ORIGINS environment variable
- **Database Connection Pooling** - Optimized for SQLite
  - StaticPool for single persistent connection
  - WAL mode enabled for concurrent read/write
  - 64MB cache size, 5-second busy timeout
- **Memory Leak Fixes** - Rate limiter bucket cleanup
  - Reduced cleanup threshold from 10 to 5 minutes
  - Hard limit of 10,000 buckets maximum
  - Aggressive cleanup when limit exceeded

### Dependencies
- Added: `itsdangerous>=2.1.0` (session signing)
- Dev: `pytest>=8.3.0`, `pytest-asyncio>=0.24.0`, `pytest-cov>=4.1.0`, `httpx>=0.27.2`

## [2.9.1] - 2025-11-24

### Fixed
- **Light Theme Visual Issues** - Resolved all remaining hardcoded colors and styling issues
  - Fixed CSRF token authentication errors in theme switching (ThemeContext now uses settingsApi)
  - Replaced 106+ instances of hardcoded gray colors with theme-aware variables across all pages
  - Fixed Flash of Unstyled Content (FOUC) by adding inline script to index.html
  - Fixed card spacing visibility in light mode (container background now uses `bg-tide-surface-light`)
  - Fixed black backgrounds on Dashboard, Updates, and History pages
  - Added borders to all Test Connection buttons in Settings page
  - Added border to Upload button in Backup & Maintenance section
  - Updated Statistics cards in About page with accurate line counts

### Changed
- **Navigation Header Text Size** - Increased font sizes for better readability
  - App title: `text-xl` → `text-2xl` (20px → 24px)
  - Desktop nav links: `text-sm` → `text-base` (14px → 16px) with 18px icons
  - Mobile nav links: `text-base` → `text-lg` (16px → 18px) with 20px icons
- **About Page Updates** - Updated project information
  - Changed author attribution from "Jamey (oaniach)" to "Operator"
  - Updated statistics to reflect current codebase:
    - Total Lines: ~16,700 → ~25,600
    - Python Backend: ~11,800 → ~17,300
    - TypeScript Frontend: ~4,900 → ~8,300

### Technical
- Systematic replacement of hardcoded Tailwind gray classes with CSS custom properties
  - `bg-gray-950` → `bg-tide-bg`, `bg-gray-700` → `bg-tide-surface`, etc.
- Theme variables properly adapt to both light and dark modes
- All UI components now consistently use semantic color names

## [2.9.0] - 2025-11-24

### Added
- **Light/Dark Theme Toggle** - NEW: Full light and dark theme support using Tailwind 4.1.x @theme feature
  - Theme toggle in Settings > System tab with Sun/Moon icons
  - Seamless theme switching with instant visual feedback
  - Persistent theme preference stored in database with cross-device sync
  - localStorage caching for instant theme loading (no FOUC)
  - Semantic CSS variables (`--color-tide-bg`, `--color-tide-surface`, `--color-tide-text`) for maintainability
  - All UI components support both themes:
    - Navigation bar, footer, cards, modals
    - Dashboard charts and analytics
    - Settings panels and forms
    - Update cards and history views
  - Dynamic Sonner toast theming
  - Scrollbar styling for both themes
  - Dark theme remains default for existing users
  - API: `GET/PUT /api/v1/settings/theme` for programmatic theme control

### Fixed
- **Migration System** - Fixed migrations directory structure to match MyGarage pattern
  - Moved migrations from `/backend/migrations/` to `/backend/app/migrations/`
  - Auto-migration system now working correctly on container startup
  - Migration 014 now handles duplicate update records before applying unique constraint

### Changed
- Updated frontend to version 2.9.0
- Updated backend to version 2.9.0

## [2.8.0] - 2025-11-24

### Added
- **HTTP Server Detection** - NEW: Automatically detect and track HTTP servers running in containers
  - Detects popular web servers: nginx, Apache, Caddy, Traefik, Granian, uvicorn, gunicorn, Node.js, and more
  - Version detection via command execution (e.g., `nginx -v`, `granian --version`)
  - Process-based detection with fallback to `/proc` for minimal containers without `ps`
  - Checks for latest versions from GitHub API (Caddy, Traefik, Granian)
  - Update availability tracking with severity indicators
  - New HTTP Servers section in Dependencies tab with stats and server cards
  - API endpoints:
    - `GET /api/v1/containers/{id}/http-servers` - Get detected servers
    - `POST /api/v1/containers/{id}/http-servers/scan` - Scan for servers
  - Auto-scans when Dependencies tab is opened
- **Dockerfile Dependency Tracking** - COMPLETE: Full end-to-end tracking of Dockerfile base images and build dependencies
  - **Backend (Phase 1)** ✅:
    - Automatically parse Dockerfiles to detect `FROM` statements
    - Track base images (e.g., `node:22-alpine`, `python:3.14-slim`) as dependencies
    - Support for multi-stage builds with stage name tracking
    - Update Detection: Check Docker registries for newer base image versions
    - Bulk Update Checking: Scan all tracked Dockerfile dependencies for updates
    - New database table: `dockerfile_dependencies` with migration
    - New API endpoints:
      - `GET /api/v1/containers/{id}/dockerfile-dependencies` - Get dependencies
      - `POST /api/v1/containers/{id}/dockerfile-dependencies/scan` - Scan Dockerfile
      - `POST /api/v1/dockerfile-dependencies/check-updates` - Check all for updates
    - Backend service: `DockerfileParser` with full update detection support
    - Integrates with existing `RegistryClient` for checking Docker Hub, GHCR, LSCR, GCR, Quay
  - **Frontend UI (Phase 2)** ✅:
    - New Dockerfile Dependencies section in Container Modal Dependencies tab
    - Visual display of base images and build images with update indicators
    - Statistics cards showing total images and available updates
    - "Scan Dockerfile" button for manual triggering
    - Dependency cards showing:
      - Image name, current tag, and latest tag
      - Dependency type (Base Image / Build Image)
      - Stage name for multi-stage builds
      - Dockerfile path and line number reference
      - Update availability badges (Update Available / Up to date)
    - Loading states and empty states with helpful messages
    - Settings page configuration:
      - Auto-Scan Dockerfiles toggle
      - Update check schedule (Disabled / Daily / Weekly)
      - Info box with feature explanation
  - **Automation (Phase 3)** ✅:
    - Auto-scan Dockerfiles when containers are added via project scanner
    - Scheduled update checks (daily at 3 AM or weekly on Sundays)
    - ntfy notifications for Dockerfile dependency updates
    - Configurable via Settings page
    - Respects `dockerfile_auto_scan` and `dockerfile_scan_schedule` settings
  - 🎯 **Solves**: Why Tidewatch didn't notify about Node.js update (now tracks Docker base images!)
- **Automatic Database Migrations** - NEW: Self-managing migration system for zero-downtime upgrades
  - Automatic migration discovery and execution on startup
  - Tracks applied migrations in `schema_migrations` table
  - Prevents re-running already-applied migrations (idempotent)
  - Runs migrations in chronological order (001, 002, etc.)
  - Graceful error handling (logs errors but doesn't fail startup)
  - Same battle-tested system as MyGarage
  - **Files Created:**
    - `app/migrations/runner.py` - Migration orchestration engine
    - `app/migrations/__init__.py` - Python package structure
  - **Files Modified:**
    - `app/db.py` - Integrated migration runner into startup sequence
  - **Benefits:**
    - No manual migration commands needed
    - Safe upgrades with automatic rollback on failure
    - Docker-friendly (just restart container to apply migrations)
    - Development-friendly (drop `.py` migration files, they auto-run)
- **ESLint Flat Configuration** - Added ESLint 9.x flat config for frontend linting
  - Created `eslint.config.js` using modern flat config format
  - Installed `globals` and `typescript-eslint` packages
  - Configured TypeScript, React, and React Hooks rules
  - Simplified lint script in package.json: `eslint .`

### Changed
- **Dependencies Tab UI Layout** - Improved layout with two-column masonry design
  - Left column: HTTP Servers + Dockerfile Dependencies
  - Right column: Application Dependencies
  - Reduces wasted vertical space and improves information density
  - Responsive grid that stacks on mobile devices
- **Application Dependencies Filter** - Changed default filter from "All" to "Updates"
  - Shows packages with available updates by default for quicker action
  - Users can still switch to "All" or "Security" filters as needed
- **Dockerfile Dependencies Auto-Scan** - Removed manual "Scan Dockerfile" button
  - Auto-scans when Dependencies tab is opened (consistent with HTTP Servers and App Dependencies)
  - Cleaner UI with one less button
- **Node.js Build Environment** - Updated frontend build to use Node.js 22 (from Node.js 20)
  - Updated Dockerfile: `FROM node:22-alpine` (was `node:20-alpine`)
  - Required for @vitejs/plugin-react 5.x compatibility (needs Node 20.19+ or 22.12+)
- **Frontend Dependencies** - Updated 8 npm packages to latest versions
  - @vitejs/plugin-react: 4.7.0 → 5.1.1 (major update with Oxc integration for faster builds)
  - recharts: 3.4.1 → 3.5.0 (performance improvements for chart rendering)
  - vite: 7.2.2 → 7.2.4 (bug fixes)
  - lucide-react: 0.553.0 → 0.554.0 (new icons)
  - @types/react: 19.2.2 → 19.2.6 (type definition updates)
  - @types/react-dom: 19.2.2 → 19.2.3 (type definition updates)
  - @typescript-eslint/eslint-plugin: 8.46.4 → 8.47.0 (new linting rules)
  - @typescript-eslint/parser: 8.46.4 → 8.47.0 (parser improvements)
  - Kept eslint-plugin-react-hooks at 7.0.0 (7.0.1 has known regression bugs)
  - Added globals: ^16.5.0 and typescript-eslint: ^8.47.0 for ESLint 9.x support

### Fixed
- **Vite Build Configuration** - Removed obsolete `react-hot-toast` reference from vite.config.ts
  - Application uses `sonner` for notifications; `react-hot-toast` was legacy reference
  - Fixes build error: "Could not resolve entry module 'react-hot-toast'"
- **ESLint Configuration Missing** - Resolved ESLint 9.x compatibility issue
  - ESLint 9.x requires flat config format (eslint.config.js)
  - Created proper flat config with all necessary plugins and rules
  - `npm run lint` now works correctly (reveals 56 pre-existing linting issues to be fixed separately)
- **Dockerfile Dependencies API Errors** - Fixed missing imports preventing application startup
  - Added missing `DockerfileDependenciesResponse` and `DockerfileDependencySchema` imports to `containers.py`
  - Added missing `Optional` type import for Dockerfile scan endpoint
  - Fixes `NameError: name 'schemas' is not defined` and `NameError: name 'Optional' is not defined`
  - Application now starts successfully with Dockerfile dependency tracking enabled

## [2.7.0] - 2025-11-22

### Added
- **My Projects Auto-Discovery** - Automatically detect dev containers from projects directory
  - New Settings card: "My Projects Configuration" with enable toggle, projects directory path, auto-scan toggle
  - Project scanner service automatically discovers containers from `/projects/*/compose.yaml` files
  - Intelligently identifies main dev container vs infrastructure services (postgres, redis, etc.)
  - Prefers services ending in `-dev` over other services in multi-service compose files
  - Manual "Scan Projects Now" button for on-demand scanning
  - Auto-detected containers automatically marked as "My Project" with `is_my_project = True`
  - Stale container cleanup: removes "My Project" entries whose compose files no longer exist
  - Scan results show added, updated, skipped, and removed container counts
  - Backend: `ProjectScanner` service with `scan_projects_directory()` and `remove_missing_projects()` methods
  - Frontend: "My Projects Configuration" card follows app theme (yellow star icon, gray-800 background, teal accents)
  - API endpoint: `POST /api/v1/containers/scan-my-projects` for manual project scanning
  - Settings: `my_projects_enabled`, `my_projects_auto_scan`, `my_projects_compose_command`, `projects_directory`
  - Volume mount: `/srv/raid0/docker/build:/projects:ro` for read-only access to project source code
  - Support for custom docker compose commands for dev containers (e.g., simple `docker compose` vs complex production stacks)

### Changed
- **UI Cleanup and Improvements**
  - Updated "My Project" toggle description to mention auto-detection: "Dev containers are auto-detected from your projects directory"
  - Moved "About Docker Settings" info box inside Docker Configuration card for better organization
  - Removed redundant "Scan Dependencies" button from Dependencies tab (auto-scan already works on tab open)
  - Updated Dependencies tab header to explain auto-scanning behavior
  - Improved empty state message in Dependencies tab with clearer explanation
- **Dependencies Tab Auto-Scanning** - Dependencies now scan automatically when tab is opened (no manual button needed)

### Fixed
- **Project Scanner Service Selection Logic** - Fixed scanner picking wrong services from multi-service compose files
  - Now correctly identifies main dev container instead of first service alphabetically
  - Skips infrastructure services (postgres, redis, mysql, mariadb, mongodb, rabbitmq, elasticsearch)
  - Prioritizes services/containers ending with `-dev` suffix
  - Falls back to first non-infrastructure service if no `-dev` service found
  - Example: `collectionsync/compose.yaml` now correctly finds `collectionsync-dev` instead of `postgres`
- **Stale Container Cleanup** - Scanner now removes containers that are no longer found in project scans
  - Tracks which containers were found during scan using a set
  - Deletes "My Project" containers not found in current scan
  - Prevents stale entries like `socket-proxy-dev` and `collectionsync-postgres` from lingering

### Technical
- Added database migration `015_add_is_my_project.py` to add `is_my_project` field
- Updated `Container` model and schemas to support `is_my_project` boolean field
- Project scanner uses `ruamel.yaml` for robust YAML parsing (already in dependencies)
- Scanner returns tuple `(result, container_name)` to track found containers
- Conditional UI rendering: My Project toggle only shows if `my_projects_enabled = true`
- Info boxes use consistent styling: `bg-gray-900/50 rounded-lg p-4` for tips sections

## [2.6.0] - 2025-11-21

### Added
- **My Projects Feature** - Mark containers as "My Project" to organize and track them separately
  - Added `is_my_project` boolean field to containers with database migration
  - Dashboard now splits containers into "My Projects" (top) and "Other Containers" sections
  - "My Project" toggle in Container Settings tab with star icon indicator
  - Only "My Projects" can access the new Dependencies tab
- **Application Dependencies Tracking** - Track and monitor application-level dependencies
  - New "Dependencies" tab in container modal (only visible for My Projects)
  - Multi-ecosystem support: npm (Node.js), PyPI (Python), Composer (PHP), Cargo (Rust), Go modules
  - Automatic dependency file detection (package.json, requirements.txt, composer.json, Cargo.toml, go.mod)
  - Real-time version checking against package registries
  - Displays current vs. latest versions with update availability
  - Security advisory tracking and severity indicators
  - Socket.dev security scoring integration (ready for future implementation)
  - Filterable view: All, Updates Available, Security Issues
  - Manual "Scan Dependencies" button with loading states
  - Stats cards showing Total, Updates Available, and Security Issues counts
  - Visual severity badges (Critical, High, Medium, Low, Info) based on semver differences
  - Ecosystem-specific icons (📦 npm, 🐍 PyPI, 🐘 Composer, 🦀 Cargo, 🐹 Go)
- **Backend Dependency Scanner Service** - Robust multi-ecosystem dependency detection
  - Automatic project root detection from compose file volume mounts
  - Parallel scanning across all supported ecosystems
  - Package registry API integration (npm, PyPI, Packagist, crates.io, Go proxy)
  - Version comparison and update availability calculation
  - Severity assessment based on semantic versioning differences
  - Configurable timeout and error handling for external API calls
- **New API Endpoints**
  - `GET /api/v1/containers/{id}/app-dependencies` - Get application dependencies with update info
  - `POST /api/v1/containers/{id}/app-dependencies/scan` - Force rescan of dependencies
  - Enhanced `PUT /api/v1/containers/{id}` to support `is_my_project` field
  - Permissions: Dependencies endpoints restricted to containers marked as My Projects

### Changed
- Updated frontend package version to 2.6.0
- Updated backend package version to 2.6.0
- Dashboard container grid now uses conditional rendering for grouped sections
- Container modal tabs conditionally show Dependencies tab based on `is_my_project` status

## [2.5.1] - 2025-11-18

### Security
- Fixed command injection vulnerability in container restart endpoint
- Added path traversal protection for compose file operations
- Fixed URL injection in health check authentication
- Added Docker tag format validation to prevent injection attacks
- Fixed ReDoS vulnerabilities in regex patterns with unbounded repetition

### Fixed
- Added error handling for resource cleanup to prevent connection leaks
- Fixed SQLite connection pool configuration causing database locks
- Fixed race condition in update creation with unique constraint and IntegrityError handling
- Improved error handling in frontend event stream with user notifications

### Changed
- Updated update checker to handle duplicate update creation gracefully
- Database connection pooling now adapts based on database type (SQLite vs PostgreSQL)
- Added comprehensive input validation for container names, file paths, and Docker tags

## [2.5.0] - 2025-11-17

### Added
- **Updates Tab Masonry Layout** - Converted Settings > Updates tab to responsive two-column masonry layout
  - Uses CSS `columns-1 xl:columns-2` for natural card flow (matching Container Settings pattern from v2.4.1)
  - Cards maintain natural widths and heights with `break-inside-avoid` property
  - Single column on mobile/tablet (<1280px), two columns on desktop (≥1280px)
  - All 5 settings cards flow naturally into columns based on content height
- **Scheduler Status Display** - Added real-time scheduler status card at top of Updates tab
  - Shows scheduler running state (● Running / ⏸ Paused) with color indicators
  - Displays next scheduled run time and last check time (relative times using `formatDistanceToNow`)
  - Auto-refreshes when Updates tab becomes active
  - Provides visibility into background update checking service
- **Auto-Reload Scheduler on Schedule Change** - Scheduler automatically reloads when cron schedule is updated
  - Detects changes to `check_schedule` setting in Settings > Updates
  - Calls `/api/v1/updates/scheduler/reload` endpoint after successful save
  - Displays success toast: "Scheduler reloaded with new schedule"
  - Immediately refreshes scheduler status display to show new next run time
- **Reset Settings to Defaults** - Added danger zone with reset button in Settings > System tab
  - Red-bordered section at bottom of System tab with warning styling
  - Confirmation dialog: "Reset ALL settings to defaults? Cannot be undone."
  - Calls `/api/v1/settings/reset` endpoint and reloads all settings after reset
  - Provides escape hatch for configuration issues
- **Settings Categories Organization (EXPERIMENTAL)** - Settings now grouped by category
  - Changed `loadSettings()` to try `/api/v1/settings/categories` endpoint first
  - Falls back to flat `/api/v1/settings/` list if categories endpoint fails
  - Graceful degradation for backwards compatibility
  - Note: Backend categories endpoint already existed, now integrated into frontend
- **Security Updates Filter** - Added dedicated filter for security-related updates on Updates page
  - New filter button with Shield icon: "Security (N)" showing count of CVE-related updates
  - Red background when active to highlight security-critical updates
  - Calls `/api/v1/updates/security` endpoint to fetch only updates with CVE fixes
  - Positioned above status filter tabs (All, Pending, Approved, etc.)
  - Shield icon provides visual indication of security-related updates

### Changed
- **Container Logs API Migration** - Migrated ContainerModal logs fetching from docker router to containers router
  - Changed `/api/v1/docker/containers/{id}/logs` → `api.containers.getLogs(id, tail)`
  - Uses existing containerApi endpoint for consistency
  - Properly handles log array formatting with `.join('\n')`

### Removed
- **Docker Router** - Removed unused `/api/v1/docker/` router from backend
  - Deleted `backend/app/api/docker.py` file (139 lines)
  - Removed docker router import and registration from `backend/app/api/__init__.py`
  - Only 1 frontend reference existed (ContainerModal logs), now migrated to containers API
  - Reduces API surface area and eliminates redundant container endpoints

## [2.4.7] - 2025-11-17

### Fixed
- **Cross-Distro Tag Suggestions** - Fixed variant tag filtering to preserve image variants (alpine vs debian/trixie)
  - Images like `python:3.12-alpine` now only suggest alpine-based updates (e.g., `3.12.12-alpine`)
  - Prevents cross-distribution suggestions that would break compatibility (e.g., suggesting `3.12.12-trixie` for `3.12-alpine`)
  - Updated all registry clients (DockerHub, GHCR, GenericRegistry, Quay) with suffix-matching logic
  - Closes issue from v2.4.5 where variant filtering was incomplete
- **Python-Style Pre-release Detection** - Added support for Python-style alpha/beta/rc tags
  - Added patterns `a0`-`a9`, `b0`-`b9`, `rc0`-`rc9` to prerelease indicators
  - Versions like `3.15.0a1`, `2.1.0b2` now correctly filtered as pre-releases
  - Applied across all registry clients (DockerHub, GHCR, LSCR, GCR, Quay)

### Added
- **Global Include Pre-releases Setting** - New toggle in Settings > Updates to control pre-release filtering
  - Users can now globally enable/disable pre-release versions (alpha, beta, rc, nightly)
  - Acts as default for containers that don't have per-container override
  - Located in "Update Checks" card where it logically belongs
  - Prevents confusion with "Exclude Dev Containers" (which only affects stale detection)

## [2.4.6] - 2025-11-17

### Fixed
- **Settings Key Mismatch** - Retry settings (Max Attempts, Backoff Multiplier) now properly applied to updates
  - Fixed frontend using wrong setting keys (`max_retry_attempts` vs `update_retry_max_attempts`)
  - Fixed backend never reading settings when creating Update objects
  - Update objects now use configured retry settings instead of hardcoded defaults (3 retries, 3x backoff)
- **No Manual Intervention for Retrying Updates** - Users can now control updates stuck in retry loops
  - Added "Cancel Retry" button to reset pending_retry updates back to pending state
  - Added "Reject" button to dismiss retrying updates permanently
  - Added "Delete" button as escape hatch to remove problematic updates
  - Fixed reject endpoint to accept both "pending" and "pending_retry" statuses
- **Retrying Updates Hidden in UI** - Added dedicated "Retrying" filter tab on Updates page
  - New filter shows only updates in pending_retry status
  - Shows retry count with rotating icon badge for easy identification
  - Displays next retry time in error messages

### Changed
- **Settings UI Improvement** - Converted retry settings to sliders matching app theme
  - Replaced number input fields with teal-colored range sliders
  - Shows current values in parentheses next to labels (e.g., "Max Attempts (5)")
  - Consistent with existing slider patterns in Container Modal

## [2.4.5] - 2025-11-16

### Fixed
- **Duplicate Update Entries** - Fixed deduplication query missing `from_tag` check
  - Added `Update.from_tag == container.current_tag` to deduplication query
  - Prevents multiple Update records for the same container+version combination
- **PR Tag Detection** - Pull request tags (e.g., `pr-4234`) no longer detected as valid updates
  - Added `'pr-'` and `'pull-'` to prerelease_indicators across all registry clients
  - Filters out development PR tags from update candidates
- **Latest Tag Detection** - "latest" tag no longer appears as update target for pinned versions
  - Added explicit "latest" tag filtering in both DockerHub and other registry clients
  - Prevents containers pinned to specific versions from showing "latest" as update
- **Variant Tag Filtering** - Image variant suffixes now automatically filtered (future-proof)
  - Replaced hardcoded suffix list with smart pattern matching
  - Automatically rejects ANY suffix that's not a standard pre-release (rc, beta, alpha)
  - Filters `-enterprise`, `-scratch`, `-cluster`, `-oss`, `-alpine`, `-slim`, etc.
  - No manual updates needed for new variant patterns introduced by upstream projects

## [2.4.4] - 2025-11-15

### Fixed
- **Rollback for Failed Updates** - Failed updates can now be rolled back if a backup exists
  - Backend now sets `can_rollback = True` for failed updates when backup is available
  - Removed frontend restriction requiring "success" status for rollback button visibility
  - Updated rollback API to accept both "success" and "failed" statuses
- **Pre-release Tag Filtering** - Tags containing "master" (e.g., `master-omnibus`) now correctly filtered as pre-releases
  - Added "master" to `prerelease_indicators` list in all registry clients
  - Prevents unwanted dev/master tag updates when "Include Prereleases" is disabled
- **Automatic Rollback After Max Retries** - Updates now automatically rollback after 3 failed retry attempts
  - When max retries reached, system attempts automatic rollback if backup exists
  - Update status set to "rolled_back" on successful auto-rollback
  - Provides clear error messages if auto-rollback fails or no backup available
- **Health Check Error Reporting** - Fixed misleading DNS errors masking actual container failures
  - Health check now reports actual container status (e.g., "Container exited") instead of HTTP/DNS errors
  - Docker inspect error messages now properly propagated when container has crashed
  - Separate tracking of HTTP errors vs container runtime errors for better debugging

## [2.4.3] - 2025-11-15

### Added
- **Rollback Option in Overview** - Added rollback card to container Overview tab after successful updates
  - Appears alongside "Up to Date" status in a split layout (50/50)
  - Shows previous version and timestamp with yellow accent border
  - Uses existing rollback functionality from History tab

### Fixed
- **Duplicate Update Cards** - Fixed issue where failed updates would create duplicate cards during retry attempts
  - Updated deduplication query in `UpdateChecker` to include `pending_retry` and `approved` statuses
  - Prevents new update records from being created when updates are already in retry or approved state
- **Unknown Status Display** - Fixed `pending_retry` status showing as "Unknown Update" in the UI
  - Added `pending_retry` status support to `StatusBadge` component with orange styling
  - Status now displays correctly as "pending_retry" instead of generic unknown state
- **Updates Page Clutter** - Applied updates now hidden from "All" tab to reduce clutter
  - Applied updates remain accessible via the "Applied" filter tab
- **History Status Colors** - Replaced inline status rendering with StatusBadge component for consistent colors
  - Ensures both 'completed' and 'success' statuses display green in container history
  - Added 'rolled_back' status with yellow color for consistency
- **About Page Version Display** - Fixed version showing "1.0.0" instead of actual version (2.4.3)
  - Improved default state to show "Loading..." while fetching version from API

### Changed
- **Success Status Styling** - Success status badges now display in green for better visual feedback
  - Changed success status color from gray to green (`bg-green-500/20 text-green-400 border-green-500/30`)
  - Provides clear visual distinction between successful and failed operations

## [2.4.2] - 2025-11-14

### Fixed
- **Docker Restart Policy Display** - Fixed inaccurate restart policy showing "manual" for all containers
  - Added `get_restart_policy()` method to `DockerStatsService` to read from Docker runtime
  - Added `_sync_restart_policies()` to `ComposeParser` to sync policies during container discovery
  - Now correctly displays actual Docker restart policy (no, on-failure, always, unless-stopped)
  - Syncs on every container sync operation

### Added
- **TideWatch Auto-Restart Badge** - Visual indicator for intelligent auto-restart feature
  - Added teal badge with RefreshCw icon to container cards when auto-restart is enabled
  - Displays alongside Docker restart policy for clear differentiation
  - Shows "Docker: {policy}" for native Docker restart + "Auto-Restart" badge for TideWatch feature
  - Helps users quickly identify which containers have intelligent restart management enabled

### Changed
- **Container Card Restart Info** - Improved clarity between Docker and TideWatch restart features
  - Renamed label from "Restart:" to "Docker:" to clarify it's the Docker native restart policy
  - Layout now shows both Docker policy (left) and TideWatch badge (right) when both are present
  - Bottom section only appears if at least one restart feature is configured

## [2.4.1] - 2025-11-14

### Fixed
- **Auto-Restart Disable Bug** - Fixed SQLAlchemy async session error when disabling auto-restart
  - Added missing `await db.refresh(state)` after commit in disable endpoint
  - Error was: `MissingGreenlet: greenlet_spawn has not been called` during Pydantic validation
  - All other endpoints (enable, reset, pause, resume) already had proper refresh logic

### Changed
- **Auto-Restart Slider Styling** - Updated configuration slider colors to teal (`accent-teal-500`)
  - Applied to Max Attempts, Base Delay, Max Delay, and Success Window sliders
- **Settings Tab Layout** - Converted to responsive CSS columns (masonry-style) layout
  - Uses `columns-1 xl:columns-2` for natural card flow across columns
  - Cards maintain their natural widths and heights with `break-inside-avoid`
  - Single column on mobile/tablet (< 1280px), two columns on desktop (≥ 1280px)
  - Cards stack naturally in columns without forced equal widths
  - All five settings sections (Auto-Restart, Health Check, Release Source, Dependency Management, Update Window) flow into columns based on available space

## [2.4.0] - 2025-11-13

### Added
- **Real-time Event Streaming** - Server-Sent Events (SSE) for live update notifications
  - EventSource-based SSE client with automatic reconnection and exponential backoff
  - Toast notifications for update available, update applied, update failed, container restarted, health check failed
  - Connection status indicator (Live/Reconnecting/Offline) in bottom-right corner
  - Graceful cleanup and heartbeat ping support
  - Created `useEventStream` hook for centralized event handling

- **Enhanced Log Viewer** - Powerful log analysis and management features
  - Search/filter functionality with case-insensitive text matching
  - Log level syntax highlighting (ERROR in red, WARN in yellow, INFO in blue, DEBUG in gray)
  - Copy to clipboard button for selected/filtered logs
  - Download logs as .txt file with timestamp
  - Follow mode toggle for auto-scrolling to latest logs
  - Adjustable tail lines selector (100, 500, 1000, All)
  - Visual feedback for filtered results

- **Better Backup Management UI** - Enhanced backup safety and information display
  - File size display with both bytes and MB formatting
  - Relative timestamps ("2 hours ago") with full datetime on hover
  - Safety backup visual indicators (Shield icon, protected badge)
  - Delete confirmation modal with backup details (filename, size, date)
  - Restore preview modal showing backup size vs current database size
  - Safety backup protection (automatic creation before restore, cannot delete)
  - Improved UX with detailed warning messages

- **Metrics History Improvements** - Advanced metrics visualization and export
  - CSV export functionality with timestamp and all metric columns
  - Multi-metric comparison mode for CPU + Memory (dual Y-axes)
  - Better axis labels with units (%, MB, MB/s)
  - Export button with data validation
  - Comparison toggle for correlating CPU and Memory usage
  - Enhanced chart tooltips and formatting

### Changed
- **Migrated toast library** from react-hot-toast to sonner for consistency
  - Unified toast notifications across all pages
  - Removed react-hot-toast dependency
  - Updated ContainerModal to use sonner
  - Improved toast styling with dark theme integration

- **Improved UI/UX polish** across multiple components
  - Better visual hierarchy with consistent spacing
  - Enhanced button groups and action controls
  - Improved modal designs with semantic color coding
  - Better mobile responsiveness for backup and log viewer

### Removed
- react-hot-toast dependency (replaced with sonner)

## [2.3.0] - 2025-11-13

### Added
- **Intelligent Auto-Restart Configuration UI** - Complete frontend interface for container restart management
  - Real-time restart state display (consecutive failures, total restarts, current backoff, max retries status)
  - Comprehensive configuration panel with backoff strategy selection (exponential/linear/fixed)
  - Configurable max attempts, base delay, max delay, and success window sliders
  - Health check integration with timeout configuration
  - Rollback on health fail toggle
  - Pause/Resume controls with duration selector
  - Reset state button to clear failure counters
  - Visual indicators for paused state and retry limits

- **Dependency Management UI** - Control container update order based on dependencies
  - Add/remove container dependencies with visual tags
  - Automatic bidirectional dependency tracking (dependencies ↔ dependents)
  - Select from all available containers to set as dependencies
  - Read-only display of containers that depend on this container
  - Circular dependency prevention via backend validation

- **Update Window Scheduling UI** - Restrict updates to specific time periods
  - Configure time-based update windows with format validation
  - Quick preset buttons for common scenarios:
    - Night Window (02:00-06:00 daily)
    - Weekends Only (Sat,Sun:00:00-23:59)
    - Weeknights (Mon-Fri:22:00-06:00)
    - Weekend Mornings (Sat,Sun:02:00-10:00)
  - Support for day-specific windows (Mon-Fri, Sat,Sun, etc.)
  - Support for windows that cross midnight
  - Clear button to remove restrictions
  - Format help with examples

- **New API Service Methods** - Frontend API client expanded with:
  - Complete restart API integration (getState, enable, disable, reset, pause, resume, getHistory, manualRestart, getStats)
  - Dependency management endpoints (getDependencies, updateDependencies)
  - Update window endpoints (getUpdateWindow, updateUpdateWindow)
  - Auto-detection endpoints (detectHealthCheck, detectReleaseSource)

- **TypeScript Type Definitions** - Added comprehensive types for:
  - RestartState, EnableRestartConfig, RestartLog, RestartStats
  - DependencyInfo
  - UpdateWindowInfo
  - AnalyticsSummary
  - ServerEvent for future event streaming

### Changed
- Updated Auto-Restart toggle to properly integrate with backend API
  - Now calls `/restarts/{id}/enable` and `/restarts/{id}/disable` endpoints
  - Saves complete configuration when enabling
  - Shows expanded configuration panel when enabled
- Enhanced ContainerModal with new Settings tab sections
  - Auto-Restart section expanded with state display and configuration
  - Added Dependency Management section after Release Source
  - Added Update Window section after Dependency Management
- Improved visual consistency across all new sections
  - Consistent dark theme (bg-gray-700/50, bg-gray-800, border-gray-600)
  - Primary color accents for interactive elements
  - Icon badges for section headers (RotateCw, Network, Calendar)

### Fixed
- Fixed duplicate "Release Source" field in Settings tab
  - Removed older "Release Notes Source" section (lines 1048-1078)
  - Kept newer "Release Source" section with auto-fill button
- Fixed Python package discovery issue in pyproject.toml
  - Added `[tool.setuptools.packages.find]` configuration
  - Explicitly includes `app*` packages

## [2.2.1] - 2025-11-12

- **CRITICAL:** Added input validation for container names to prevent command injection in subprocess calls
  - Validates against Docker naming constraints (`^[a-zA-Z0-9][a-zA-Z0-9_.-]*$`)
  - Applied to `ComposeParser`, `UpdateEngine`, and `ContainerMonitorService`
- **Added CSRF protection** using Double Submit Cookie pattern
  - Backend middleware validates CSRF tokens on POST, PUT, DELETE, PATCH requests
  - Frontend automatically includes CSRF token in all unsafe requests
  - Exempt paths: `/health`, `/metrics`, `/docs`, `/redoc`, `/openapi.json`
  - Configurable secure cookie flag for production environments
- **Added API rate limiting** (60 requests/minute per IP)
  - Token bucket algorithm with automatic refill
  - Exempt paths for health checks and metrics
  - Returns HTTP 429 with Retry-After header when exceeded
  - Includes X-RateLimit-Limit and X-RateLimit-Remaining headers
- **Added container label sanitization**
  - Maximum 100 labels per container (DoS prevention)
  - Key length limit: 255 characters (Docker standard)
  - Value length limit: 4,096 characters
  - Control character filtering and null byte removal
  - Applied to both container sync and health check extraction
- Added sensitive settings masking in API responses
  - Credentials (DockerHub token, GHCR token, VulnForge password, ntfy API key) now masked in GET endpoints
  - Shows first/last characters with asterisks in middle (e.g., `ghp_****abcd`)
- Added rollback safety validation
  - Prevents rollback of failed updates
  - Verifies container is at expected version before rollback
  - Prevents double rollback

### Fixed
- **CRITICAL:** Fixed event bus race condition causing runtime errors
  - Added list copy in publish method to prevent modification during iteration
  - Added proper logging for slow consumer removal
- **Fixed HTTPS mixed content errors** when running behind Traefik with Authentik forward auth
  - Added trailing slashes to frontend API calls (`/containers/`, `/updates/`, `/history/`)
  - Prevents FastAPI 307 redirects that were downgrading HTTPS to HTTP
  - Resolves browser blocking of HTTP resources on HTTPS pages
- Fixed HTTP client resource leaks
  - Added `__aenter__`/`__aexit__` context managers to RegistryClient, VulnForgeClient, and NtfyService
  - Ensures proper cleanup of HTTP connections
- Fixed Dashboard N+1 query problem
  - Replaced O(n*m) `.some()` calls with O(1) Map lookup
  - Improves performance with large container counts
- Fixed unsafe UTC datetime usage (Python 3.12+ deprecation)
  - Replaced `datetime.utcnow()` with `datetime.now(timezone.utc)` across codebase
- Fixed missing HTTP client timeout in health check requests
- Fixed useEffect dependency ordering in Dashboard component

### Performance
- **Added registry tag caching** (15-minute TTL)
  - In-memory cache for all registry clients (DockerHub, GHCR, LSCR, GCR, Quay)
  - Reduces redundant API calls by up to 90%
  - Automatic expiration and cleanup
  - Cache hit/miss logging for debugging
- **Added dependency resolution caching**
  - MD5-based cache keys for topological sort results
  - 100-entry LRU eviction policy
  - Automatic cache invalidation when dependencies change
  - Significantly improves bulk update ordering performance
- **Migrated Docker CLI to SDK in ContainerMonitorService**
  - Replaced subprocess `docker inspect` calls with Docker Python SDK
  - Better error handling and performance
  - Eliminates shell overhead
- Added database connection pooling
  - pool_size: 10 concurrent connections
  - max_overflow: 20 additional connections during peak load
  - pool_recycle: 3600 seconds (1 hour)
  - pool_pre_ping: enabled for connection health checks
- Added database indexes to frequently queried columns
  - Container: `update_available`, `policy`, `last_checked`
  - Update: `status`
  - UpdateHistory: `status`, `started_at`, `created_at`
  - Improves query performance for dashboard and filtering operations

### Added
- **Prometheus metrics endpoint** at `/metrics`
  - Container metrics: total, with updates, by policy, by registry
  - Update metrics: pending, approved, rejected, applied, failed
  - History metrics: success, failed, rolled back
  - Compatible with standard Prometheus scrapers
  - Automatically collects current state from database
- **Configurable timing values** for health checks and restarts
  - `health_check_retry_delay`: Initial delay between health check retries (default: 5s)
  - `health_check_use_exponential_backoff`: Enable exponential backoff (default: true)
  - `health_check_max_delay`: Maximum delay for exponential backoff (default: 30s)
  - `container_startup_delay`: Wait time after container restart before health check (default: 2s)
- **Exponential backoff for health checks**
  - Implements 5s → 10s → 20s → 30s backoff pattern
  - Reduces load on failing services during health check retries
  - Applied to both HTTP exceptions and non-200 status codes
  - Configurable via settings (can be disabled for fixed delay)
- **Frontend code splitting for large components**
  - Lazy-loaded ContainerModal component (1204 lines, ~40KB)
  - Modal only loads when opened, reducing initial bundle size
  - Added Suspense boundary with loading spinner
- **Container health status** in container details API
  - Real-time health check using ContainerMonitorService
  - Returns status: "healthy", "unhealthy", or "stopped"
  - Includes last health check timestamp

### Improved
- **Type hints coverage** - Added return type hints to 15+ functions
  - All `__init__` methods now have `-> None` return type
  - Async context managers (`__aenter__`, `__aexit__`) have proper typing
  - Utility and service methods include return type annotations
  - Improves IDE autocomplete and static analysis

## [2.2.0] - 2025-11-12

### Changed
- **MAJOR:** Migrated from Tailwind CSS v3 to v4
  - Updated PostCSS configuration to use `@tailwindcss/postcss` plugin
  - Migrated CSS imports from `@tailwind` directives to `@import "tailwindcss"`
  - Moved configuration from JavaScript to CSS-based `@theme` directive
  - Custom color theme (primary/accent) now defined as CSS custom properties
- Updated frontend dependencies:
  - `react-router-dom`: 7.3.1 → 7.9.6
  - `lucide-react`: 0.468.0 → 0.553.0 (now includes 1,647 icons)
  - `sonner`: 1.7.0 → 2.0.7
  - `@typescript-eslint/*`: 8.46.3 → 8.46.4
  - `eslint-plugin-react-refresh`: 0.4.16 → 0.4.24
  - `autoprefixer`: 10.4.21 → 10.4.22
  - `postcss`: 8.4.42 → 8.5.6
- Removed `tailwind.config.js` (no longer needed in Tailwind v4)
- Improved build script by removing `tsc &&` prefix for faster builds

### Technical Notes
- Tailwind v4 requires modern browsers (Safari 16.4+, Chrome 111+, Firefox 128+)
- Theme colors are now CSS variables for better runtime flexibility

## [2.1.1] - 2025-11-12

### Changed
- **MAJOR:** Migrated from uvicorn to Granian ASGI server
  - Updated `Dockerfile` to use Granian with single worker configuration
  - Changed logger filter in `app/main.py` from `uvicorn.access` to `granian.access`
  - Granian provides ~15-20% memory reduction and better async handling
- Updated backend dependencies to latest stable versions:
  - `fastapi`: 0.115.0 → 0.121.2
  - `sqlalchemy`: 2.0.36 → 2.0.44 (improved async support)
  - `pydantic`: 2.9.0 → 2.12.0 (minor behavior changes in dataclass Field handling)
  - `apscheduler`: 3.10.4 → 3.11.1 (dependency cleanup)
  - `docker`: 7.0.0 → 7.1.0
- Updated frontend dependencies:
  - `typescript`: 5.7.4 → 5.9.3 (stable version)
  - `eslint-plugin-react-hooks`: 5.1.0 → 7.0.0 (⚠️ avoid 7.0.1 - broken resolution)

### Performance
- Reduced memory footprint with Granian's Rust-based architecture
- Better async request handling and backpressure management
- Auto-tuned thread configuration for optimal performance

### Technical Notes
- Single worker required due to stateful APScheduler service
- Granian is fully ASGI-compliant and a drop-in replacement for uvicorn

## [2.1.0] - 2025-11-11

### Added
- Initial stable release of TideWatch
- Intelligent Docker container update management
- Real-time container monitoring and update tracking
- Integration with VulnForge for security analysis
- Automated update scheduling with configurable policies
- Update history tracking and rollback capabilities
- Comprehensive web UI with dashboard and analytics

### Technical Stack
- Backend: Python 3.14, FastAPI, SQLAlchemy, APScheduler
- Frontend: React 19, TypeScript, Tailwind CSS
- Database: SQLite with async support (aiosqlite)
- Container Management: Docker SDK for Python

---

## Version History

- **2.2.1**: Security fixes + performance optimizations
- **2.2.0**: Tailwind v4 migration + dependency updates
- **2.1.1**: Granian migration + backend dependency updates
- **2.1.0**: Initial stable release
