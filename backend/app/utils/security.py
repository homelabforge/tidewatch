"""Security utilities for input sanitization and validation.

This module provides functions to prevent security vulnerabilities:
- Log injection: Sanitize user input before logging
- Path injection: Validate file paths to prevent traversal attacks
- Sensitive data exposure: Mask sensitive values in logs/responses
"""

import re
from pathlib import Path
from typing import Union, Optional


def sanitize_log_message(msg: Union[str, bytes, int, float, None]) -> str:
    """Remove newlines and control characters from log messages.

    Prevents log injection attacks where attackers inject newlines or control
    characters to corrupt log files, hide malicious activity, or break log parsing.

    Args:
        msg: Message to sanitize (will be converted to string)

    Returns:
        Sanitized message with control characters removed

    Examples:
        >>> sanitize_log_message("Container\\nmalicious\\nlog")
        'Containermaliciouslog'
        >>> sanitize_log_message("User: admin\\r\\nPassword: secret")
        'User: adminPassword: secret'

    Security:
        Removes the following characters:
        - Newlines: \\n, \\r
        - Tab: \\t
        - Control characters: 0x00-0x1f (ASCII control codes)
        - Delete and control chars: 0x7f-0x9f
    """
    if msg is None:
        return ""

    # Convert to string if not already
    msg_str = str(msg)

    # Remove newlines, tabs, and all control characters
    # Pattern matches: \n, \r, \t, and control chars (0x00-0x1f, 0x7f-0x9f)
    sanitized = re.sub(r'[\n\r\t\x00-\x1f\x7f-\x9f]', '', msg_str)

    return sanitized


def mask_sensitive(value: Union[str, None], visible_chars: int = 4, mask_char: str = "*") -> str:
    """Mask sensitive values, showing only the last N characters.

    Used to prevent sensitive data exposure in logs and API responses while
    maintaining some visibility for debugging (e.g., "which API key was used?").

    Args:
        value: Sensitive value to mask (API keys, tokens, passwords, etc.)
        visible_chars: Number of characters to show at the end (default: 4)
        mask_char: Character to use for masking (default: "*")

    Returns:
        Masked string showing only last visible_chars characters

    Examples:
        >>> mask_sensitive("sk_live_1234567890abcdef")
        '***cdef'
        >>> mask_sensitive("password123", visible_chars=3)
        '***123'
        >>> mask_sensitive("abc", visible_chars=4)
        '***'
        >>> mask_sensitive("")
        '***'
        >>> mask_sensitive(None)
        '***'

    Security:
        - Never shows the beginning of secrets (where entropy is highest)
        - Shows only last few chars for verification purposes
        - Returns generic mask for None or empty values
        - Safe for logging and API responses
    """
    if not value or len(value) == 0:
        return mask_char * 3

    # For very short values, mask completely
    if len(value) <= visible_chars:
        return mask_char * 3

    # Show last N characters only
    visible_part = value[-visible_chars:]
    return f"{mask_char * 3}{visible_part}"


def sanitize_path(user_path: Union[str, Path], base_dir: Union[str, Path], allow_symlinks: bool = False) -> Path:
    """Safely resolve user-provided paths within a base directory.

    Prevents path traversal attacks (e.g., "../../etc/passwd") by:
    1. Resolving the path to its absolute form
    2. Checking if it's within the allowed base directory
    3. Optionally rejecting symbolic links

    Args:
        user_path: User-provided path (can be relative or absolute)
        base_dir: Base directory that user_path must be within
        allow_symlinks: If False (default), reject symbolic links for extra security

    Returns:
        Resolved absolute Path object if validation passes

    Raises:
        ValueError: If path traversal detected or symlink found (when disallowed)
        FileNotFoundError: If base_dir doesn't exist

    Examples:
        >>> sanitize_path("data/compose.yml", "/app/data")
        PosixPath('/app/data/compose.yml')

        >>> sanitize_path("../../etc/passwd", "/app/data")
        ValueError: Path traversal detected

        >>> sanitize_path("/etc/passwd", "/app/data")
        ValueError: Path traversal detected

    Security:
        - Resolves all symlinks and relative paths (. and ..)
        - Validates resolved path is within base_dir
        - Prevents access to files outside allowed directory
        - Optionally blocks symlink attacks

    References:
        - CWE-22: Improper Limitation of a Pathname to a Restricted Directory
        - OWASP: Path Traversal
    """
    # Convert to Path objects
    base = Path(base_dir).resolve()

    # Check base directory exists
    if not base.exists():
        raise FileNotFoundError(f"Base directory does not exist: {base}")

    # If user_path is absolute, it must still be within base_dir
    # Resolve() will follow symlinks and resolve .. components
    try:
        # Combine paths: if user_path is absolute, it will override base
        # If relative, it will be relative to base
        if Path(user_path).is_absolute():
            # For absolute paths, resolve and check if within base
            target = Path(user_path).resolve()
        else:
            # For relative paths, resolve relative to base
            target = (base / user_path).resolve()
    except (OSError, RuntimeError) as e:
        # Resolve can fail on invalid paths, circular symlinks, etc.
        raise ValueError(f"Invalid path: {user_path} - {e}")

    # Check for symlinks if disallowed
    if not allow_symlinks:
        # Check if the path itself is a symlink
        try:
            if (base / user_path).exists() and (base / user_path).is_symlink():
                raise ValueError(f"Symbolic links not allowed: {user_path}")
        except (OSError, RuntimeError):
            # Path might not exist yet, which is okay
            pass

    # Ensure the resolved path is within base_dir
    # is_relative_to() checks if target is a subpath of base
    try:
        if not target.is_relative_to(base):
            raise ValueError(
                f"Path traversal detected: {user_path} resolves to {target}, "
                f"which is outside base directory {base}"
            )
    except AttributeError:
        # Python <3.9 fallback: use try/except with relative_to
        try:
            target.relative_to(base)
        except ValueError:
            raise ValueError(
                f"Path traversal detected: {user_path} resolves to {target}, "
                f"which is outside base directory {base}"
            )

    return target


