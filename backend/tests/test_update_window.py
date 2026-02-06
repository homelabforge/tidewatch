"""Tests for update window validation (app/services/update_window.py).

Tests time-based update restrictions:
- Daily time windows (HH:MM-HH:MM)
- Day-specific windows (Days:HH:MM-HH:MM)
- Midnight-crossing windows
- Day range parsing (Mon-Fri, Sat,Sun)
- Time parsing and validation
- Format validation
"""

from datetime import datetime, time

import pytest

from app.services.update_window import UpdateWindow


class TestIsInWindow:
    """Test is_in_window() method for time validation."""

    def test_returns_true_when_no_window_specified(self):
        """Test returns True when update_window is None or empty."""
        assert UpdateWindow.is_in_window(None) is True
        assert UpdateWindow.is_in_window("") is True
        assert UpdateWindow.is_in_window("   ") is True

    def test_checks_daily_time_window(self):
        """Test checks daily time window (HH:MM-HH:MM)."""
        # Window: 02:00-06:00 (2am to 6am daily)
        window = "02:00-06:00"

        # Inside window
        check_time = datetime(2025, 1, 15, 3, 30)  # 3:30 AM
        assert UpdateWindow.is_in_window(window, check_time) is True

        # Outside window
        check_time = datetime(2025, 1, 15, 12, 0)  # Noon
        assert UpdateWindow.is_in_window(window, check_time) is False

    def test_checks_midnight_crossing_window(self):
        """Test checks window that crosses midnight."""
        # Window: 22:00-06:00 (10pm to 6am next day)
        window = "22:00-06:00"

        # Inside window (before midnight)
        check_time = datetime(2025, 1, 15, 23, 30)  # 11:30 PM
        assert UpdateWindow.is_in_window(window, check_time) is True

        # Inside window (after midnight)
        check_time = datetime(2025, 1, 15, 3, 0)  # 3 AM
        assert UpdateWindow.is_in_window(window, check_time) is True

        # Outside window
        check_time = datetime(2025, 1, 15, 12, 0)  # Noon
        assert UpdateWindow.is_in_window(window, check_time) is False

    def test_checks_day_specific_window(self):
        """Test checks window for specific days."""
        # Window: Weekends only, all day
        window = "Sat,Sun:00:00-23:59"

        # Saturday - inside window
        check_time = datetime(2025, 1, 11, 12, 0)  # Saturday noon
        assert UpdateWindow.is_in_window(window, check_time) is True

        # Sunday - inside window
        check_time = datetime(2025, 1, 12, 12, 0)  # Sunday noon
        assert UpdateWindow.is_in_window(window, check_time) is True

        # Monday - outside window (wrong day)
        check_time = datetime(2025, 1, 13, 12, 0)  # Monday noon
        assert UpdateWindow.is_in_window(window, check_time) is False

    def test_checks_day_range_window(self):
        """Test checks window with day range (Mon-Fri)."""
        # Window: Weeknights 10pm-6am
        window = "Mon-Fri:22:00-06:00"

        # Tuesday 11pm - inside window
        check_time = datetime(2025, 1, 14, 23, 0)  # Tuesday 11 PM
        assert UpdateWindow.is_in_window(window, check_time) is True

        # Saturday 11pm - outside window (wrong day)
        check_time = datetime(2025, 1, 11, 23, 0)  # Saturday 11 PM
        assert UpdateWindow.is_in_window(window, check_time) is False

    def test_uses_current_time_when_not_specified(self):
        """Test uses current time when check_time not provided."""
        # Window that's likely to be true at some point
        window = "00:00-23:59"  # All day

        result = UpdateWindow.is_in_window(window)

        # Should return boolean (uses current time)
        assert isinstance(result, bool)

    def test_handles_edge_case_at_exact_start_time(self):
        """Test window boundaries - exact start time."""
        window = "02:00-06:00"
        check_time = datetime(2025, 1, 15, 2, 0)  # Exactly 2:00 AM

        assert UpdateWindow.is_in_window(window, check_time) is True

    def test_handles_edge_case_at_exact_end_time(self):
        """Test window boundaries - exact end time."""
        window = "02:00-06:00"
        check_time = datetime(2025, 1, 15, 6, 0)  # Exactly 6:00 AM

        assert UpdateWindow.is_in_window(window, check_time) is True

    def test_returns_true_on_invalid_format_fail_open(self):
        """Test returns True (fail open) on invalid window format."""
        invalid_windows = [
            "invalid",
            "25:00-26:00",  # Invalid hours
            "NotADay:12:00-14:00",  # Invalid day name
        ]

        for window in invalid_windows:
            check_time = datetime(2025, 1, 15, 12, 0)
            # Should return True (fail open) on parse error
            result = UpdateWindow.is_in_window(window, check_time)
            assert result is True


