"""Settings service for database-first configuration."""

import os
import logging
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import OperationalError
from app.models import Setting
from typing import Optional, Dict, Any
from app.utils.encryption import get_encryption_service, is_encryption_configured
from app.utils.security import sanitize_log_message

logger = logging.getLogger(__name__)


class SettingsService:
    """Manage application settings in database."""

    # Default settings with descriptions
    DEFAULTS: Dict[str, Dict[str, Any]] = {
        # System
        "timezone": {
            "value": os.getenv("TZ", "UTC"),
            "category": "system",
            "description": "System timezone for displaying times and scheduling tasks",
        },
        # Paths
        "compose_directory": {
            "value": "/compose",
            "category": "paths",
            "description": "Directory containing docker-compose files",
        },
        "projects_directory": {
            "value": "/projects",
            "category": "paths",
            "description": "Directory containing project source code for dependency scanning",
        },
        "my_projects_enabled": {
            "value": "true",
            "category": "paths",
            "description": "Enable My Projects feature for dev containers",
        },
        "my_projects_auto_scan": {
            "value": "true",
            "category": "paths",
            "description": "Auto-discover dev containers in projects directory",
        },
        "my_projects_compose_command": {
            "value": "docker compose",
            "category": "paths",
            "description": "Docker Compose command for My Projects (use {compose_file}, {service} placeholders)",
        },
        "docker_socket": {
            "value": os.getenv("DOCKER_HOST", "/var/run/docker.sock"),
            "category": "system",
            "description": "Docker socket path or DOCKER_HOST URL",
        },
        "docker_compose_command": {
            "value": "docker compose",
            "category": "paths",
            "description": "Docker compose command template. Use {compose_file}, {env_file}, {service} placeholders. Example: 'docker compose -p homelab -f {compose_file} --env-file {env_file}'",
        },
        # Update scheduling
        "check_enabled": {
            "value": "true",
            "category": "scheduling",
            "description": "Enable automatic background update checks",
        },
        "check_schedule": {
            "value": "0 */6 * * *",  # Every 6 hours
            "category": "scheduling",
            "description": "Cron expression for update checks",
        },
        "auto_update_enabled": {
            "value": "false",
            "category": "scheduling",
            "description": "Enable automatic updates (requires policy=auto)",
        },
        "auto_update_max_concurrent": {
            "value": "3",
            "category": "scheduling",
            "description": "Maximum number of updates to auto-apply per run (rate limiting)",
        },
        # Update reliability
        "update_retry_max_attempts": {
            "value": "3",
            "category": "updates",
            "description": "Maximum retry attempts for failed updates (0-10)",
        },
        "update_retry_backoff_multiplier": {
            "value": "3.0",
            "category": "updates",
            "description": "Exponential backoff multiplier for retry delays (1.0-10.0)",
        },
        "include_prereleases": {
            "value": "false",
            "category": "updates",
            "description": "Include pre-release versions (alpha, beta, rc, nightly, etc.) when checking for updates",
        },
        "default_update_window": {
            "value": "",
            "category": "updates",
            "description": "Default update window for new containers (e.g., 22:00-06:00 or Mon-Fri:02:00-06:00)",
        },
        "update_window_enforcement": {
            "value": "strict",
            "category": "updates",
            "description": "Update window enforcement (strict: block outside window, advisory: warn but allow)",
        },
        # Registry authentication
        "dockerhub_username": {
            "value": "",
            "category": "registries",
            "description": "Docker Hub username (optional, for higher rate limits)",
        },
        "dockerhub_token": {
            "value": "",
            "category": "registries",
            "description": "Docker Hub access token (optional, encrypted)",
            "encrypted": True,
        },
        "ghcr_username": {
            "value": "",
            "category": "registries",
            "description": "GitHub username for GHCR (optional)",
        },
        "ghcr_token": {
            "value": "",
            "category": "registries",
            "description": "GitHub Personal Access Token for GHCR (optional, encrypted)",
            "encrypted": True,
        },
        # VulnForge integration
        "vulnforge_url": {
            "value": "",
            "category": "integrations",
            "description": "VulnForge API URL (e.g., http://vulnforge:8787)",
        },
        "vulnforge_auth_type": {
            "value": "none",
            "category": "integrations",
            "description": "VulnForge auth type: none, api_key, or basic_auth",
        },
        "vulnforge_api_key": {
            "value": "",
            "category": "integrations",
            "description": "VulnForge API key for Bearer token auth (encrypted)",
            "encrypted": True,
        },
        "vulnforge_username": {
            "value": "",
            "category": "integrations",
            "description": "VulnForge username for basic auth (optional)",
        },
        "vulnforge_password": {
            "value": "",
            "category": "integrations",
            "description": "VulnForge password for basic auth (encrypted)",
            "encrypted": True,
        },
        "vulnforge_enabled": {
            "value": "false",
            "category": "integrations",
            "description": "Enable VulnForge integration",
        },
        # Notifications
        "ntfy_url": {
            "value": "",
            "category": "notifications",
            "description": "ntfy server URL (deprecated, migrate to ntfy_server)",
        },
        "ntfy_server": {
            "value": "",
            "category": "notifications",
            "description": "ntfy server URL",
        },
        "ntfy_topic": {
            "value": "tidewatch",
            "category": "notifications",
            "description": "ntfy topic name",
        },
        "ntfy_enabled": {
            "value": "false",
            "category": "notifications",
            "description": "Enable ntfy notifications",
        },
        "ntfy_token": {
            "value": "",
            "category": "notifications",
            "description": "ntfy API key for authentication (optional, encrypted)",
            "encrypted": True,
        },
        # Gotify
        "gotify_enabled": {
            "value": "false",
            "category": "notifications",
            "description": "Enable Gotify notifications",
        },
        "gotify_server": {
            "value": "",
            "category": "notifications",
            "description": "Gotify server URL",
        },
        "gotify_token": {
            "value": "",
            "category": "notifications",
            "description": "Gotify application token (encrypted)",
            "encrypted": True,
        },
        # Pushover
        "pushover_enabled": {
            "value": "false",
            "category": "notifications",
            "description": "Enable Pushover notifications",
        },
        "pushover_user_key": {
            "value": "",
            "category": "notifications",
            "description": "Pushover user key (encrypted)",
            "encrypted": True,
        },
        "pushover_api_token": {
            "value": "",
            "category": "notifications",
            "description": "Pushover API token (encrypted)",
            "encrypted": True,
        },
        # Slack
        "slack_enabled": {
            "value": "false",
            "category": "notifications",
            "description": "Enable Slack notifications",
        },
        "slack_webhook_url": {
            "value": "",
            "category": "notifications",
            "description": "Slack incoming webhook URL (encrypted)",
            "encrypted": True,
        },
        # Discord
        "discord_enabled": {
            "value": "false",
            "category": "notifications",
            "description": "Enable Discord notifications",
        },
        "discord_webhook_url": {
            "value": "",
            "category": "notifications",
            "description": "Discord webhook URL (encrypted)",
            "encrypted": True,
        },
        # Telegram
        "telegram_enabled": {
            "value": "false",
            "category": "notifications",
            "description": "Enable Telegram notifications",
        },
        "telegram_bot_token": {
            "value": "",
            "category": "notifications",
            "description": "Telegram bot token from @BotFather (encrypted)",
            "encrypted": True,
        },
        "telegram_chat_id": {
            "value": "",
            "category": "notifications",
            "description": "Telegram chat or channel ID",
        },
        # Email/SMTP
        "email_enabled": {
            "value": "false",
            "category": "notifications",
            "description": "Enable email notifications",
        },
        "email_smtp_host": {
            "value": "",
            "category": "notifications",
            "description": "SMTP server hostname",
        },
        "email_smtp_port": {
            "value": "587",
            "category": "notifications",
            "description": "SMTP server port",
        },
        "email_smtp_user": {
            "value": "",
            "category": "notifications",
            "description": "SMTP username",
        },
        "email_smtp_password": {
            "value": "",
            "category": "notifications",
            "description": "SMTP password (encrypted)",
            "encrypted": True,
        },
        "email_smtp_tls": {
            "value": "true",
            "category": "notifications",
            "description": "Use TLS/STARTTLS for SMTP",
        },
        "email_from": {
            "value": "",
            "category": "notifications",
            "description": "Sender email address",
        },
        "email_to": {
            "value": "",
            "category": "notifications",
            "description": "Recipient email address",
        },
        # Notification Retry Settings
        "notification_retry_attempts": {
            "value": "3",
            "category": "notifications",
            "description": "Number of retry attempts for high-priority notifications",
        },
        "notification_retry_delay": {
            "value": "2.0",
            "category": "notifications",
            "description": "Base delay in seconds between retry attempts",
        },
        # Notification Event Toggles
        "notify_updates_enabled": {
            "value": "true",
            "category": "notifications",
            "description": "Enable update notifications group",
        },
        "notify_updates_available": {
            "value": "true",
            "category": "notifications",
            "description": "Notify when updates are available",
        },
        "notify_updates_applied_success": {
            "value": "true",
            "category": "notifications",
            "description": "Notify when updates are successfully applied",
        },
        "notify_updates_applied_failed": {
            "value": "true",
            "category": "notifications",
            "description": "Notify when updates fail to apply",
        },
        "notify_updates_rollback": {
            "value": "false",
            "category": "notifications",
            "description": "Notify when updates are rolled back",
        },
        "notify_restarts_enabled": {
            "value": "false",
            "category": "notifications",
            "description": "Enable restart notifications group",
        },
        "notify_restarts_scheduled": {
            "value": "false",
            "category": "notifications",
            "description": "Notify when restarts are scheduled",
        },
        "notify_restarts_success": {
            "value": "false",
            "category": "notifications",
            "description": "Notify when containers successfully restart",
        },
        "notify_restarts_failure": {
            "value": "true",
            "category": "notifications",
            "description": "Notify when container restarts fail",
        },
        "notify_restarts_max_retries": {
            "value": "true",
            "category": "notifications",
            "description": "Notify when max restart retries reached",
        },
        "notify_system_enabled": {
            "value": "false",
            "category": "notifications",
            "description": "Enable system notifications group",
        },
        "notify_system_check_complete": {
            "value": "false",
            "category": "notifications",
            "description": "Notify when update checks complete",
        },
        "notify_system_dockerfile_updates": {
            "value": "false",
            "category": "notifications",
            "description": "Notify when Dockerfile dependency updates are available",
        },
        # Update policies (defaults)
        "default_policy": {
            "value": "manual",
            "category": "policies",
            "description": "Default update policy (auto, manual, disabled, security)",
        },
        "default_scope": {
            "value": "patch",
            "category": "policies",
            "description": "Default update scope (patch, minor, major)",
        },
        "max_vuln_threshold": {
            "value": "0",
            "category": "policies",
            "description": "Max acceptable vulnerabilities for auto-update",
        },
        # Stale container detection
        "stale_detection_enabled": {
            "value": "true",
            "category": "cleanup",
            "description": "Enable stale/inactive container detection",
        },
        "stale_detection_threshold_days": {
            "value": "30",
            "category": "cleanup",
            "description": "Mark containers as stale after X days of not being found in compose files",
        },
        "stale_detection_exclude_dev": {
            "value": "true",
            "category": "cleanup",
            "description": "Exclude dev containers (names ending in -dev) from stale detection",
        },
        # Docker cleanup
        "cleanup_old_images": {
            "value": "false",
            "category": "cleanup",
            "description": "Enable automatic Docker resource cleanup",
        },
        "cleanup_after_days": {
            "value": "7",
            "category": "cleanup",
            "description": "Days to keep old images before cleanup in aggressive mode",
        },
        "cleanup_containers": {
            "value": "true",
            "category": "cleanup",
            "description": "Also clean up exited containers during scheduled cleanup",
        },
        "cleanup_schedule": {
            "value": "0 4 * * *",
            "category": "cleanup",
            "description": "Cron schedule for automatic Docker cleanup (default: 4 AM daily)",
        },
        "cleanup_mode": {
            "value": "dangling",
            "category": "cleanup",
            "description": "Cleanup scope: 'dangling' (untagged only), 'moderate' (+ exited containers), 'aggressive' (+ old unused images)",
        },
        "cleanup_exclude_patterns": {
            "value": "-dev,rollback",
            "category": "cleanup",
            "description": "Comma-separated patterns to exclude from cleanup (containers/images matching these are preserved)",
        },
        # Security
        "cors_origins": {
            "value": os.getenv("CORS_ORIGINS", "*"),
            "category": "security",
            "description": "Comma-separated list of allowed CORS origins. Use * for all (not recommended in production). Example: http://localhost:3000,https://tidewatch.example.com",
        },
        # Intelligent Restart System
        "restart_monitor_enabled": {
            "value": "true",
            "category": "restart",
            "description": "Enable intelligent container restart monitoring",
        },
        "restart_monitor_interval": {
            "value": "30",
            "category": "restart",
            "description": "Container monitoring interval in seconds",
        },
        "restart_default_strategy": {
            "value": "exponential",
            "category": "restart",
            "description": "Default backoff strategy (exponential, linear, fixed)",
        },
        "restart_default_max_attempts": {
            "value": "10",
            "category": "restart",
            "description": "Default maximum restart attempts before giving up",
        },
        "restart_base_delay": {
            "value": "2",
            "category": "restart",
            "description": "Base delay in seconds for restart backoff",
        },
        "restart_max_delay": {
            "value": "300",
            "category": "restart",
            "description": "Maximum delay in seconds for restart backoff (5 minutes)",
        },
        "restart_success_window": {
            "value": "300",
            "category": "restart",
            "description": "Success window in seconds before resetting failure count (5 minutes)",
        },
        "restart_health_check_timeout": {
            "value": "60",
            "category": "restart",
            "description": "Health check timeout in seconds after restart",
        },
        "restart_concurrent_limit": {
            "value": "10",
            "category": "restart",
            "description": "Maximum number of concurrent restart operations",
        },
        "restart_notify_on_failure": {
            "value": "true",
            "category": "restart",
            "description": "Send notification when container fails to restart",
        },
        "restart_notify_on_max_retries": {
            "value": "true",
            "category": "restart",
            "description": "Send notification when max restart attempts reached",
        },
        "restart_notify_on_success": {
            "value": "false",
            "category": "restart",
            "description": "Send notification when container successfully restarts",
        },
        # Health check timing
        "health_check_retry_delay": {
            "value": "5",
            "category": "restart",
            "description": "Initial delay in seconds between health check retry attempts (base for exponential backoff)",
        },
        "health_check_use_exponential_backoff": {
            "value": "true",
            "category": "restart",
            "description": "Use exponential backoff for health check retries (doubles delay each attempt)",
        },
        "health_check_max_delay": {
            "value": "30",
            "category": "restart",
            "description": "Maximum delay in seconds for exponential backoff between health check retries",
        },
        "container_startup_delay": {
            "value": "2",
            "category": "restart",
            "description": "Delay in seconds to wait after restarting a container before health check",
        },
    }

    @staticmethod
    async def init_defaults(db: AsyncSession) -> None:
        """Initialize default settings if they don't exist."""
        # Migrate legacy keys created before update retry/window settings were finalized
        legacy_key_map = {
            "retry_max_attempts": "update_retry_max_attempts",
            "retry_backoff_multiplier": "update_retry_backoff_multiplier",
            "window_enforcement": "update_window_enforcement",
        }
        legacy_changes = False
        for legacy_key, new_key in legacy_key_map.items():
            legacy_result = await db.execute(select(Setting).where(Setting.key == legacy_key))
            legacy_setting = legacy_result.scalar_one_or_none()
            if not legacy_setting:
                continue

            new_result = await db.execute(select(Setting).where(Setting.key == new_key))
            new_setting = new_result.scalar_one_or_none()
            default_config = SettingsService.DEFAULTS.get(new_key, {})

            if new_setting:
                default_value = default_config.get("value")
                if default_value is not None and new_setting.value == default_value:
                    new_setting.value = legacy_setting.value
                await db.delete(legacy_setting)
            else:
                legacy_setting.key = new_key
                legacy_setting.category = default_config.get("category", legacy_setting.category)
                legacy_setting.description = default_config.get("description", legacy_setting.description)
                legacy_setting.encrypted = default_config.get("encrypted", legacy_setting.encrypted)
            legacy_changes = True

        if legacy_changes:
            await db.flush()

        for key, config in SettingsService.DEFAULTS.items():
            result = await db.execute(select(Setting).where(Setting.key == key))
            if not result.scalar_one_or_none():
                setting = Setting(
                    key=key,
                    value=config["value"],
                    category=config["category"],
                    description=config["description"],
                    encrypted=config.get("encrypted", False),
                )
                db.add(setting)

        await db.commit()

    @classmethod
    async def get(cls, db: AsyncSession, key: str, default: Optional[str] = None) -> Optional[str]:
        """Get setting value by key.

        Automatically decrypts encrypted settings if encryption is configured.

        Args:
            db: Database session
            key: Setting key
            default: Default value if setting not found

        Returns:
            Decrypted setting value or default
        """
        result = await db.execute(select(Setting).where(Setting.key == key))
        setting = result.scalar_one_or_none()

        if not setting:
            return default

        # If setting is marked as encrypted and encryption is configured, decrypt it
        if setting.encrypted and is_encryption_configured():
            try:
                encryption_service = get_encryption_service()
                decrypted_value = encryption_service.decrypt(setting.value)
                return decrypted_value
            except ValueError as e:
                logger.error(f"Failed to decrypt setting '{sanitize_log_message(str(key))}': {sanitize_log_message(str(e))}")
                logger.warning(f"Setting '{sanitize_log_message(str(key))}' is marked as encrypted but decryption failed. Returning None.")
                return None
            except Exception as e:
                logger.error(f"Unexpected error decrypting setting '{sanitize_log_message(str(key))}': {sanitize_log_message(str(e))}")
                return None

        return setting.value

    @staticmethod
    async def get_bool(db: AsyncSession, key: str, default: bool = False) -> bool:
        """Get setting as boolean."""
        value = await SettingsService.get(db, key)
        if value is None:
            return default
        return value.lower() in ("true", "1", "yes", "on")

    @staticmethod
    async def get_int(db: AsyncSession, key: str, default: int = 0) -> int:
        """Get setting as integer."""
        value = await SettingsService.get(db, key)
        if value is None:
            return default
        try:
            return int(value)
        except ValueError:
            return default

    @classmethod
    async def set(cls, db: AsyncSession, key: str, value: str) -> Setting:
        """Set setting value.

        Automatically encrypts sensitive settings if encryption is configured.

        Args:
            db: Database session
            key: Setting key
            value: Setting value (will be encrypted if marked as encrypted)

        Returns:
            Updated Setting object
        """
        result = await db.execute(select(Setting).where(Setting.key == key))
        setting = result.scalar_one_or_none()

        # Get config for metadata
        config = cls.DEFAULTS.get(key, {})
        is_encrypted = config.get("encrypted", False)

        # Encrypt value if needed
        value_to_store = value
        if is_encrypted and is_encryption_configured():
            try:
                encryption_service = get_encryption_service()
                value_to_store = encryption_service.encrypt(value)
                logger.debug(f"Encrypted setting '{sanitize_log_message(str(key))}' before storing")
            except Exception as e:
                logger.error(f"Failed to encrypt setting '{sanitize_log_message(str(key))}': {sanitize_log_message(str(e))}")
                # For security, don't store unencrypted value if encryption was expected
                raise ValueError(f"Failed to encrypt setting '{key}': {e}")
        elif is_encrypted and not is_encryption_configured():
            logger.warning(
                f"Setting '{key}' is marked as encrypted but TIDEWATCH_ENCRYPTION_KEY is not configured. "
                "Value will be stored in plain text. Configure encryption key in environment variables."
            )

        if setting:
            setting.value = value_to_store
            # Update encrypted flag if changed
            if is_encrypted != setting.encrypted:
                setting.encrypted = is_encrypted
        else:
            # Create new setting if it doesn't exist
            setting = Setting(
                key=key,
                value=value_to_store,
                category=config.get("category", "general"),
                description=config.get("description", ""),
                encrypted=is_encrypted,
            )
            db.add(setting)

        await db.commit()
        await db.refresh(setting)
        return setting

    @staticmethod
    async def get_all(db: AsyncSession, category: Optional[str] = None) -> list[Setting]:
        """Get all settings, optionally filtered by category."""
        query = select(Setting)
        if category:
            query = query.where(Setting.category == category)
        result = await db.execute(query.order_by(Setting.category, Setting.key))
        return list(result.scalars().all())

    @staticmethod
    async def get_by_category(db: AsyncSession) -> Dict[str, list[Setting]]:
        """Get all settings grouped by category."""
        all_settings = await SettingsService.get_all(db)
        grouped: Dict[str, list[Setting]] = {}
        for setting in all_settings:
            if setting.category not in grouped:
                grouped[setting.category] = []
            grouped[setting.category].append(setting)
        return grouped

    @staticmethod
    async def get_cors_origins(db: AsyncSession) -> list[str]:
        """Get CORS origins as a list."""
        origins = await SettingsService.get(db, "cors_origins", "*")
        if origins == "*":
            return ["*"]
        # Split by comma and strip whitespace
        return [origin.strip() for origin in origins.split(",") if origin.strip()]
