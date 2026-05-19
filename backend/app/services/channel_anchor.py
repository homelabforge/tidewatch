"""Stable channel anchor — Phase 5/6 of update-detection-hardening.

Resolves the upstream "stable major" for an image by reading an anchor tag's
manifest config labels, then exposes a state machine that blocks cross-major
beta promotion on images like linuxserver/sonarr where v5 is the upstream
beta line while v4 is the stable line.

The anchor mechanism is opt-in per container. When a container sets
`stable_anchor_tag` (typically "latest"), `resolve_anchor_major` walks the
registry's manifest list, picks the host-platform child, fetches the image
config blob, and extracts a major version from one of these labels (in order):

  1. org.opencontainers.image.version  — modern OCI standard
  2. org.label-schema.version          — older convention
  3. build_version                     — LinuxServer free-form sentence

The fresh-resolution major is then compared against `accepted_anchor_major`
stored on the container. Drift upward is **never** silently accepted as a new
bound; it surfaces as a `channel_shift` so the user can explicitly opt in to
the new upstream major before any v(N+1) candidate is permitted.

Pure-logic helpers in this module avoid all I/O; manifest/blob fetching is
delegated to the per-registry client via `RegistryClient.get_image_labels`.
"""

from __future__ import annotations

import logging
import platform
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from packaging.version import InvalidVersion, Version

if TYPE_CHECKING:
    from app.services.registry_client import RegistryClient

logger = logging.getLogger(__name__)


# Label keys checked in priority order. The first one with a parseable value
# wins. LinuxServer's `build_version` is free-form (e.g. "LinuxServer.io
# version: 4.0.17.2952-ls311 Build-date: ...") so it needs the token regex
# in `extract_anchor_major` rather than direct Version parsing.
ANCHOR_LABEL_KEYS: tuple[str, ...] = (
    "org.opencontainers.image.version",
    "org.label-schema.version",
    "build_version",
)


# Matches a dotted-numeric version token of length >= 2 segments, with optional
# `v` prefix and optional dash/underscore-separated build tail. Allows additional
# `-segments` (``ls300``, ``develop-ls300``) in the tail; `extract_anchor_major`
# strips at the first separator before parsing so noisy tails don't break the
# Version() parse.
_VERSION_TOKEN_RE = re.compile(r"(?:^|[\s:=])v?(\d+(?:\.\d+){1,4}(?:[.\-_][A-Za-z0-9.\-_]+)?)")


# Mapping from Python `platform.machine()` values to OCI/Docker `architecture`
# values seen in manifest list entries. Used by `pick_platform_manifest` to
# select the right child manifest from a multi-arch index.
_HOST_ARCH_MAP: dict[str, str] = {
    "x86_64": "amd64",
    "amd64": "amd64",
    "i386": "386",
    "i686": "386",
    "aarch64": "arm64",
    "arm64": "arm64",
    "armv7l": "arm",
    "armv6l": "arm",
    "ppc64le": "ppc64le",
    "s390x": "s390x",
    "riscv64": "riscv64",
}


def host_arch() -> str:
    """Return the OCI-style architecture name for the running host."""
    return _HOST_ARCH_MAP.get(platform.machine().lower(), "amd64")


@dataclass(frozen=True)
class AnchorResolution:
    """Result of resolving an anchor tag to an upstream major version.

    Attributes:
        anchor_major: Extracted major version (e.g. 4 for Sonarr v4.x stable).
        digest: Manifest digest of the anchor tag.
        source_label: Which label key produced the value
            (e.g. "build_version").
        raw_label_value: Verbatim label value, kept for diagnostic traces and
            UI display.
    """

    anchor_major: int
    digest: str
    source_label: str
    raw_label_value: str


