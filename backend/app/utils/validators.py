"""Security validation utilities for Tidewatch."""

import re
from pathlib import Path
from typing import List, Optional


class ValidationError(Exception):
    """Raised when validation fails."""
    pass


def validate_container_name(name: str) -> str:
    """Validate container/service name for safe use in Docker commands.

    Args:
        name: Container or service name to validate

    Returns:
        Validated name

    Raises:
        ValidationError: If name contains invalid characters or patterns
    """
    if not name:
        raise ValidationError("Container name cannot be empty")

    # Reject names starting with dash (could be interpreted as flag)
    if name.startswith("-"):
        raise ValidationError("Container name cannot start with dash")

    # Only allow alphanumeric, underscore, dash, and dot (Docker naming rules)
    # But dash cannot be at start (already checked)
    if not re.match(r'^[a-zA-Z0-9_][a-zA-Z0-9_.-]*$', name):
        raise ValidationError(
            "Container name must contain only alphanumeric characters, "
            "underscores, dashes, and dots"
        )

    # Reject any shell metacharacters
    dangerous_chars = ['$', '`', '\\', '"', "'", ';', '|', '&', '<', '>',
                       '(', ')', '{', '}', '[', ']', '*', '?', '!', '\n', '\r']
    if any(char in name for char in dangerous_chars):
        raise ValidationError(f"Container name contains forbidden characters")

    # Length check
    if len(name) > 255:
        raise ValidationError("Container name too long (max 255 characters)")

    return name


def validate_service_name(name: str) -> str:
    """Validate service name for safe use in Docker Compose commands.

    Args:
        name: Service name to validate

    Returns:
        Validated name

    Raises:
        ValidationError: If name contains invalid characters
    """
    if not name:
        raise ValidationError("Service name cannot be empty")

    # Service names should be alphanumeric + underscore/dash only
    if not re.match(r'^[a-zA-Z0-9_-]+$', name):
        raise ValidationError(
            "Service name must contain only alphanumeric characters, "
            "underscores, and dashes"
        )

    # Reject names starting with dash
    if name.startswith("-"):
        raise ValidationError("Service name cannot start with dash")

    # Length check
    if len(name) > 255:
        raise ValidationError("Service name too long (max 255 characters)")

    return name


def validate_compose_file_path(path: str, allowed_base: str = "/compose", strict: bool = True) -> Path:
    """Validate and resolve compose file path to prevent path traversal.

    Args:
        path: Path to compose file
        allowed_base: Base directory that must contain the file

    Returns:
        Resolved absolute Path object

    Raises:
        ValidationError: If path is invalid or outside allowed directory
    """
    if not path:
        raise ValidationError("Compose file path cannot be empty")

    # Check for dangerous patterns
    dangerous_patterns = ['..', '//', '\\', '\x00']
    if any(pattern in path for pattern in dangerous_patterns):
        raise ValidationError("Compose file path contains forbidden patterns")

    try:
        # Convert to Path and resolve to absolute path
        file_path = Path(path).resolve(strict=strict)
    except (OSError, RuntimeError) as e:
        raise ValidationError(f"Invalid compose file path: {e}")

    # Only validate file existence if strict mode is enabled
    if strict:
        if not file_path.exists():
            raise ValidationError("Compose file does not exist")

        if not file_path.is_file():
            raise ValidationError("Compose file path is not a file")

        # Check file extension
        if file_path.suffix not in ['.yml', '.yaml']:
            raise ValidationError("Compose file must have .yml or .yaml extension")

    # Ensure path is within allowed base directory
    allowed_base_path = Path(allowed_base).resolve()
    try:
        file_path.relative_to(allowed_base_path)
    except ValueError:
        raise ValidationError(
            f"Compose file must be within {allowed_base} directory"
        )

    return file_path


