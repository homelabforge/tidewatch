"""SSRF validation for ntfy/Gotify/email notifiers + non-fatal dispatcher skip (#4).

ntfy/Gotify now use validate_integration_url (block private/metadata unless
TIDEWATCH_TRUSTED_HOSTS); email validates the SMTP host; slack/discord keep their
strict policy (block private even when trusted-host is set); the dispatcher skips
a blocked notifier instead of aborting all notifications.
"""

from unittest.mock import patch

import pytest

from app.exceptions import SSRFProtectionError
from app.services.notifications.email import EmailNotificationService
from app.services.notifications.gotify import GotifyNotificationService
from app.services.notifications.ntfy import NtfyNotificationService
from app.services.notifications.slack import SlackNotificationService


class TestNtfySSRF:
    def test_blocks_private_ip(self):
        with pytest.raises(SSRFProtectionError):
            NtfyNotificationService("http://10.0.0.5", "topic")

    def test_blocks_localhost(self):
        with pytest.raises(SSRFProtectionError):
            NtfyNotificationService("http://localhost", "topic")

    def test_blocks_metadata_endpoint(self):
        with pytest.raises(SSRFProtectionError):
            NtfyNotificationService("http://169.254.169.254", "topic")

    def test_allows_trusted_host(self, monkeypatch):
        monkeypatch.setenv("TIDEWATCH_TRUSTED_HOSTS", "10.0.0.5")
        svc = NtfyNotificationService("http://10.0.0.5", "topic")
        assert svc.server_url == "http://10.0.0.5"

    def test_allows_trusted_cidr(self, monkeypatch):
        monkeypatch.setenv("TIDEWATCH_TRUSTED_HOSTS", "10.0.0.0/8")
        svc = NtfyNotificationService("http://10.0.0.5", "topic")
        assert svc.server_url == "http://10.0.0.5"

    def test_allows_public(self):
        with patch("app.utils.url_validation.resolve_hostname", return_value="93.184.216.34"):
            svc = NtfyNotificationService("https://ntfy.sh", "topic")
        assert svc.server_url == "https://ntfy.sh"


class TestGotifySSRF:
    def test_blocks_private_ip(self):
        with pytest.raises(SSRFProtectionError):
            GotifyNotificationService("http://192.168.1.10", "token")

    def test_blocks_metadata_endpoint(self):
        with pytest.raises(SSRFProtectionError):
            GotifyNotificationService("http://169.254.169.254", "token")

    def test_allows_trusted_host(self, monkeypatch):
        monkeypatch.setenv("TIDEWATCH_TRUSTED_HOSTS", "192.168.1.10")
        svc = GotifyNotificationService("http://192.168.1.10", "token")
        assert svc.server_url == "http://192.168.1.10"

    def test_allows_public(self):
        with patch("app.utils.url_validation.resolve_hostname", return_value="93.184.216.34"):
            svc = GotifyNotificationService("https://gotify.example.com", "token")
        assert svc.server_url == "https://gotify.example.com"


class TestEmailSSRF:
    _ARGS = ("user", "pass", "from@example.com", "to@example.com")

    def test_blocks_private_host(self):
        with pytest.raises(SSRFProtectionError):
            EmailNotificationService("10.0.0.5", 587, *self._ARGS)

    def test_blocks_loopback(self):
        with pytest.raises(SSRFProtectionError):
            EmailNotificationService("127.0.0.1", 587, *self._ARGS)

    def test_allows_trusted_host(self, monkeypatch):
        monkeypatch.setenv("TIDEWATCH_TRUSTED_HOSTS", "10.0.0.5")
        svc = EmailNotificationService("10.0.0.5", 587, *self._ARGS)
        assert svc.smtp_host == "10.0.0.5"

    def test_allows_public(self):
        with patch(
            "app.utils.url_validation.socket.getaddrinfo",
            return_value=[(2, 1, 6, "", ("93.184.216.34", 587))],
        ):
            svc = EmailNotificationService("smtp.example.com", 587, *self._ARGS)
        assert svc.smtp_host == "smtp.example.com"


class TestSlackDiscordUnchanged:
    def test_slack_blocks_private_even_when_trusted(self, monkeypatch):
        """Proves the strict slack/discord policy is intact: a private host is
        still blocked even with TIDEWATCH_TRUSTED_HOSTS set."""
        monkeypatch.setenv("TIDEWATCH_TRUSTED_HOSTS", "10.0.0.5")
        with pytest.raises(SSRFProtectionError):
            SlackNotificationService("https://10.0.0.5/services/webhook")


class TestDispatcherSkipsBlockedService:
    async def test_blocked_ntfy_skipped_not_fatal(self, db):
        from app.services.notifications.dispatcher import NotificationDispatcher
        from app.services.settings_service import SettingsService

        await SettingsService.set(db, "notify_updates_enabled", "true")
        await SettingsService.set(db, "notify_updates_available", "true")
        await SettingsService.set(db, "ntfy_enabled", "true")
        await SettingsService.set(db, "ntfy_server", "http://10.0.0.5")
        await SettingsService.set(db, "ntfy_topic", "tw")
        await SettingsService.set(db, "ntfy_token", "tok")

        dispatcher = NotificationDispatcher(db)
        # Must not raise even though the ntfy URL is blocked.
        results = await dispatcher.dispatch("update_available", "Title", "Body")
        assert "ntfy" not in results
