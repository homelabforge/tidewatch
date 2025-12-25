"""Centralized error handling utilities for secure error responses.

This module provides utilities to prevent information disclosure through error messages:
- Stack traces logged server-side only (not exposed to users)
- Generic user-facing error messages
- Full exception details captured for debugging

Security:
    - CWE-209: Generation of Error Message Containing Sensitive Information
    - CWE-497: Exposure of Sensitive System Information to an Unauthorized Control Sphere
"""

import logging
from typing import Optional, Any, Dict
from fastapi import HTTPException


def safe_error_response(
    logger_instance: logging.Logger,
    error: Exception,
    user_message: str,
    status_code: int = 500,
    log_level: str = "error",
) -> None:
    """Log full error details server-side and raise generic HTTPException for user.

    This function ensures that:
    1. Full stack traces are logged for debugging
    2. Users only see generic, safe error messages
    3. No sensitive system information is leaked

    Args:
        logger_instance: Logger instance to use for server-side logging
        error: The exception that was caught
        user_message: Generic message to show to the user (should not contain sensitive details)
        status_code: HTTP status code for the response (default: 500)
        log_level: Logging level to use (error, warning, info) (default: error)

    Raises:
        HTTPException: With the user_message as detail

    Examples:
        >>> logger = logging.getLogger(__name__)
        >>> try:
        ...     result = do_database_operation()
        >>> except Exception as e:
        ...     safe_error_response(
        ...         logger, e,
        ...         "Failed to update settings",
        ...         status_code=500
        ...     )

    Security:
        - Full exception and stack trace logged only on server
        - User receives only the generic user_message
        - No file paths, module names, or internal details exposed
    """
    # Log full exception details server-side (with stack trace)
    log_method = getattr(logger_instance, log_level, logger_instance.error)
    log_method(f"{user_message}: {type(error).__name__}", exc_info=True)

    # Raise HTTPException with generic message for user
    raise HTTPException(status_code=status_code, detail=user_message)


def safe_dict_response(
    logger_instance: logging.Logger,
    error: Exception,
    user_message: str,
    success: bool = False,
    additional_fields: Optional[Dict[str, Any]] = None,
    log_level: str = "error",
) -> Dict[str, Any]:
    """Log error server-side and return safe dict response (for non-exception returns).

    Use this when you want to return an error dict instead of raising an exception.

    Args:
        logger_instance: Logger instance to use for server-side logging
        error: The exception that was caught
        user_message: Generic message to include in response
        success: Success flag for the response (default: False)
        additional_fields: Additional fields to include in response dict
        log_level: Logging level to use (error, warning, info) (default: error)

    Returns:
        Dict with success flag, message, and optional additional fields

    Examples:
        >>> logger = logging.getLogger(__name__)
        >>> try:
        ...     result = do_operation()
        >>> except Exception as e:
        ...     return safe_dict_response(
        ...         logger, e,
        ...         "Operation failed",
        ...         additional_fields={"code": "OP_ERROR"}
        ...     )

    Security:
        - Full exception logged only on server
        - Response dict contains only safe, generic information
    """
    # Log full exception details server-side
    log_method = getattr(logger_instance, log_level, logger_instance.error)
    log_method(f"{user_message}: {type(error).__name__}", exc_info=True)

    # Build safe response dict
    response = {"success": success, "message": user_message}

    if additional_fields:
        response.update(additional_fields)

    return response


def log_and_continue(
    logger_instance: logging.Logger,
    error: Exception,
    context_message: str,
    log_level: str = "warning",
) -> None:
    """Log error but continue execution (for non-critical errors).

    Use this for errors that should be logged but don't require halting execution.

    Args:
        logger_instance: Logger instance to use
        error: The exception that was caught
        context_message: Context about where/why this error occurred
        log_level: Logging level to use (default: warning)

    Examples:
        >>> logger = logging.getLogger(__name__)
        >>> try:
        ...     send_notification()
        >>> except Exception as e:
        ...     log_and_continue(logger, e, "Failed to send notification")
        ...     # Continue with main logic

    Security:
        - Full exception logged with context
        - No user-facing output
    """
    log_method = getattr(logger_instance, log_level, logger_instance.warning)
    log_method(f"{context_message}: {type(error).__name__}", exc_info=True)