class TestParseWindow:
    """Test _parse_window() method for format parsing."""

    def test_parses_daily_window(self):
        """Test parses daily time window."""
        days, start_time, end_time = UpdateWindow._parse_window("02:00-06:00")

        assert days is None  # No specific days (daily)
        assert start_time == time(2, 0)
        assert end_time == time(6, 0)

    def test_parses_day_specific_window(self):
        """Test parses day-specific window."""
        days, start_time, end_time = UpdateWindow._parse_window("Sat,Sun:00:00-23:59")

        assert days == {5, 6}  # Saturday=5, Sunday=6
        assert start_time == time(0, 0)
        assert end_time == time(23, 59)

    def test_parses_day_range_window(self):
        """Test parses day range."""
        days, start_time, end_time = UpdateWindow._parse_window("Mon-Fri:09:00-17:00")

        assert days == {0, 1, 2, 3, 4}  # Monday=0 through Friday=4
        assert start_time == time(9, 0)
        assert end_time == time(17, 0)

    def test_parses_midnight_crossing_window(self):
        """Test parses window crossing midnight."""
        days, start_time, end_time = UpdateWindow._parse_window("22:00-06:00")

        assert days is None
        assert start_time == time(22, 0)
        assert end_time == time(6, 0)
        # Caller should handle start > end for midnight crossing

    def test_raises_on_missing_time_separator(self):
        """Test raises ValueError when time separator missing."""
        with pytest.raises(ValueError, match="Invalid time range format"):
            UpdateWindow._parse_window("02:00")  # No end time

    def test_raises_on_invalid_time_format(self):
        """Test raises ValueError on invalid time format."""
        with pytest.raises(ValueError, match="Invalid hour"):
            UpdateWindow._parse_window("25:00-06:00")  # Invalid hour

    def test_handles_whitespace_in_window_string(self):
        """Test handles extra whitespace."""
        days, start_time, end_time = UpdateWindow._parse_window("  02:00 - 06:00  ")

        assert start_time == time(2, 0)
        assert end_time == time(6, 0)


class TestParseDays:
    """Test _parse_days() method for day parsing."""

    def test_parses_single_day(self):
        """Test parses single day name."""
        days = UpdateWindow._parse_days("Mon")
        assert days == {0}  # Monday

        days = UpdateWindow._parse_days("Sun")
        assert days == {6}  # Sunday

    def test_parses_multiple_days_comma_separated(self):
        """Test parses comma-separated days."""
        days = UpdateWindow._parse_days("Sat,Sun")
        assert days == {5, 6}  # Saturday, Sunday

    def test_parses_day_range(self):
        """Test parses day range (Mon-Fri)."""
        days = UpdateWindow._parse_days("Mon-Fri")
        assert days == {0, 1, 2, 3, 4}  # Monday through Friday

    def test_parses_wrapping_day_range(self):
        """Test parses day range that wraps around week (Fri-Mon)."""
        days = UpdateWindow._parse_days("Fri-Mon")
        assert days == {0, 4, 5, 6}  # Friday, Saturday, Sunday, Monday

    def test_parses_mixed_format(self):
        """Test parses mixed format (ranges and single days)."""
        days = UpdateWindow._parse_days("Mon-Wed,Fri,Sun")
        assert days == {0, 1, 2, 4, 6}  # Mon, Tue, Wed, Fri, Sun

    def test_handles_full_day_names(self):
        """Test handles full day names."""
        days = UpdateWindow._parse_days("Monday-Friday")
        assert days == {0, 1, 2, 3, 4}

    def test_case_insensitive(self):
        """Test day parsing is case insensitive."""
        days = UpdateWindow._parse_days("MON-FRI")
        assert days == {0, 1, 2, 3, 4}

        days = UpdateWindow._parse_days("mon-fri")
        assert days == {0, 1, 2, 3, 4}

    def test_raises_on_invalid_day_name(self):
        """Test raises ValueError on invalid day name."""
        with pytest.raises(ValueError, match="Invalid day name"):
            UpdateWindow._parse_days("NotADay")

    def test_raises_on_invalid_day_in_range(self):
        """Test raises ValueError on invalid day in range."""
        with pytest.raises(ValueError, match="Invalid day name"):
            UpdateWindow._parse_days("Mon-NotADay")

    def test_handles_whitespace(self):
        """Test handles whitespace in day specification."""
        days = UpdateWindow._parse_days(" Mon , Fri ")
        assert days == {0, 4}