def extract_anchor_major(label_source: str, label_value: str) -> int | None:
    """Extract a major version integer from a label value.

    For canonical labels (OCI image.version, label-schema.version) the value
    is normally a clean version string and `packaging.Version` is tried
    directly. For LinuxServer's free-form `build_version` (and as a fallback
    for the canonical labels when they contain noise), a token regex finds
    the first dotted-numeric version-like substring.

    Returns ``None`` if no version token is recoverable.
    """
    if not label_value:
        return None

    candidates: list[str] = []
    stripped = label_value.strip()

    # For well-known free-form labels, regex-first.
    if label_source == "build_version":
        candidates.extend(m.group(1) for m in _VERSION_TOKEN_RE.finditer(label_value))
        if not candidates and stripped:
            candidates.append(stripped)
    else:
        # OCI / label-schema: try the value as-is first.
        if stripped:
            candidates.append(stripped)
        # Then fall back to regex tokens in case the value has extra prefix
        # text (some images embed marketing strings into image.version).
        candidates.extend(m.group(1) for m in _VERSION_TOKEN_RE.finditer(label_value))

    for candidate in candidates:
        token = candidate.lstrip("vV")
        # Trim a trailing build/qualifier separated by '-' so packaging.Version
        # accepts e.g. "4.0.17.2952-ls311" → "4.0.17.2952".
        for sep in ("-", "_"):
            if sep in token:
                token = token.split(sep, 1)[0]
                break
        try:
            parsed = Version(token)
        except InvalidVersion:
            continue
        if parsed.release:
            return parsed.release[0]

    logger.debug(
        "extract_anchor_major: no parseable token in label %s value=%r",
        label_source,
        label_value[:120],
    )
    return None


def pick_platform_manifest(
    index_manifests: list[dict],
    *,
    preferred_arch: str | None = None,
) -> dict | None:
    """Select the per-platform manifest entry matching the host architecture.

    `index_manifests` is the ``manifests[]`` array from an OCI image index or
    Docker manifest list. Each entry must have `platform.architecture` (and
    optionally `platform.os`) plus a `digest` field.

    Returns the matched entry (with `digest`, `mediaType`, `platform`) or
    ``None`` if no entry matches the preferred arch or `linux/amd64` fallback.
    """
    if not index_manifests:
        return None

    arch = preferred_arch or host_arch()

    def is_linux(entry: dict) -> bool:
        return entry.get("platform", {}).get("os", "linux") == "linux"

    def matches_arch(entry: dict, target_arch: str) -> bool:
        return entry.get("platform", {}).get("architecture") == target_arch and is_linux(entry)

    for entry in index_manifests:
        if matches_arch(entry, arch):
            return entry
    # Fall back to amd64 (most homelab containers are amd64-targeted).
    if arch != "amd64":
        for entry in index_manifests:
            if matches_arch(entry, "amd64"):
                return entry
    # Last resort: any linux entry.
    for entry in index_manifests:
        if is_linux(entry):
            return entry
    return None


def labels_from_config_blob(config_blob: dict) -> dict[str, str]:
    """Extract the Labels map from an image config blob.

    OCI and Docker layouts differ in where the labels live:

      * OCI image config:    ``.config.Labels``
      * Docker image config: ``.config.Labels`` (same key, mostly)
      * Some registries:     ``.container_config.Labels`` (legacy)

    Returns a flat ``dict[str, str]`` of label key → value, or an empty dict
    if no labels are present.
    """
    if not isinstance(config_blob, dict):
        return {}
    for path in (("config", "Labels"), ("container_config", "Labels")):
        node: object = config_blob
        for key in path:
            if isinstance(node, dict):
                node = node.get(key)
            else:
                node = None
                break
        if isinstance(node, dict):
            return {str(k): str(v) for k, v in node.items() if v is not None}
    return {}


async def resolve_anchor_major(
    client: RegistryClient,
    image: str,
    anchor_tag: str,
) -> AnchorResolution | None:
    """Resolve the anchor tag's manifest labels into an upstream major version.

    Delegates the network calls to the registry client's
    `get_image_labels(image, tag)` helper, which is responsible for:

      * fetching the manifest (with multi-arch index handling),
      * picking the host-platform child manifest,
      * fetching the image config blob,
      * returning ``(labels, digest)`` or ``None`` on failure.

    Pure-logic label scanning happens here so it stays unit-testable without
    touching the network.

    Returns ``None`` if no usable label is found. Callers treat ``None`` as
    "no anchor available" and fall through to existing behavior — the anchor
    is fail-open in the sense that resolution failures do not erroneously
    *raise* the allowed bound, but the caller is responsible for preserving
    any previously accepted bound rather than relaxing to "no bound".
    """
    try:
        result = await client.get_image_labels(image, anchor_tag)
    except Exception as exc:  # noqa: BLE001 — fail-closed against unexpected errors
        logger.warning(
            "resolve_anchor_major: client.get_image_labels failed for %s:%s — %s",
            image,
            anchor_tag,
            exc,
        )
        return None

    if not result:
        logger.debug("resolve_anchor_major: no manifest labels for %s:%s", image, anchor_tag)
        return None

    labels, digest = result
    if not labels:
        return None

    for key in ANCHOR_LABEL_KEYS:
        value = labels.get(key)
        if not value:
            continue
        major = extract_anchor_major(key, value)
        if major is not None:
            return AnchorResolution(
                anchor_major=major,
                digest=digest,
                source_label=key,
                raw_label_value=value,
            )

    logger.info(
        "resolve_anchor_major: %s:%s has labels but none parsed to a major: %s",
        image,
        anchor_tag,
        sorted(labels.keys()),
    )
    return None