def validate_docker_compose_command(command: str) -> List[str]:
    """Validate and parse Docker Compose command template.

    Only allows 'docker compose' or 'docker-compose' as the base command.
    Rejects shell metacharacters and dangerous patterns.
    Preserves all flags and options for multi-file compose setups.

    Args:
        command: Command template (may contain placeholders)

    Returns:
        List of validated command parts with placeholders preserved

    Raises:
        ValidationError: If command contains forbidden patterns
    """
    if not command:
        raise ValidationError("Docker compose command cannot be empty")

    # Remove placeholders for validation ONLY
    clean_cmd = command.replace("{compose_file}", "")
    clean_cmd = clean_cmd.replace("{service}", "")
    clean_cmd = clean_cmd.replace("{env_file}", "")
    clean_cmd = clean_cmd.strip()

    # Check for shell metacharacters (but allow quotes and hyphens for docker compose flags)
    dangerous_chars = ['$', '`', '\\', ';', '|', '&', '<', '>',
                       '(', ')', '{', '}', '*', '?', '!', '\n', '\r']
    if any(char in clean_cmd for char in dangerous_chars):
        raise ValidationError("Docker compose command contains forbidden characters")

    # Split command and validate
    parts = clean_cmd.split()

    # Must start with docker compose or docker-compose (allow full paths)
    if len(parts) < 1:
        raise ValidationError("Invalid Docker compose command format")

    # Get the basename of the command (in case of full path like /usr/bin/docker)
    cmd_basename = parts[0].split('/')[-1]
    
    # Check if it's docker-compose command
    if cmd_basename == 'docker-compose':
        return command.split()
    
    # Check if it's docker compose (parts[0] should be 'docker' or end with '/docker')
    if cmd_basename != 'docker':
        raise ValidationError("Command must start with 'docker' or 'docker-compose'")
    
    # If using 'docker compose' format, ensure 'compose' is the second part
    if len(parts) < 2 or parts[1] not in ["compose", "compose-v2"]:
        raise ValidationError("Command must be 'docker compose' or 'docker-compose'")

    # Return ALL command parts, not just base command
    # This preserves -p, -f, and other flags for multi-file setups
    return command.split()


def build_docker_compose_command(
    compose_file: Path,
    service_name: str,
    env_file: Optional[Path] = None,
    action: str = "up"
) -> List[str]:
    """Build a safe Docker Compose command using list-based construction.

    Args:
        compose_file: Path to compose file (already validated)
        service_name: Service name (already validated)
        env_file: Optional path to env file
        action: Docker Compose action (up, restart, stop, etc.)

    Returns:
        List of command parts ready for subprocess.run()
    """
    # Validate action
    allowed_actions = ["up", "down", "restart", "stop", "start", "pull", "ps", "logs"]
    if action not in allowed_actions:
        raise ValidationError(f"Invalid Docker Compose action: {action}")

    # Build command as list
    cmd = ["docker", "compose", "-f", str(compose_file)]

    # Add env file if provided
    if env_file and env_file.exists():
        cmd.extend(["--env-file", str(env_file)])

    # Add action
    cmd.append(action)

    # Add service-specific flags for 'up' action
    if action == "up":
        cmd.extend(["-d", "--no-deps", "--force-recreate"])

    # Add service name
    cmd.append(service_name)

    return cmd


def build_docker_command(
    action: str,
    container_name: str,
    additional_args: Optional[List[str]] = None
) -> List[str]:
    """Build a safe Docker command using list-based construction.

    Args:
        action: Docker action (restart, stop, start, etc.)
        container_name: Container name (already validated)
        additional_args: Optional additional arguments

    Returns:
        List of command parts ready for subprocess.run()
    """
    # Validate action
    allowed_actions = ["restart", "stop", "start", "pause", "unpause", "inspect", "logs"]
    if action not in allowed_actions:
        raise ValidationError(f"Invalid Docker action: {action}")

    # Build command as list
    cmd = ["docker", action, container_name]

    # Add additional args if provided
    if additional_args:
        # Validate each arg doesn't contain shell metacharacters
        for arg in additional_args:
            if any(char in arg for char in ['$', '`', '\\', ';', '|', '&']):
                raise ValidationError(f"Invalid argument: {arg}")
        cmd.extend(additional_args)

    return cmd
