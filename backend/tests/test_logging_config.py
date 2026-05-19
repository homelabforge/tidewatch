"""Tests for the granian access-log filter and pretty/plain log handler config.

Covers:
- HealthCheckLogFilter suppresses successful /health and /healthz lines.
- Filter passes through failures so flapping liveness checks stay visible.
- Filter does not over-match adjacent paths like /health-status.
- Filter passes through unrelated request lines unchanged.
- Filter ignores messages that don't match the access-log shape.
- aiosqlite datetime deprecation is silenced by registering an ISO adapter.
"""

from __future__ import annotations

import logging
import warnings
from datetime import datetime

import pytest

# ─── HealthCheckLogFilter ─────────────────────────────────────────────────────


@pytest.fixture
def filter_instance():
    from app.main import HealthCheckLogFilter

    return HealthCheckLogFilter()


def _make_record(msg: str) -> logging.LogRecord:
    return logging.LogRecord(
        name="granian.access",
        level=logging.INFO,
        pathname=__file__,
        lineno=0,
        msg=msg,
        args=None,
        exc_info=None,
    )


@pytest.mark.parametrize(
    "path",
    ["/health", "/healthz"],
)
def test_filter_suppresses_successful_health_probe(filter_instance, path):
    record = _make_record(f'127.0.0.1 - "GET {path} HTTP/1.1" 200 0')
    assert filter_instance.filter(record) is False


@pytest.mark.parametrize(
    "status",
    [400, 401, 500, 503],
)
def test_filter_passes_through_health_failures(filter_instance, status):
    record = _make_record(f'127.0.0.1 - "GET /health HTTP/1.1" {status} 0')
    assert filter_instance.filter(record) is True


def test_filter_does_not_match_adjacent_path(filter_instance):
    """`/health-status` is NOT `/health` — the old substring match would drop it."""
    record = _make_record('127.0.0.1 - "GET /health-status HTTP/1.1" 200 0')
    assert filter_instance.filter(record) is True


def test_filter_passes_through_unrelated_request(filter_instance):
    record = _make_record('127.0.0.1 - "GET /api/containers HTTP/1.1" 200 1234')
    assert filter_instance.filter(record) is True


def test_filter_passes_through_non_access_log_line(filter_instance):
    """A log line that doesn't match the access pattern (e.g. a startup
    message accidentally routed to granian.access) must pass through."""
    record = _make_record("granian started on 0.0.0.0:8788")
    assert filter_instance.filter(record) is True


def test_filter_respects_query_string(filter_instance):
    record = _make_record('127.0.0.1 - "GET /health?probe=1 HTTP/1.1" 200 0')
    assert filter_instance.filter(record) is False


def test_filter_handles_head_method(filter_instance):
    record = _make_record('127.0.0.1 - "HEAD /healthz HTTP/1.1" 200 0')
    assert filter_instance.filter(record) is False


# ─── aiosqlite datetime adapter ───────────────────────────────────────────────


def test_datetime_adapter_no_deprecation_warning():
    """Importing app.database must register custom datetime adapters so the
    Python 3.12+ default-adapter deprecation no longer fires."""
    import sqlite3

    import app.database  # noqa: F401 — side effect registers adapters

    with warnings.catch_warnings():
        warnings.simplefilter("error", category=DeprecationWarning)
        conn = sqlite3.connect(":memory:")
        try:
            conn.execute("CREATE TABLE t (ts TIMESTAMP)")
            # Binding a datetime as a parameter is what trips the default
            # adapter deprecation on Python 3.12+. Our registered adapter
            # converts it to ISO 8601 without touching the deprecated path.
            conn.execute("INSERT INTO t VALUES (?)", (datetime(2026, 5, 19, 12, 0, 0),))
            conn.commit()
            row = conn.execute("SELECT ts FROM t").fetchone()
        finally:
            conn.close()

    assert row[0].startswith("2026-05-19T")


# ─── pretty log handler ───────────────────────────────────────────────────────


def test_pretty_log_handler_uses_rich(monkeypatch):
    """When TIDEWATCH_LOG_PRETTY=true, _configure_logging installs RichHandler."""
    from rich.logging import RichHandler

    from app import main as app_main

    monkeypatch.setenv("TIDEWATCH_LOG_PRETTY", "true")
    app_main._configure_logging()

    root = logging.getLogger()
    assert any(isinstance(h, RichHandler) for h in root.handlers), [
        type(h).__name__ for h in root.handlers
    ]


def test_plain_log_handler_when_pretty_disabled(monkeypatch):
    from app import main as app_main

    monkeypatch.setenv("TIDEWATCH_LOG_PRETTY", "false")
    app_main._configure_logging()

    root = logging.getLogger()
    # Must not be RichHandler — plain StreamHandler only.
    try:
        from rich.logging import RichHandler

        assert not any(isinstance(h, RichHandler) for h in root.handlers)
    except ImportError:
        pass  # rich not installed — handler can only be StreamHandler


def test_pretty_log_falls_back_when_rich_missing(monkeypatch):
    """If rich isn't installed at runtime, we degrade to plain logging
    instead of raising — TIDEWATCH_LOG_PRETTY=true should not crash startup."""
    import builtins

    from app import main as app_main

    monkeypatch.setenv("TIDEWATCH_LOG_PRETTY", "true")
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "rich.logging" or name.startswith("rich.logging."):
            raise ImportError("simulated missing rich")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    # Should not raise
    app_main._configure_logging()

    root = logging.getLogger()
    assert root.handlers, "expected at least one handler after fallback"