class AnchorCache:
    """In-process cache for anchor resolutions with a short TTL.

    Mutable anchor tags like ``latest`` can change frequently, so this cache
    deliberately uses a 5-minute TTL — shorter than the 15-minute
    `TagCache` used for tag list responses. Keyed on
    ``(registry, image, anchor_tag)``.
    """

    def __init__(self, ttl_minutes: int = 5) -> None:
        self._ttl = timedelta(minutes=ttl_minutes)
        self._store: dict[tuple[str, str, str], tuple[AnchorResolution, datetime]] = {}

    def get(self, registry: str, image: str, anchor_tag: str) -> AnchorResolution | None:
        key = (registry.lower(), image, anchor_tag)
        entry = self._store.get(key)
        if entry is None:
            return None
        resolution, stored_at = entry
        if datetime.now(UTC) - stored_at > self._ttl:
            del self._store[key]
            return None
        return resolution

    def set(self, registry: str, image: str, anchor_tag: str, resolution: AnchorResolution) -> None:
        key = (registry.lower(), image, anchor_tag)
        self._store[key] = (resolution, datetime.now(UTC))

    def invalidate(self, registry: str, image: str, anchor_tag: str) -> None:
        self._store.pop((registry.lower(), image, anchor_tag), None)

    def clear(self) -> None:
        self._store.clear()


# Process-global anchor cache. Re-keyed per request via the cache helper above.
_anchor_cache = AnchorCache(ttl_minutes=5)


def get_anchor_cache() -> AnchorCache:
    """Access the process-global anchor cache."""
    return _anchor_cache


@dataclass(frozen=True)
class AnchorDecision:
    """Result of the fresh-vs-accepted anchor state machine.

    Attributes:
        upper_major_bound: The major above which candidates must be rejected.
            ``None`` means no anchor bound is active (anchor disabled or
            fresh resolution failed without a prior accepted value).
        fresh: The most recent successful resolution this check, if any.
        channel_shift: True when the fresh resolution moved the major above
            the accepted bound. The caller is expected to surface this as a
            channel_shift update kind rather than silently raise the bound.
    """

    upper_major_bound: int | None
    fresh: AnchorResolution | None
    channel_shift: bool


def decide_anchor_bound(
    *,
    accepted_anchor_major: int | None,
    fresh: AnchorResolution | None,
) -> AnchorDecision:
    """Compute the active upper-major bound given prior + fresh resolutions.

    Phase 5.4 state machine:

      * If the user has not opted in (`accepted_anchor_major is None` and no
        fresh resolution), there is no bound to enforce.
      * If we cannot resolve fresh (network failure, missing labels), preserve
        the accepted bound — never relax to "no bound".
      * If fresh ≤ accepted, the anchor is unchanged or moved backward (e.g.
        rebuild, rollback). Keep the accepted bound.
      * If fresh > accepted, **do not** raise the bound. Surface
        `channel_shift=True`; the caller must require explicit user acceptance
        before any candidate >= fresh.anchor_major is permitted.
    """
    # Feature disabled outright.
    if accepted_anchor_major is None and fresh is None:
        return AnchorDecision(upper_major_bound=None, fresh=None, channel_shift=False)

    # Feature enabled but no accepted baseline yet — first successful
    # resolution becomes the implicit baseline. We still return it as the
    # bound; callers that distinguish "initial enable" vs "later check" use
    # the absence of accepted_anchor_major as the signal to persist it.
    if accepted_anchor_major is None and fresh is not None:
        return AnchorDecision(
            upper_major_bound=fresh.anchor_major,
            fresh=fresh,
            channel_shift=False,
        )

    # Accepted exists; fresh failed. Preserve accepted bound.
    if fresh is None:
        return AnchorDecision(
            upper_major_bound=accepted_anchor_major,
            fresh=None,
            channel_shift=False,
        )

    # Both present. Compare.
    if fresh.anchor_major <= (accepted_anchor_major or 0):
        return AnchorDecision(
            upper_major_bound=accepted_anchor_major,
            fresh=fresh,
            channel_shift=False,
        )

    # fresh > accepted — channel shift. Keep the bound at the accepted major.
    return AnchorDecision(
        upper_major_bound=accepted_anchor_major,
        fresh=fresh,
        channel_shift=True,
    )
