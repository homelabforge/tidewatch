"""Settings API endpoints."""

import logging

import docker
import httpx
from docker.errors import DockerException
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas import SettingCategory, SettingSchema, SettingUpdate
from app.services import SettingsService
from app.services.auth import require_auth
from app.utils.error_handling import safe_error_response

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/", response_model=list[SettingSchema])
async def get_all_settings(
    admin: dict | None = Depends(require_auth),
    category: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Get all settings, optionally filtered by category."""
    from app.schemas.setting import SENSITIVE_KEYS

    settings = await SettingsService.get_all(db, category)

    # Mask sensitive values in responses
    for setting in settings:
        if setting.key in SENSITIVE_KEYS and setting.value:
            if len(setting.value) > 12:
                setting.value = (
                    f"{setting.value[:4]}{'*' * (len(setting.value) - 8)}{setting.value[-4:]}"
                )
            elif len(setting.value) > 4:
                setting.value = f"{setting.value[:2]}{'*' * (len(setting.value) - 2)}"
            else:
                setting.value = "****"

    return settings


@router.get("/categories", response_model=list[SettingCategory])
async def get_settings_by_category(
    admin: dict | None = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
) -> list[SettingCategory]:
    """Get settings grouped by category."""
    from app.schemas.setting import SENSITIVE_KEYS

    grouped = await SettingsService.get_by_category(db)

    # Mask sensitive values in all categories
    for settings_list in grouped.values():
        for setting in settings_list:
            if setting.key in SENSITIVE_KEYS and setting.value:
                if len(setting.value) > 12:
                    setting.value = (
                        f"{setting.value[:4]}{'*' * (len(setting.value) - 8)}{setting.value[-4:]}"
                    )
                elif len(setting.value) > 4:
                    setting.value = f"{setting.value[:2]}{'*' * (len(setting.value) - 2)}"
                else:
                    setting.value = "****"

    return [SettingCategory(category=cat, settings=settings) for cat, settings in grouped.items()]


@router.get("/{key}", response_model=SettingSchema)
async def get_setting(
    key: str,
    admin: dict | None = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
) -> SettingSchema:
    """Get a specific setting by key."""
    from app.schemas.setting import SENSITIVE_KEYS

    value = await SettingsService.get(db, key)
    if value is None:
        raise HTTPException(status_code=404, detail=f"Setting '{key}' not found")

    # Fetch full setting object
    settings = await SettingsService.get_all(db)
    setting = next((s for s in settings if s.key == key), None)
    if not setting:
        raise HTTPException(status_code=404, detail=f"Setting '{key}' not found")

    # Mask sensitive value
    if setting.key in SENSITIVE_KEYS and setting.value:
        if len(setting.value) > 12:
            setting.value = (
                f"{setting.value[:4]}{'*' * (len(setting.value) - 8)}{setting.value[-4:]}"
            )
        elif len(setting.value) > 4:
            setting.value = f"{setting.value[:2]}{'*' * (len(setting.value) - 2)}"
        else:
            setting.value = "****"

    return setting


@router.put("/{key}", response_model=SettingSchema)
async def update_setting(
    key: str,
    update: SettingUpdate,
    admin: dict | None = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
) -> SettingSchema:
    """Update a setting value."""
    setting = await SettingsService.set(db, key, update.value)
    return setting


@router.post("/batch", response_model=list[SettingSchema])
async def batch_update_settings(
    updates: list[dict[str, str]],
    admin: dict | None = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
) -> list[SettingSchema]:
    """Update multiple settings atomically.

    Args:
        updates: List of setting updates with 'key' and 'value' fields

    Returns:
        List of updated settings

    Raises:
        HTTPException: If validation fails (400) or database error occurs (500)
    """
    try:
        # Validate all updates first
        for update in updates:
            if "key" not in update or "value" not in update:
                raise HTTPException(
                    status_code=400,
                    detail="Each update must have 'key' and 'value' fields",
                )

        # Apply all updates in transaction
        updated_settings = []
        for update in updates:
            setting = await SettingsService.set(db, update["key"], update["value"])
            updated_settings.append(setting)

        return updated_settings

    except HTTPException:
        raise
    except Exception as e:
        safe_error_response(logger, e, "Failed to batch update settings", status_code=500)


@router.post("/reset")
async def reset_to_defaults(
    admin: dict | None = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Reset all settings to defaults."""
    await SettingsService.init_defaults(db)
    return {"message": "Settings reset to defaults"}


@router.post("/test/docker")
async def test_docker_connection(
    admin: dict | None = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Test Docker socket/API connection.

    Returns:
        Connection test result with status and details
    """
    docker_socket = "unknown"
    try:
        docker_socket = await SettingsService.get(db, "docker_socket") or "unknown"

        # Determine docker host format
        if docker_socket.startswith(("tcp://", "unix://")):
            docker_host = docker_socket
        else:
            docker_host = f"unix://{docker_socket}"

        # Test connection using Docker SDK
        client = docker.DockerClient(base_url=docker_host, timeout=10)

        # Get version info
        version_info = client.version()
        version = version_info.get("Version", "unknown")
        api_version = version_info.get("ApiVersion", "unknown")

        # Get basic info to verify connection
        info = client.info()
        containers = info.get("Containers", 0)

        client.close()

        return {
            "success": True,
            "message": f"Connected to Docker Engine v{version}",
            "details": {
                "docker_host": docker_host,
                "version": version,
                "api_version": api_version,
                "containers": containers,
            },
        }
    except DockerException:
        return {
            "success": False,
            "message": "Failed to connect to Docker",
            "details": {"docker_host": docker_socket, "error": "An error occurred"},
        }
    except OperationalError:
        return {
            "success": False,
            "message": "Database error",
            "details": {"error": "An error occurred"},
        }
    except (ValueError, KeyError, AttributeError):
        return {
            "success": False,
            "message": "Invalid configuration",
            "details": {"error": "An error occurred"},
        }


@router.post("/test/vulnforge")
async def test_vulnforge_connection(
    admin: dict | None = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Test VulnForge API connection.

    Returns:
        Connection test result with status and details
    """
    vulnforge_url = "unknown"
    try:
        # Get VulnForge settings
        vulnforge_url = await SettingsService.get(db, "vulnforge_url")
        auth_type = await SettingsService.get(db, "vulnforge_auth_type")
        api_key = await SettingsService.get(db, "vulnforge_api_key")
        username = await SettingsService.get(db, "vulnforge_username")
        password = await SettingsService.get(db, "vulnforge_password")

        if not vulnforge_url:
            return {
                "success": False,
                "message": "VulnForge URL not configured",
                "details": {},
            }

        # Build auth headers based on configured type
        headers = {}
        if auth_type == "api_key" and api_key:
            # VulnForge uses X-API-Key header for API key authentication
            headers["X-API-Key"] = api_key
        elif auth_type == "basic_auth" and username and password:
            import base64

            credentials = f"{username}:{password}"
            encoded = base64.b64encode(credentials.encode()).decode()
            headers["Authorization"] = f"Basic {encoded}"
        # auth_type == "none" requires no headers

        # Test connection with health endpoint
        base_url = vulnforge_url.rstrip("/")
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{base_url}/health", headers=headers)
            response.raise_for_status()

            # Try to get container count from API
            container_count = "N/A"
            try:
                containers_response = await client.get(
                    f"{base_url}/api/v1/containers/", headers=headers
                )
                if containers_response.status_code == 200:
                    data = containers_response.json()
                    container_count = data.get("total", len(data.get("containers", [])))
            except Exception:
                # Containers endpoint might be protected or unavailable
                pass

            auth_status = "none"
            if auth_type == "api_key" and api_key:
                auth_status = "api_key (Bearer)"
            elif auth_type == "basic_auth" and username:
                auth_status = "basic_auth"

            return {
                "success": True,
                "message": "Connected to VulnForge successfully",
                "details": {
                    "url": base_url,
                    "auth_type": auth_status,
                    "containers": container_count,
                },
            }
    except httpx.HTTPStatusError as e:
        return {
            "success": False,
            "message": f"VulnForge API error: {e.response.status_code}",
            "details": {
                "url": vulnforge_url,
                "status_code": e.response.status_code,
                "error": "An error occurred",
            },
        }
    except httpx.ConnectError:
        return {
            "success": False,
            "message": "Cannot connect to VulnForge",
            "details": {
                "url": vulnforge_url,
                "error": "Connection refused or host unreachable",
            },
        }
    except httpx.TimeoutException:
        return {
            "success": False,
            "message": "VulnForge connection timeout",
            "details": {"error": "An error occurred"},
        }
    except OperationalError:
        return {
            "success": False,
            "message": "Database error",
            "details": {"error": "An error occurred"},
        }
    except (ValueError, KeyError):
        return {
            "success": False,
            "message": "Invalid configuration or response",
            "details": {"error": "An error occurred"},
        }


@router.post("/test/ntfy")
async def test_ntfy_connection(
    admin: dict | None = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Test ntfy server connection.

    Returns:
        Connection test result with status and details
    """
    ntfy_server = "unknown"
    ntfy_topic = "unknown"
    try:
        # Get ntfy settings
        ntfy_enabled = await SettingsService.get_bool(db, "ntfy_enabled")
        ntfy_server = await SettingsService.get(db, "ntfy_server") or await SettingsService.get(
            db, "ntfy_url"
        )
        ntfy_topic = await SettingsService.get(db, "ntfy_topic")

        if not ntfy_enabled:
            return {
                "success": False,
                "message": "ntfy notifications are disabled",
                "details": {"enabled": False},
            }

        if not ntfy_server or not ntfy_topic:
            return {
                "success": False,
                "message": "ntfy server or topic not configured",
                "details": {
                    "server_configured": bool(ntfy_server),
                    "topic_configured": bool(ntfy_topic),
                },
            }

        # Send test notification
        server_url = ntfy_server.rstrip("/")
        url = f"{server_url}/{ntfy_topic}"

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                url,
                content="TideWatch connection test - If you see this, notifications are working! 🌊",
                headers={
                    "Title": "TideWatch: Connection Test",
                    "Priority": "default",
                    "Tags": "white_check_mark,ocean",
                },
            )
            response.raise_for_status()

            return {
                "success": True,
                "message": "Test notification sent successfully",
                "details": {
                    "server": server_url,
                    "topic": ntfy_topic,
                    "message": "Check your ntfy client for the test notification",
                },
            }
    except httpx.HTTPStatusError as e:
        return {
            "success": False,
            "message": f"ntfy API error: {e.response.status_code}",
            "details": {
                "server": ntfy_server,
                "topic": ntfy_topic,
                "status_code": e.response.status_code,
                "error": "An error occurred",
            },
        }
    except httpx.ConnectError:
        return {
            "success": False,
            "message": "Cannot connect to ntfy server",
            "details": {
                "server": ntfy_server,
                "error": "Connection refused or host unreachable",
            },
        }
    except httpx.TimeoutException:
        return {
            "success": False,
            "message": "ntfy connection timeout",
            "details": {"error": "An error occurred"},
        }
    except OperationalError:
        return {
            "success": False,
            "message": "Database error",
            "details": {"error": "An error occurred"},
        }
    except (ValueError, KeyError):
        return {
            "success": False,
            "message": "Invalid configuration",
            "details": {"error": "An error occurred"},
        }


@router.post("/test/dockerhub")
async def test_dockerhub_connection(
    admin: dict | None = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Test Docker Hub registry authentication.

    Tests authentication using the same method that the DockerHubClient uses -
    Basic Auth credentials on requests to hub.docker.com/v2/repositories API.

    Returns:
        Connection test result with status and details
    """
    try:
        # Get Docker Hub credentials
        dockerhub_username = await SettingsService.get(db, "dockerhub_username")
        dockerhub_token = await SettingsService.get(db, "dockerhub_token")

        if not dockerhub_username or not dockerhub_token:
            return {
                "success": False,
                "message": "Docker Hub credentials not configured",
                "details": {
                    "username_configured": bool(dockerhub_username),
                    "token_configured": bool(dockerhub_token),
                },
            }

        # Test authentication using the same method as DockerHubClient
        # The client uses Basic Auth on requests to hub.docker.com/v2/repositories
        async with httpx.AsyncClient(timeout=10.0) as client:
            # Make an authenticated request to the repositories API
            # Using nginx (library/nginx) as a well-known public image
            auth = httpx.BasicAuth(dockerhub_username, dockerhub_token)

            response = await client.get(
                "https://hub.docker.com/v2/repositories/library/nginx/tags",
                params={"page_size": 1},
                auth=auth,
            )

            if response.status_code == 200:
                # Check rate limit headers to verify authenticated access
                # Authenticated users get 200 pulls/6hr vs 100 for anonymous
                rate_limit = response.headers.get("ratelimit-limit", "unknown")
                rate_remaining = response.headers.get("ratelimit-remaining", "unknown")

                return {
                    "success": True,
                    "message": "Docker Hub authentication successful",
                    "details": {
                        "username": dockerhub_username,
                        "authenticated": True,
                        "rate_limit": rate_limit,
                        "rate_remaining": rate_remaining,
                    },
                }
            elif response.status_code == 401:
                return {
                    "success": False,
                    "message": "Docker Hub authentication failed - invalid credentials",
                    "details": {
                        "username": dockerhub_username,
                        "error": "Invalid username or token",
                    },
                }
            elif response.status_code == 429:
                return {
                    "success": False,
                    "message": "Docker Hub rate limited",
                    "details": {
                        "username": dockerhub_username,
                        "error": "Rate limit exceeded - credentials may still be valid",
                    },
                }
            else:
                return {
                    "success": False,
                    "message": f"Docker Hub API error: {response.status_code}",
                    "details": {
                        "status_code": response.status_code,
                        "error": "Unexpected response from Docker Hub",
                    },
                }
    except httpx.HTTPStatusError as e:
        return {
            "success": False,
            "message": f"Docker Hub API error: {e.response.status_code}",
            "details": {
                "status_code": e.response.status_code,
                "error": "An error occurred",
            },
        }
    except httpx.ConnectError:
        return {
            "success": False,
            "message": "Cannot connect to Docker Hub",
            "details": {"error": "Connection refused or network unreachable"},
        }
    except httpx.TimeoutException:
        return {
            "success": False,
            "message": "Docker Hub connection timeout",
            "details": {"error": "An error occurred"},
        }
    except OperationalError:
        return {
            "success": False,
            "message": "Database error",
            "details": {"error": "An error occurred"},
        }
    except (ValueError, KeyError):
        return {
            "success": False,
            "message": "Invalid configuration or response",
            "details": {"error": "An error occurred"},
        }


@router.post("/test/gotify")
async def test_gotify_connection(
    admin: dict | None = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Test Gotify server connection.

    Returns:
        Connection test result with status and details
    """
    gotify_server = "unknown"
    try:
        gotify_enabled = await SettingsService.get_bool(db, "gotify_enabled")
        gotify_server = await SettingsService.get(db, "gotify_server")
        gotify_token = await SettingsService.get(db, "gotify_token")

        if not gotify_enabled:
            return {
                "success": False,
                "message": "Gotify notifications are disabled",
                "details": {"enabled": False},
            }

        if not gotify_server or not gotify_token:
            return {
                "success": False,
                "message": "Gotify server or token not configured",
                "details": {
                    "server_configured": bool(gotify_server),
                    "token_configured": bool(gotify_token),
                },
            }

        # Send test notification
        server_url = gotify_server.rstrip("/")
        url = f"{server_url}/message"

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                url,
                headers={"X-Gotify-Key": gotify_token},
                json={
                    "title": "TideWatch: Connection Test",
                    "message": "If you see this, Gotify notifications are working! 🌊",
                    "priority": 5,
                },
            )
            response.raise_for_status()

            return {
                "success": True,
                "message": "Test notification sent successfully",
                "details": {
                    "server": server_url,
                    "message": "Check your Gotify client for the test notification",
                },
            }
    except httpx.HTTPStatusError as e:
        return {
            "success": False,
            "message": f"Gotify API error: {e.response.status_code}",
            "details": {
                "server": gotify_server,
                "status_code": e.response.status_code,
                "error": "An error occurred",
            },
        }
    except httpx.ConnectError:
        return {
            "success": False,
            "message": "Cannot connect to Gotify server",
            "details": {
                "server": gotify_server,
                "error": "Connection refused or host unreachable",
            },
        }
    except httpx.TimeoutException:
        return {
            "success": False,
            "message": "Gotify connection timeout",
            "details": {"error": "An error occurred"},
        }
    except OperationalError:
        return {
            "success": False,
            "message": "Database error",
            "details": {"error": "An error occurred"},
        }
    except (ValueError, KeyError):
        return {
            "success": False,
            "message": "Invalid configuration",
            "details": {"error": "An error occurred"},
        }


@router.post("/test/pushover")
async def test_pushover_connection(
    admin: dict | None = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Test Pushover API connection.

    Returns:
        Connection test result with status and details
    """
    try:
        pushover_enabled = await SettingsService.get_bool(db, "pushover_enabled")
        pushover_user_key = await SettingsService.get(db, "pushover_user_key")
        pushover_api_token = await SettingsService.get(db, "pushover_api_token")

        if not pushover_enabled:
            return {
                "success": False,
                "message": "Pushover notifications are disabled",
                "details": {"enabled": False},
            }

        if not pushover_user_key or not pushover_api_token:
            return {
                "success": False,
                "message": "Pushover user key or API token not configured",
                "details": {
                    "user_key_configured": bool(pushover_user_key),
                    "api_token_configured": bool(pushover_api_token),
                },
            }

        # Send test notification
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                "https://api.pushover.net/1/messages.json",
                data={
                    "token": pushover_api_token,
                    "user": pushover_user_key,
                    "title": "TideWatch: Connection Test",
                    "message": "If you see this, Pushover notifications are working! 🌊",
                    "priority": 0,
                },
            )
            response.raise_for_status()

            return {
                "success": True,
                "message": "Test notification sent successfully",
                "details": {"message": "Check your Pushover client for the test notification"},
            }
    except httpx.HTTPStatusError as e:
        return {
            "success": False,
            "message": f"Pushover API error: {e.response.status_code}",
            "details": {
                "status_code": e.response.status_code,
                "error": "An error occurred",
            },
        }
    except httpx.ConnectError:
        return {
            "success": False,
            "message": "Cannot connect to Pushover API",
            "details": {"error": "Connection refused or network unreachable"},
        }
    except httpx.TimeoutException:
        return {
            "success": False,
            "message": "Pushover connection timeout",
            "details": {"error": "An error occurred"},
        }
    except OperationalError:
        return {
            "success": False,
            "message": "Database error",
            "details": {"error": "An error occurred"},
        }
    except (ValueError, KeyError):
        return {
            "success": False,
            "message": "Invalid configuration",
            "details": {"error": "An error occurred"},
        }


@router.post("/test/slack")
async def test_slack_connection(
    admin: dict | None = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Test Slack webhook connection.

    Returns:
        Connection test result with status and details
    """
    try:
        slack_enabled = await SettingsService.get_bool(db, "slack_enabled")
        slack_webhook_url = await SettingsService.get(db, "slack_webhook_url")

        if not slack_enabled:
            return {
                "success": False,
                "message": "Slack notifications are disabled",
                "details": {"enabled": False},
            }

        if not slack_webhook_url:
            return {
                "success": False,
                "message": "Slack webhook URL not configured",
                "details": {"webhook_configured": False},
            }

        # Send test notification
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                slack_webhook_url,
                json={
                    "text": "🌊 *TideWatch: Connection Test*\n\nIf you see this, Slack notifications are working!",
                    "username": "TideWatch",
                    "icon_emoji": ":ocean:",
                },
            )
            response.raise_for_status()

            return {
                "success": True,
                "message": "Test notification sent successfully",
                "details": {"message": "Check your Slack channel for the test notification"},
            }
    except httpx.HTTPStatusError as e:
        return {
            "success": False,
            "message": f"Slack API error: {e.response.status_code}",
            "details": {
                "status_code": e.response.status_code,
                "error": "An error occurred",
            },
        }
    except httpx.ConnectError:
        return {
            "success": False,
            "message": "Cannot connect to Slack",
            "details": {"error": "Connection refused or network unreachable"},
        }
    except httpx.TimeoutException:
        return {
            "success": False,
            "message": "Slack connection timeout",
            "details": {"error": "An error occurred"},
        }
    except OperationalError:
        return {
            "success": False,
            "message": "Database error",
            "details": {"error": "An error occurred"},
        }
    except (ValueError, KeyError):
        return {
            "success": False,
            "message": "Invalid configuration",
            "details": {"error": "An error occurred"},
        }


@router.post("/test/discord")
async def test_discord_connection(
    admin: dict | None = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Test Discord webhook connection.

    Returns:
        Connection test result with status and details
    """
    try:
        discord_enabled = await SettingsService.get_bool(db, "discord_enabled")
        discord_webhook_url = await SettingsService.get(db, "discord_webhook_url")

        if not discord_enabled:
            return {
                "success": False,
                "message": "Discord notifications are disabled",
                "details": {"enabled": False},
            }

        if not discord_webhook_url:
            return {
                "success": False,
                "message": "Discord webhook URL not configured",
                "details": {"webhook_configured": False},
            }

        # Send test notification
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                discord_webhook_url,
                json={
                    "username": "TideWatch",
                    "embeds": [
                        {
                            "title": "🌊 Connection Test",
                            "description": "If you see this, Discord notifications are working!",
                            "color": 3447003,  # Blue color
                        }
                    ],
                },
            )
            response.raise_for_status()

            return {
                "success": True,
                "message": "Test notification sent successfully",
                "details": {"message": "Check your Discord channel for the test notification"},
            }
    except httpx.HTTPStatusError as e:
        return {
            "success": False,
            "message": f"Discord API error: {e.response.status_code}",
            "details": {
                "status_code": e.response.status_code,
                "error": "An error occurred",
            },
        }
    except httpx.ConnectError:
        return {
            "success": False,
            "message": "Cannot connect to Discord",
            "details": {"error": "Connection refused or network unreachable"},
        }
    except httpx.TimeoutException:
        return {
            "success": False,
            "message": "Discord connection timeout",
            "details": {"error": "An error occurred"},
        }
    except OperationalError:
        return {
            "success": False,
            "message": "Database error",
            "details": {"error": "An error occurred"},
        }
    except (ValueError, KeyError):
        return {
            "success": False,
            "message": "Invalid configuration",
            "details": {"error": "An error occurred"},
        }


@router.post("/test/telegram")
async def test_telegram_connection(
    admin: dict | None = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Test Telegram bot connection.

    Returns:
        Connection test result with status and details
    """
    try:
        telegram_enabled = await SettingsService.get_bool(db, "telegram_enabled")
        telegram_bot_token = await SettingsService.get(db, "telegram_bot_token")
        telegram_chat_id = await SettingsService.get(db, "telegram_chat_id")

        if not telegram_enabled:
            return {
                "success": False,
                "message": "Telegram notifications are disabled",
                "details": {"enabled": False},
            }

        if not telegram_bot_token or not telegram_chat_id:
            return {
                "success": False,
                "message": "Telegram bot token or chat ID not configured",
                "details": {
                    "bot_token_configured": bool(telegram_bot_token),
                    "chat_id_configured": bool(telegram_chat_id),
                },
            }

        # Send test notification
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"https://api.telegram.org/bot{telegram_bot_token}/sendMessage",
                json={
                    "chat_id": telegram_chat_id,
                    "text": "🌊 *TideWatch: Connection Test*\n\nIf you see this, Telegram notifications are working!",
                    "parse_mode": "Markdown",
                },
            )
            response.raise_for_status()

            result = response.json()
            if not result.get("ok"):
                return {
                    "success": False,
                    "message": f"Telegram API error: {result.get('description', 'Unknown error')}",
                    "details": {"error": result.get("description")},
                }

            return {
                "success": True,
                "message": "Test notification sent successfully",
                "details": {
                    "chat_id": telegram_chat_id,
                    "message": "Check your Telegram chat for the test notification",
                },
            }
    except httpx.HTTPStatusError as e:
        return {
            "success": False,
            "message": f"Telegram API error: {e.response.status_code}",
            "details": {
                "status_code": e.response.status_code,
                "error": "An error occurred",
            },
        }
    except httpx.ConnectError:
        return {
            "success": False,
            "message": "Cannot connect to Telegram API",
            "details": {"error": "Connection refused or network unreachable"},
        }
    except httpx.TimeoutException:
        return {
            "success": False,
            "message": "Telegram connection timeout",
            "details": {"error": "An error occurred"},
        }
    except OperationalError:
        return {
            "success": False,
            "message": "Database error",
            "details": {"error": "An error occurred"},
        }
    except (ValueError, KeyError):
        return {
            "success": False,
            "message": "Invalid configuration",
            "details": {"error": "An error occurred"},
        }


@router.post("/test/email")
async def test_email_connection(
    admin: dict | None = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Test Email SMTP connection.

    Returns:
        Connection test result with status and details
    """
    import aiosmtplib

    smtp_host = "unknown"
    smtp_port = 0
    try:
        email_enabled = await SettingsService.get_bool(db, "email_enabled")
        smtp_host = await SettingsService.get(db, "email_smtp_host")
        smtp_port = await SettingsService.get_int(db, "email_smtp_port", default=587)
        smtp_user = await SettingsService.get(db, "email_smtp_user")
        smtp_password = await SettingsService.get(db, "email_smtp_password")
        from_address = await SettingsService.get(db, "email_from")
        to_address = await SettingsService.get(db, "email_to")
        use_tls = await SettingsService.get_bool(db, "email_smtp_tls", default=True)

        if not email_enabled:
            return {
                "success": False,
                "message": "Email notifications are disabled",
                "details": {"enabled": False},
            }

        if not all([smtp_host, smtp_user, smtp_password, from_address, to_address]):
            return {
                "success": False,
                "message": "Email configuration incomplete",
                "details": {
                    "smtp_host_configured": bool(smtp_host),
                    "smtp_user_configured": bool(smtp_user),
                    "smtp_password_configured": bool(smtp_password),
                    "from_address_configured": bool(from_address),
                    "to_address_configured": bool(to_address),
                },
            }

        # Send test email
        from email.message import EmailMessage

        msg = EmailMessage()
        msg["Subject"] = "TideWatch: Connection Test"
        msg["From"] = from_address
        msg["To"] = to_address
        msg.set_content(
            "🌊 TideWatch Email Test\n\n"
            "If you see this, email notifications are working!\n\n"
            "This is an automated test message from TideWatch."
        )

        await aiosmtplib.send(
            msg,
            hostname=smtp_host,
            port=smtp_port,
            username=smtp_user,
            password=smtp_password,
            start_tls=use_tls,
            timeout=30.0,
        )

        return {
            "success": True,
            "message": "Test email sent successfully",
            "details": {
                "smtp_host": smtp_host,
                "smtp_port": smtp_port,
                "from": from_address,
                "to": to_address,
                "tls": use_tls,
                "message": "Check your inbox for the test email",
            },
        }
    except aiosmtplib.SMTPException:
        logger.error("SMTP test failed", exc_info=True)
        return {
            "success": False,
            "message": "SMTP connection failed. Check server logs for details.",
            "details": {
                "smtp_host": smtp_host,
                "smtp_port": smtp_port,
                "error": "An error occurred",
            },
        }
    except ConnectionRefusedError:
        return {
            "success": False,
            "message": "Cannot connect to SMTP server",
            "details": {
                "smtp_host": smtp_host,
                "smtp_port": smtp_port,
                "error": "Connection refused",
            },
        }
    except TimeoutError:
        return {
            "success": False,
            "message": "SMTP connection timeout",
            "details": {"error": "An error occurred"},
        }
    except OperationalError:
        return {
            "success": False,
            "message": "Database error",
            "details": {"error": "An error occurred"},
        }
    except (ValueError, KeyError):
        return {
            "success": False,
            "message": "Invalid configuration",
            "details": {"error": "An error occurred"},
        }
    except ImportError:
        return {
            "success": False,
            "message": "aiosmtplib not installed",
            "details": {"error": "Email support requires the aiosmtplib package"},
        }


@router.post("/test/ghcr")
async def test_ghcr_connection(
    admin: dict | None = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Test GitHub Container Registry (GHCR) authentication.

    Tests authentication using the same endpoint and method that the
    GHCRClient uses - requesting a bearer token from ghcr.io/token
    with Basic Auth credentials.

    Returns:
        Connection test result with status and details
    """
    try:
        # Get GHCR credentials
        ghcr_username = await SettingsService.get(db, "ghcr_username")
        ghcr_token = await SettingsService.get(db, "ghcr_token")

        if not ghcr_username or not ghcr_token:
            return {
                "success": False,
                "message": "GHCR credentials not configured",
                "details": {
                    "username_configured": bool(ghcr_username),
                    "token_configured": bool(ghcr_token),
                },
            }

        # Test authentication against actual GHCR token endpoint
        # This is what the GHCRClient._get_bearer_token() method uses
        async with httpx.AsyncClient(timeout=10.0) as client:
            # Use a well-known public image to test token validity
            # linuxserver images are public and reliable for testing
            test_image = "linuxserver/sonarr"
            params = {
                "scope": f"repository:{test_image}:pull",
                "service": "ghcr.io",
            }

            # GHCR requires Basic Auth for token requests
            auth = httpx.BasicAuth(ghcr_username, ghcr_token)

            response = await client.get(
                "https://ghcr.io/token",
                params=params,
                auth=auth,
            )

            if response.status_code == 200:
                data = response.json()
                token = data.get("token")

                if token:
                    return {
                        "success": True,
                        "message": "GHCR authentication successful",
                        "details": {
                            "username": ghcr_username,
                            "authenticated": True,
                            "token_valid": True,
                        },
                    }
                else:
                    return {
                        "success": False,
                        "message": "GHCR returned empty token",
                        "details": {
                            "username": ghcr_username,
                            "error": "Token response was empty",
                        },
                    }
            elif response.status_code == 401:
                return {
                    "success": False,
                    "message": "GHCR authentication failed - invalid credentials",
                    "details": {
                        "username": ghcr_username,
                        "error": "Invalid username or token",
                    },
                }
            elif response.status_code == 403:
                return {
                    "success": False,
                    "message": "GHCR authentication failed - token expired or lacks permissions",
                    "details": {
                        "username": ghcr_username,
                        "error": "Token may be expired or missing read:packages scope",
                    },
                }
            else:
                return {
                    "success": False,
                    "message": f"GHCR API error: {response.status_code}",
                    "details": {
                        "status_code": response.status_code,
                        "error": "Unexpected response from GHCR",
                    },
                }
    except httpx.HTTPStatusError as e:
        return {
            "success": False,
            "message": f"GHCR API error: {e.response.status_code}",
            "details": {
                "status_code": e.response.status_code,
                "error": "An error occurred",
            },
        }
    except httpx.ConnectError:
        return {
            "success": False,
            "message": "Cannot connect to GitHub",
            "details": {"error": "Connection refused or network unreachable"},
        }
    except httpx.TimeoutException:
        return {
            "success": False,
            "message": "GitHub connection timeout",
            "details": {"error": "An error occurred"},
        }
    except OperationalError:
        return {
            "success": False,
            "message": "Database error",
            "details": {"error": "An error occurred"},
        }
    except (ValueError, KeyError):
        return {
            "success": False,
            "message": "Invalid configuration or response",
            "details": {"error": "An error occurred"},
        }