def is_safe_filename(filename: str, allow_dots: bool = True) -> bool:
    """Check if a filename is safe (no path components, control chars, etc.).

    Args:
        filename: Filename to validate (should not contain path separators)
        allow_dots: If False, reject filenames starting with . (hidden files)

    Returns:
        True if filename is safe, False otherwise

    Examples:
        >>> is_safe_filename("document.pdf")
        True
        >>> is_safe_filename("../../../etc/passwd")
        False
        >>> is_safe_filename(".htaccess")
        True
        >>> is_safe_filename(".htaccess", allow_dots=False)
        False
        >>> is_safe_filename("file\\x00.txt")
        False

    Security:
        - Rejects path separators (/, \\)
        - Rejects null bytes
        - Rejects control characters
        - Optionally rejects hidden files (starting with .)
    """
    if not filename or len(filename) == 0:
        return False

    # Reject path separators
    if '/' in filename or '\\' in filename:
        return False

    # Reject null bytes (can be used for path truncation)
    if '\x00' in filename:
        return False

    # Reject control characters
    if re.search(r'[\x00-\x1f\x7f-\x9f]', filename):
        return False

    # Optionally reject hidden files
    if not allow_dots and filename.startswith('.'):
        return False

    # Reject special directory names
    if filename in ('.', '..'):
        return False

    return True


def validate_container_name(name: str) -> str:
    """Validate and sanitize Docker container name.

    Docker container names must match: [a-zA-Z0-9][a-zA-Z0-9_.-]*

    Args:
        name: Container name to validate

    Returns:
        Validated container name

    Raises:
        ValueError: If container name is invalid

    Examples:
        >>> validate_container_name("my-container")
        'my-container'
        >>> validate_container_name("container_1")
        'container_1'
        >>> validate_container_name("../../../etc")
        ValueError: Invalid container name
    """
    if not name or len(name) == 0:
        raise ValueError("Container name cannot be empty")

    # Docker container name regex: starts with alphanumeric, then alphanumeric + _ . -
    if not re.match(r'^[a-zA-Z0-9][a-zA-Z0-9_.-]*$', name):
        raise ValueError(
            f"Invalid container name: {name}. "
            "Must match [a-zA-Z0-9][a-zA-Z0-9_.-]*"
        )

    return name


def validate_image_name(image: str) -> str:
    """Validate Docker image name format.

    Args:
        image: Image name to validate (e.g., "nginx:latest", "myregistry.com/image:tag")

    Returns:
        Validated image name

    Raises:
        ValueError: If image name is invalid

    Examples:
        >>> validate_image_name("nginx:latest")
        'nginx:latest'
        >>> validate_image_name("ghcr.io/user/repo:v1.0.0")
        'ghcr.io/user/repo:v1.0.0'
        >>> validate_image_name("../../etc/passwd")
        ValueError: Invalid image name
    """
    if not image or len(image) == 0:
        raise ValueError("Image name cannot be empty")

    # Basic validation: no path traversal patterns
    if '..' in image or image.startswith('/'):
        raise ValueError(f"Invalid image name: {image}")

    # Check for control characters
    if re.search(r'[\x00-\x1f\x7f-\x9f]', image):
        raise ValueError(f"Invalid image name contains control characters: {image}")

    # Docker image name pattern (simplified):
    # [registry/][namespace/]repository[:tag|@digest]
    # Allow: alphanumeric, dots, hyphens, underscores, slashes, colons, @
    if not re.match(r'^[a-zA-Z0-9][a-zA-Z0-9._/:@-]*$', image):
        raise ValueError(f"Invalid image name format: {image}")

    return image