class TestParseTime:
    """Test _parse_time() method for time parsing."""

    def test_parses_valid_time(self):
        """Test parses valid HH:MM format."""
        assert UpdateWindow._parse_time("02:00") == time(2, 0)
        assert UpdateWindow._parse_time("14:30") == time(14, 30)
        assert UpdateWindow._parse_time("23:59") == time(23, 59)
        assert UpdateWindow._parse_time("00:00") == time(0, 0)

    def test_parses_single_digit_hour(self):
        """Test parses single-digit hour."""
        assert UpdateWindow._parse_time("2:00") == time(2, 0)
        assert UpdateWindow._parse_time("9:30") == time(9, 30)

    def test_raises_on_invalid_format(self):
        """Test raises ValueError on invalid format."""
        with pytest.raises(ValueError, match="Invalid time format"):
            UpdateWindow._parse_time("2")  # Missing minutes

        with pytest.raises(ValueError, match="Invalid time format"):
            UpdateWindow._parse_time("2:00:00")  # Includes seconds

        with pytest.raises(ValueError, match="Invalid time format"):
            UpdateWindow._parse_time("2am")  # AM/PM format

    def test_raises_on_invalid_hour(self):
        """Test raises ValueError on invalid hour."""
        with pytest.raises(ValueError, match="Invalid hour"):
            UpdateWindow._parse_time("24:00")  # Hour 24 is invalid

        with pytest.raises(ValueError, match="Invalid hour"):
            UpdateWindow._parse_time("25:00")  # Hour > 23

        with pytest.raises(ValueError, match="Invalid time format"):
            UpdateWindow._parse_time("-1:00")  # Negative hour (doesn't match regex)

    def test_raises_on_invalid_minute(self):
        """Test raises ValueError on invalid minute."""
        with pytest.raises(ValueError, match="Invalid minute"):
            UpdateWindow._parse_time("12:60")  # Minute 60 is invalid

        with pytest.raises(ValueError, match="Invalid minute"):
            UpdateWindow._parse_time("12:99")  # Minute > 59

        with pytest.raises(ValueError, match="Invalid time format"):
            UpdateWindow._parse_time("12:-1")  # Negative minute (doesn't match regex)


class TestValidateFormat:
    """Test validate_format() method for window validation."""

    def test_validates_empty_window(self):
        """Test validates empty/None window."""
        is_valid, error = UpdateWindow.validate_format(None)
        assert is_valid is True
        assert error is None

        is_valid, error = UpdateWindow.validate_format("")
        assert is_valid is True
        assert error is None

    def test_validates_daily_window(self):
        """Test validates daily time window."""
        is_valid, error = UpdateWindow.validate_format("02:00-06:00")
        assert is_valid is True
        assert error is None

    def test_validates_day_specific_window(self):
        """Test validates day-specific window."""
        is_valid, error = UpdateWindow.validate_format("Sat,Sun:00:00-23:59")
        assert is_valid is True
        assert error is None

    def test_validates_day_range_window(self):
        """Test validates day range window."""
        is_valid, error = UpdateWindow.validate_format("Mon-Fri:09:00-17:00")
        assert is_valid is True
        assert error is None

    def test_validates_midnight_crossing_window(self):
        """Test validates midnight-crossing window."""
        is_valid, error = UpdateWindow.validate_format("22:00-06:00")
        assert is_valid is True
        assert error is None

    def test_rejects_invalid_time_format(self):
        """Test rejects invalid time format."""
        is_valid, error = UpdateWindow.validate_format("25:00-06:00")
        assert is_valid is False
        assert error is not None
        assert "Invalid hour" in error

    def test_rejects_invalid_day_name(self):
        """Test rejects invalid day name."""
        is_valid, error = UpdateWindow.validate_format("NotADay:12:00-14:00")
        assert is_valid is False
        assert error is not None

    def test_rejects_missing_time_separator(self):
        """Test rejects missing time separator."""
        is_valid, error = UpdateWindow.validate_format("12:00")
        assert is_valid is False
        assert error is not None
        assert "Invalid time range format" in error

    def test_rejects_invalid_minute(self):
        """Test rejects invalid minute."""
        is_valid, error = UpdateWindow.validate_format("12:60-14:00")
        assert is_valid is False
        assert error is not None
        assert "Invalid minute" in error


