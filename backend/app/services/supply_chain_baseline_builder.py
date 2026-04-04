"""Supply chain baseline builder.

Manages trusted image baselines for anomaly detection.
Baselines are keyed by (registry, image, version_track).
"""

import asyncio
import json
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.supply_chain_baseline import SupplyChainBaseline
from app.services.registry_client import RegistryClientFactory

logger = logging.getLogger(__name__)


async def _docker_image_inspect(image_ref: str) -> dict | None:
    """Inspect a local Docker image via CLI.

    Uses the Docker socket proxy that TideWatch already has access to.
    Returns parsed JSON or None on failure.
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            "docker",
            "image",
            "inspect",
            "--format",
            "{{json .}}",
            image_ref,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10.0)
        if proc.returncode != 0:
            logger.debug(
                "docker image inspect failed for %s: %s",
                image_ref,
                stderr.decode().strip(),
            )
            return None
        return json.loads(stdout.decode())
    except (TimeoutError, json.JSONDecodeError, OSError) as e:
        logger.debug("docker image inspect error for %s: %s", image_ref, e)
        return None


class BaselineBuilder:
    """Manages supply chain baselines for image trust."""

    @staticmethod
    async def get_baseline(
        db: AsyncSession,
        registry: str,
        image: str,
        version_track: str | None,
    ) -> SupplyChainBaseline | None:
        """Get existing baseline for an image."""
        result = await db.execute(
            select(SupplyChainBaseline).where(
                SupplyChainBaseline.registry == registry,
                SupplyChainBaseline.image == image,
                SupplyChainBaseline.version_track == version_track,
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def advance_baseline(
        db: AsyncSession,
        registry: str,
        image: str,
        version_track: str | None,
        tag: str,
        digest: str,
        size_bytes: int | None,
    ) -> None:
        """Advance baseline from a trusted observation.

        Called ONLY after a clean, non-held apply succeeds.
        """
        baseline = await BaselineBuilder.get_baseline(db, registry, image, version_track)

        if baseline:
            baseline.last_trusted_tag = tag
            baseline.last_trusted_digest = digest
            if size_bytes is not None:
                baseline.last_trusted_size_bytes = size_bytes
            baseline.sample_count = (baseline.sample_count or 0) + 1
        else:
            baseline = SupplyChainBaseline(
                registry=registry,
                image=image,
                version_track=version_track,
                last_trusted_tag=tag,
                last_trusted_digest=digest,
                last_trusted_size_bytes=size_bytes,
                sample_count=1,
            )
            db.add(baseline)

        await db.flush()

    @staticmethod
    async def bootstrap_from_current(
        db: AsyncSession,
        registry: str,
        image: str,
        version_track: str | None,
        current_tag: str,
    ) -> None:
        """Seed baseline from locally running image via Docker inspect.

        Uses `docker image inspect` to get the actual RepoDigest and Size
        of the image deployed on this host, NOT whatever the registry
        currently serves for that tag.

        Falls back to registry get_tag_metadata() if inspect fails.
        """
        digest: str | None = None
        size: int | None = None

        # Primary: local Docker inspect (actual deployed image)
        image_ref = f"{image}:{current_tag}"
        # For registries that use full image refs (e.g., ghcr.io/org/app)
        if registry not in ("dockerhub", "docker.io"):
            registry_prefix = registry
            if registry == "ghcr":
                registry_prefix = "ghcr.io"
            elif registry == "lscr":
                registry_prefix = "lscr.io"
            elif registry == "gcr":
                registry_prefix = "gcr.io"
            elif registry == "quay":
                registry_prefix = "quay.io"
            image_ref = f"{registry_prefix}/{image}:{current_tag}"

        try:
            result = await _docker_image_inspect(image_ref)
            if result:
                repo_digests = result.get("RepoDigests", [])
                if repo_digests:
                    # RepoDigests entries look like "registry/image@sha256:abc123"
                    digest = repo_digests[0].split("@")[-1]
                size = result.get("Size")
        except Exception:
            logger.warning("Docker inspect failed for %s, falling back to registry", image_ref)

        # Fallback: registry metadata
        if not digest:
            try:
                client = await RegistryClientFactory.get_client(registry, db)
                try:
                    meta = await client.get_tag_metadata(image, current_tag)
                finally:
                    await client.close()
                if meta:
                    digest = meta.get("digest")
                    size = meta.get("full_size")
            except Exception:
                logger.warning(
                    "Registry fallback also failed for %s/%s:%s",
                    registry,
                    image,
                    current_tag,
                )

        if digest:
            await BaselineBuilder.advance_baseline(
                db, registry, image, version_track, current_tag, digest, size
            )
            logger.info(
                "Bootstrapped baseline for %s/%s (track=%s) from %s",
                registry,
                image,
                version_track,
                "local Docker" if digest else "registry",
            )
        else:
            logger.warning(
                "Could not bootstrap baseline for %s/%s:%s — no digest available",
                registry,
                image,
                current_tag,
            )
