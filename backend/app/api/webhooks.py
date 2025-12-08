"""API endpoints for webhook management."""

import logging
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.services.auth import require_auth
from app.services.webhook_service import WebhookService
from app.schemas.webhook import (
    WebhookCreate,
    WebhookUpdate,
    WebhookSchema,
    WebhookTestResponse,
)
from app.utils.error_handling import safe_error_response

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/", response_model=List[WebhookSchema], status_code=status.HTTP_200_OK)
async def list_webhooks(
    admin: Optional[dict] = Depends(require_auth),
    db: AsyncSession = Depends(get_db)
) -> List[WebhookSchema]:
    """List all webhooks.

    Args:
        admin: Authenticated admin user
        db: Database session

    Returns:
        List of all configured webhooks
    """
    try:
        webhooks = await WebhookService.list_webhooks(db)
        return webhooks
    except Exception as e:
        safe_error_response(logger, e, "Failed to list webhooks")


@router.post("/", response_model=WebhookSchema, status_code=status.HTTP_201_CREATED)
async def create_webhook(
    webhook: WebhookCreate,
    admin: Optional[dict] = Depends(require_auth),
    db: AsyncSession = Depends(get_db)
) -> WebhookSchema:
    """Create a new webhook.

    SSRF Protection: Webhook URLs pointing to private/internal IPs are blocked.

    Args:
        webhook: Webhook configuration
        admin: Authenticated admin user
        db: Database session

    Returns:
        Created webhook

    Raises:
        400: Invalid webhook configuration or SSRF attempt
        409: Webhook with same name already exists
    """
    try:
        created_webhook = await WebhookService.create_webhook(db, webhook)
        return created_webhook
    except ValueError as e:
        # SSRF protection or validation error
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        # Check for unique constraint violation
        if "UNIQUE constraint failed" in str(e) or "unique" in str(e).lower():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Webhook with name '{webhook.name}' already exists"
            )
        safe_error_response(logger, e, "Failed to create webhook")


@router.get("/{webhook_id}", response_model=WebhookSchema, status_code=status.HTTP_200_OK)
async def get_webhook(
    webhook_id: int,
    admin: Optional[dict] = Depends(require_auth),
    db: AsyncSession = Depends(get_db)
) -> WebhookSchema:
    """Get webhook by ID.

    Args:
        webhook_id: Webhook ID
        admin: Authenticated admin user
        db: Database session

    Returns:
        Webhook details

    Raises:
        404: Webhook not found
    """
    webhook = await WebhookService.get_webhook(db, webhook_id)
    if not webhook:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Webhook with ID {webhook_id} not found"
        )
    return webhook


@router.put("/{webhook_id}", response_model=WebhookSchema, status_code=status.HTTP_200_OK)
async def update_webhook(
    webhook_id: int,
    webhook: WebhookUpdate,
    admin: Optional[dict] = Depends(require_auth),
    db: AsyncSession = Depends(get_db)
) -> WebhookSchema:
    """Update an existing webhook.

    Args:
        webhook_id: Webhook ID
        webhook: Updated webhook data
        admin: Authenticated admin user
        db: Database session

    Returns:
        Updated webhook

    Raises:
        400: Invalid webhook configuration or SSRF attempt
        404: Webhook not found
    """
    try:
        updated_webhook = await WebhookService.update_webhook(db, webhook_id, webhook)
        if not updated_webhook:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Webhook with ID {webhook_id} not found"
            )
        return updated_webhook
    except ValueError as e:
        # SSRF protection or validation error
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        safe_error_response(logger, e, "Failed to update webhook")


@router.delete("/{webhook_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_webhook(
    webhook_id: int,
    admin: Optional[dict] = Depends(require_auth),
    db: AsyncSession = Depends(get_db)
):
    """Delete a webhook.

    Args:
        webhook_id: Webhook ID
        admin: Authenticated admin user
        db: Database session

    Raises:
        404: Webhook not found
    """
    deleted = await WebhookService.delete_webhook(db, webhook_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Webhook with ID {webhook_id} not found"
        )


@router.post("/{webhook_id}/test", response_model=WebhookTestResponse, status_code=status.HTTP_200_OK)
async def test_webhook(
    webhook_id: int,
    admin: Optional[dict] = Depends(require_auth),
    db: AsyncSession = Depends(get_db)
) -> WebhookTestResponse:
    """Send a test payload to a webhook.

    Args:
        webhook_id: Webhook ID
        admin: Authenticated admin user
        db: Database session

    Returns:
        Test result with success status and details

    Raises:
        404: Webhook not found
    """
    result = await WebhookService.test_webhook(db, webhook_id)

    # If webhook not found, return 404
    if not result.success and result.error == "Webhook not found":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Webhook not found"
        )

    return result