class TestUpdateWindowEdgeCases:
    """Test edge cases and real-world scenarios."""

    def test_handles_all_day_window(self):
        """Test handles all-day window."""
        window = "00:00-23:59"

        # Any time should be inside
        check_time = datetime(2025, 1, 15, 12, 0)
        assert UpdateWindow.is_in_window(window, check_time) is True

    def test_handles_very_narrow_window(self):
        """Test handles very narrow time window."""
        window = "03:00-03:01"  # 1 minute window

        # Inside (exactly at start)
        check_time = datetime(2025, 1, 15, 3, 0)
        assert UpdateWindow.is_in_window(window, check_time) is True

        # Outside (1 minute after)
        check_time = datetime(2025, 1, 15, 3, 2)
        assert UpdateWindow.is_in_window(window, check_time) is False

    def test_handles_business_hours_window(self):
        """Test typical business hours window."""
        window = "Mon-Fri:09:00-17:00"

        # Wednesday 2pm - inside
        check_time = datetime(2025, 1, 15, 14, 0)  # Wednesday
        assert UpdateWindow.is_in_window(window, check_time) is True

        # Saturday 2pm - outside (weekend)
        check_time = datetime(2025, 1, 11, 14, 0)  # Saturday
        assert UpdateWindow.is_in_window(window, check_time) is False

    def test_handles_maintenance_window(self):
        """Test typical maintenance window."""
        window = "Sun:02:00-06:00"  # Sunday 2-6 AM

        # Sunday 3am - inside
        check_time = datetime(2025, 1, 12, 3, 0)  # Sunday
        assert UpdateWindow.is_in_window(window, check_time) is True

        # Sunday 7am - outside (after window)
        check_time = datetime(2025, 1, 12, 7, 0)  # Sunday
        assert UpdateWindow.is_in_window(window, check_time) is False

        # Monday 3am - outside (wrong day)
        check_time = datetime(2025, 1, 13, 3, 0)  # Monday
        assert UpdateWindow.is_in_window(window, check_time) is False

    def test_handles_overnight_shifts(self):
        """Test overnight shift windows."""
        window = "Mon-Fri:18:00-02:00"  # 6pm to 2am weekdays

        # Monday 11pm - inside
        check_time = datetime(2025, 1, 13, 23, 0)  # Monday
        assert UpdateWindow.is_in_window(window, check_time) is True

        # Tuesday 1am - inside (crossed midnight from Monday)
        check_time = datetime(2025, 1, 14, 1, 0)  # Tuesday
        assert UpdateWindow.is_in_window(window, check_time) is True

    def test_day_name_variations(self):
        """Test various day name formats."""
        # Short names
        days1 = UpdateWindow._parse_days("Mon,Wed,Fri")
        # Full names
        days2 = UpdateWindow._parse_days("Monday,Wednesday,Friday")

        assert days1 == days2 == {0, 2, 4}

    def test_weekend_only_window(self):
        """Test weekend-only update window."""
        window = "Sat-Sun:00:00-23:59"

        # Saturday - inside
        check_time = datetime(2025, 1, 11, 15, 0)  # Saturday 3pm
        assert UpdateWindow.is_in_window(window, check_time) is True

        # Sunday - inside
        check_time = datetime(2025, 1, 12, 15, 0)  # Sunday 3pm
        assert UpdateWindow.is_in_window(window, check_time) is True

        # Friday - outside
        check_time = datetime(2025, 1, 10, 15, 0)  # Friday 3pm
        assert UpdateWindow.is_in_window(window, check_time) is False
