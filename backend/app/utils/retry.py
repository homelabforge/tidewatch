"""Retry utilities for handling transient failures."""

import asyncio
import logging
from collections.abc import Callable
from functools import wraps
from typing import Any, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


def async_retry(
    max_attempts: int = 3,
    backoff_base: float = 2.0,
    backoff_max: float = 60.0,
    exceptions: tuple[type[Exception], ...] = (Exception,),
    on_retry: Callable[[Exception, int], None] | None = None,
):
    """Decorator for retrying async functions with exponential backoff.

    Args:
        max_attempts: Maximum number of attempts
        backoff_base: Base for exponential backoff (seconds)
        backoff_max: Maximum backoff time (seconds)
        exceptions: Tuple of exception types to retry on
        on_retry: Optional callback function called on each retry

    Returns:
        Decorated function that retries on failure

    Example:
        @async_retry(max_attempts=3, exceptions=(aiohttp.ClientError,))
        async def fetch_data(url: str):
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    return await response.json()
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(func)
        async def wrapper(*args, **kwargs) -> Any:
            last_exception: Exception | None = None

            for attempt in range(1, max_attempts + 1):
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e

                    if attempt == max_attempts:
                        logger.error(
                            f"{func.__name__} failed after {max_attempts} attempts: {str(e)}"
                        )
                        raise

                    # Calculate backoff with exponential increase
                    backoff = min(backoff_base ** (attempt - 1), backoff_max)

                    logger.warning(
                        f"{func.__name__} attempt {attempt}/{max_attempts} failed: {str(e)}. "
                        f"Retrying in {backoff:.1f}s..."
                    )

                    if on_retry:
                        on_retry(e, attempt)

                    await asyncio.sleep(backoff)

            # This should never be reached due to raise on line 54, but satisfy type checker
            # If somehow reached, last_exception should be set from the loop
            assert last_exception is not None, "No exception captured but max attempts reached"
            raise last_exception

        return wrapper

    return decorator


def sync_retry(
    max_attempts: int = 3,
    backoff_base: float = 2.0,
    backoff_max: float = 60.0,
    exceptions: tuple[type[Exception], ...] = (Exception,),
    on_retry: Callable[[Exception, int], None] | None = None,
):
    """Decorator for retrying sync functions with exponential backoff.

    Args:
        max_attempts: Maximum number of attempts
        backoff_base: Base for exponential backoff (seconds)
        backoff_max: Maximum backoff time (seconds)
        exceptions: Tuple of exception types to retry on
        on_retry: Optional callback function called on each retry

    Returns:
        Decorated function that retries on failure
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            import time

            last_exception: Exception | None = None

            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e

                    if attempt == max_attempts:
                        logger.error(
                            f"{func.__name__} failed after {max_attempts} attempts: {str(e)}"
                        )
                        raise

                    # Calculate backoff with exponential increase
                    backoff = min(backoff_base ** (attempt - 1), backoff_max)

                    logger.warning(
                        f"{func.__name__} attempt {attempt}/{max_attempts} failed: {str(e)}. "
                        f"Retrying in {backoff:.1f}s..."
                    )

                    if on_retry:
                        on_retry(e, attempt)

                    time.sleep(backoff)

            # This should never be reached due to raise on line 113, but satisfy type checker
            # If somehow reached, last_exception should be set from the loop
            assert last_exception is not None, "No exception captured but max attempts reached"
            raise last_exception

        return wrapper

    return decorator
