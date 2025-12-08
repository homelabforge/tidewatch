"""Notification services package for TideWatch."""

from app.services.notifications.base import NotificationService
from app.services.notifications.dispatcher import NotificationDispatcher

__all__ = ["NotificationService", "NotificationDispatcher"]
