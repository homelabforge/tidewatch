"""Update window validation for time-based update restrictions."""

import logging
import re
from datetime import datetime, time
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


class UpdateWindow:
    """Helper class for validating update windows.

    Update window formats:
        - "HH:MM-HH:MM" - Daily time window (e.g., "02:00-06:00")
        - "Days:HH:MM-HH:MM" - Specific days (e.g., "Sat,Sun:00:00-23:59", "Mon-Fri:22:00-06:00")

    Examples:
        "02:00-06:00" - Updates allowed between 2am-6am daily
        "Sat,Sun:00:00-23:59" - Updates allowed only on weekends
        "Mon-Fri:22:00-06:00" - Updates allowed weeknights (crosses midnight)
    """

    # Day name mappings
    DAY_NAMES = {
        "mon": 0, "monday": 0,
        "tue": 1, "tuesday": 1,
        "wed": 2, "wednesday": 2,
        "thu": 3, "thursday": 3,
        "fri": 4, "friday": 4,
        "sat": 5, "saturday": 5,
        "sun": 6, "sunday": 6,
    }

    @staticmethod
    def is_in_window(update_window: Optional[str], check_time: Optional[datetime] = None) -> bool:
        """Check if current time is within the update window.

        Args:
            update_window: Window configuration string (None/empty means always allowed)
            check_time: Time to check (defaults to now)

        Returns:
            True if updates are allowed, False otherwise
        """
        if not update_window or not update_window.strip():
            return True  # No restrictions

        if check_time is None:
            check_time = datetime.now()

        try:
            # Parse the window configuration
            days, start_time, end_time = UpdateWindow._parse_window(update_window)

            # Check if current day is allowed
            current_day = check_time.weekday()
            if days is not None and current_day not in days:
                logger.debug(
                    f"Current day {current_day} not in allowed days {days}"
                )
                return False

            # Check if current time is in range
            current_time = check_time.time()

            # Handle time ranges that cross midnight (e.g., 22:00-06:00)
            if end_time < start_time:
                # Time range crosses midnight
                in_window = current_time >= start_time or current_time <= end_time
            else:
                # Normal time range
                in_window = start_time <= current_time <= end_time

            if in_window:
                logger.debug(
                    f"Current time {current_time} is within window "
                    f"{start_time}-{end_time}"
                )
            else:
                logger.debug(
                    f"Current time {current_time} is outside window "
                    f"{start_time}-{end_time}"
                )

            return in_window

        except (ValueError, KeyError, AttributeError) as e:
            logger.error(f"Invalid update window format '{update_window}': {e}")
            return True  # On error, allow updates (fail open)

    @staticmethod
    def _parse_window(window_str: str) -> Tuple[Optional[set], time, time]:
        """Parse update window string into components.

        Args:
            window_str: Window configuration string

        Returns:
            Tuple of (allowed_days, start_time, end_time)
            allowed_days is None for daily windows, or set of weekday integers

        Raises:
            ValueError: If format is invalid
        """
        window_str = window_str.strip()

        # Check if days are specified by looking for pattern: <non-digit>:<digit>
        # This distinguishes "Mon-Fri:22:00" from "22:00-06:00"
        # Day formats always have a letter before the colon
        days_part = None
        time_part = window_str

        # Look for day specification pattern (letters/hyphens/commas followed by colon then digits)
        match = re.match(r'^([A-Za-z\-,]+):(.+)$', window_str)
        if match:
            # This looks like "Days:HH:MM-HH:MM"
            days_part = match.group(1)
            time_part = match.group(2)
            allowed_days = UpdateWindow._parse_days(days_part)
        else:
            # Format: "HH:MM-HH:MM" (daily)
            allowed_days = None

        # Parse time range
        if "-" not in time_part:
            raise ValueError(f"Invalid time range format: {time_part}")

        start_str, end_str = time_part.split("-", 1)
        start_time = UpdateWindow._parse_time(start_str.strip())
        end_time = UpdateWindow._parse_time(end_str.strip())

        return allowed_days, start_time, end_time

    @staticmethod
    def _parse_days(days_str: str) -> set:
        """Parse day specification into set of weekday integers.

        Args:
            days_str: Day specification (e.g., "Mon-Fri", "Sat,Sun")

        Returns:
            Set of weekday integers (0=Monday, 6=Sunday)

        Raises:
            ValueError: If day format is invalid
        """
        days = set()

        # Split by comma for multiple day specs
        for part in days_str.split(","):
            part = part.strip().lower()

            # Check for range (e.g., "Mon-Fri")
            if "-" in part:
                start_day, end_day = part.split("-", 1)
                start_day = start_day.strip()
                end_day = end_day.strip()

                if start_day not in UpdateWindow.DAY_NAMES:
                    raise ValueError(f"Invalid day name: {start_day}")
                if end_day not in UpdateWindow.DAY_NAMES:
                    raise ValueError(f"Invalid day name: {end_day}")

                start_num = UpdateWindow.DAY_NAMES[start_day]
                end_num = UpdateWindow.DAY_NAMES[end_day]

                # Handle ranges (including wrapping like Fri-Mon)
                if start_num <= end_num:
                    days.update(range(start_num, end_num + 1))
                else:
                    # Wrapping range (e.g., Fri-Mon = Fri,Sat,Sun,Mon)
                    days.update(range(start_num, 7))
                    days.update(range(0, end_num + 1))
            else:
                # Single day
                if part not in UpdateWindow.DAY_NAMES:
                    raise ValueError(f"Invalid day name: {part}")
                days.add(UpdateWindow.DAY_NAMES[part])

        return days

    @staticmethod
    def _parse_time(time_str: str) -> time:
        """Parse time string into time object.

        Args:
            time_str: Time in HH:MM format

        Returns:
            time object

        Raises:
            ValueError: If time format is invalid
        """
        # Match HH:MM format
        match = re.match(r"^(\d{1,2}):(\d{2})$", time_str)
        if not match:
            raise ValueError(f"Invalid time format: {time_str}")

        hour = int(match.group(1))
        minute = int(match.group(2))

        if hour < 0 or hour > 23:
            raise ValueError(f"Invalid hour: {hour}")
        if minute < 0 or minute > 59:
            raise ValueError(f"Invalid minute: {minute}")

        return time(hour=hour, minute=minute)

    @staticmethod
    def validate_format(window_str: Optional[str]) -> Tuple[bool, Optional[str]]:
        """Validate update window format.

        Args:
            window_str: Window configuration string

        Returns:
            Tuple of (is_valid, error_message)
        """
        if not window_str or not window_str.strip():
            return True, None

        try:
            UpdateWindow._parse_window(window_str)
            return True, None
        except (ValueError, KeyError, AttributeError) as e:
            return False, str(e)
