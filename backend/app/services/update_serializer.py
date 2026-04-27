"""Serialize Update ORM rows to UpdateSchema with self-managed enrichment.

The frontend renders a "self-managed" badge plus the manual update instructions
when an update targets infrastructure that TideWatch can't safely auto-manage
(see app.services.protected_infra). Pydantic can't derive those fields from
the Update row alone — they need a join against the Container table — so this
module owns the enrichment.

Bulk path uses a single SELECT against Container even for large batches.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.container import Container
from app.models.update import Update
from app.schemas.update import UpdateSchema
from app.services.protected_infra import (
    SelfManagedInfraError,
    is_self_managed_infrastructure,
)


async def enrich_updates(db: AsyncSession, updates: list[Update]) -> list[UpdateSchema]:
    """Bulk-enrich Update rows with self-managed metadata.

    Args:
        db: Active async session.
        updates: Update ORM rows. May be empty.

    Returns:
        Same length as ``updates``, in the same order, as UpdateSchema instances.
        Self-managed entries have ``self_managed=True`` and a populated
        ``manual_update_instructions`` string.
    """
    if not updates:
        return []

    container_ids = {u.container_id for u in updates}
    result = await db.execute(select(Container).where(Container.id.in_(container_ids)))
    by_id = {c.id: c for c in result.scalars().all()}

    out: list[UpdateSchema] = []
    for u in updates:
        schema = UpdateSchema.model_validate(u)
        container = by_id.get(u.container_id)
        if container and is_self_managed_infrastructure(container):
            schema.self_managed = True
            # Reuse the exception's instruction-builder so apply guards,
            # rollback guards, and the serializer all produce identical text.
            err = SelfManagedInfraError(
                container.name,
                operation="apply",
                target_tag=u.to_tag,
                compose_file=container.compose_file,
                compose_project=container.compose_project,
                service_name=container.service_name,
            )
            schema.manual_update_instructions = err.manual_update_instructions
        out.append(schema)
    return out


async def enrich_update(db: AsyncSession, update: Update) -> UpdateSchema:
    """Single-row helper that uses the bulk path internally."""
    enriched = await enrich_updates(db, [update])
    return enriched[0]
