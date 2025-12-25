"""Changelog fetchers for deriving update reasons."""

import logging
import re
from dataclasses import dataclass
from typing import Optional, Tuple

import httpx
from html2text import HTML2Text

from app.utils.security import sanitize_log_message

logger = logging.getLogger(__name__)


@dataclass
class ChangelogResult:
    raw_text: str
    source: str
    tag: Optional[str] = None
    title: Optional[str] = None
    url: Optional[str] = None


class ChangelogFetcher:
    """Fetch release notes from a configured source."""

    def __init__(self, github_token: Optional[str] = None) -> None:
        self.github_token = github_token

    def _is_html_content(self, text: str) -> bool:
        """Detect if content is HTML rather than markdown.

        Checks for common HTML tags and doctype declarations.
        """
        if not text or len(text.strip()) < 10:
            return False

        text_lower = text.lower().strip()

        # Check for HTML doctype or opening tag
        if text_lower.startswith("<!doctype html") or text_lower.startswith("<html"):
            return True

        # Check for common HTML tags (must appear early in content)
        html_indicators = [
            "<div",
            "<p>",
            "<span",
            "<h1>",
            "<h2>",
            "<h3>",
            "<ul>",
            "<ol>",
            "<table",
            "<br>",
            "<br/>",
        ]
        first_500_chars = text_lower[:500]

        # Count HTML tag occurrences
        html_tag_count = sum(
            1 for indicator in html_indicators if indicator in first_500_chars
        )

        # If 3+ HTML tags found in first 500 chars, likely HTML
        return html_tag_count >= 3

    def _convert_html_to_markdown(self, html_content: str) -> str:
        """Convert HTML content to clean markdown.

        Args:
            html_content: Raw HTML string

        Returns:
            Markdown-formatted string
        """
        try:
            # Configure html2text converter
            h = HTML2Text()
            h.ignore_links = False  # Keep links
            h.ignore_images = False  # Keep images
            h.ignore_emphasis = False  # Keep bold/italic
            h.body_width = 0  # No line wrapping
            h.unicode_snob = True  # Use unicode characters
            h.skip_internal_links = True  # Skip anchor links
            h.ignore_tables = False  # Convert tables to markdown
            h.default_image_alt = ""  # Don't add default alt text
            h.protect_links = True  # Don't mangle URLs
            h.wrap_links = False  # Don't wrap link text

            # Convert HTML to markdown
            markdown = h.handle(html_content)

            # Clean up common issues
            markdown = markdown.strip()

            # Remove excessive newlines (more than 2 consecutive)
            markdown = re.sub(r"\n{3,}", "\n\n", markdown)

            logger.info("Successfully converted HTML to markdown")
            return markdown

        except Exception as e:
            logger.error(
                f"Failed to convert HTML to markdown: {sanitize_log_message(str(e))}"
            )
            # Fallback: return original content with HTML stripped
            stripped = re.sub(r"<[^>]+>", "", html_content)
            return stripped.strip()

    async def fetch(
        self, source: Optional[str], image: str, tag: str
    ) -> Optional[ChangelogResult]:
        if not source:
            return None

        result = None
        if source.startswith("github:"):
            owner_repo = source.split(":", 1)[1]
            result = await self._fetch_github_release(owner_repo, tag)
        elif source.startswith("https://") or source.startswith("http://"):
            result = await self._fetch_url(source)
        elif "/" in source and not source.startswith(
            ("http://", "https://", "github:")
        ):
            # Handle bare owner/repo format as GitHub repository
            logger.debug(
                f"Treating '{sanitize_log_message(str(source))}' as GitHub repository for {sanitize_log_message(str(image))}"
            )
            result = await self._fetch_github_release(source, tag)
        else:
            logger.debug(
                f"Unsupported release source '{sanitize_log_message(str(source))}' for {sanitize_log_message(str(image))}"
            )
            return None

        if not result:
            return None

        # Convert HTML to Markdown if needed
        if self._is_html_content(result.raw_text):
            logger.info(
                f"Detected HTML content from {sanitize_log_message(str(source))}, converting to markdown"
            )
            result.raw_text = self._convert_html_to_markdown(result.raw_text)

        return result

    async def _fetch_url(self, url: str) -> Optional[ChangelogResult]:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(url)
                response.raise_for_status()
                return ChangelogResult(raw_text=response.text, source=url)
        except httpx.HTTPStatusError as e:
            logger.warning(
                f"HTTP error fetching changelog from {sanitize_log_message(str(url))}: {sanitize_log_message(str(e))}"
            )
            return None
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            logger.warning(
                f"Connection error fetching changelog from {sanitize_log_message(str(url))}: {sanitize_log_message(str(e))}"
            )
            return None
        except (ValueError, KeyError) as e:
            logger.warning(
                f"Invalid response fetching changelog from {sanitize_log_message(str(url))}: {sanitize_log_message(str(e))}"
            )
            return None

    async def _fetch_github_release(
        self, owner_repo: str, tag: str
    ) -> Optional[ChangelogResult]:
        # Validate owner_repo format to prevent path traversal in URL construction
        # Valid format: owner/repo (alphanumeric, hyphens, underscores, dots)
        import re

        if not re.match(r"^[a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+$", owner_repo):
            logger.warning(
                f"Invalid GitHub repository format: {sanitize_log_message(str(owner_repo))}"
            )
            return None

        # Try multiple tag formats (some repos use v prefix, version/ prefix, etc.)
        tag_variations = [
            tag,  # exact tag (e.g., "2025.10.2")
            f"v{tag}",  # v prefix (e.g., "v2025.10.2")
            f"version/{tag}",  # version prefix (e.g., "version/2025.10.2")
            tag.lstrip("v"),  # without v prefix if it has one
        ]
        # Remove duplicates while preserving order
        seen = set()
        tag_variations = [t for t in tag_variations if not (t in seen or seen.add(t))]

        headers = {"Accept": "application/vnd.github+json"}
        if self.github_token:
            headers["Authorization"] = f"Bearer {self.github_token}"

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                for tag_variant in tag_variations:
                    # URL is constrained to api.github.com, owner_repo validated above
                    api_url = f"https://api.github.com/repos/{owner_repo}/releases/tags/{tag_variant}"
                    response = await client.get(api_url, headers=headers)

                    if response.status_code == 404:
                        logger.debug(
                            f"GitHub release {sanitize_log_message(str(owner_repo))}@{sanitize_log_message(str(tag_variant))} not found, trying next variant"
                        )
                        continue

                    response.raise_for_status()
                    data = response.json()
                    body = data.get("body") or ""
                    if not body.strip():
                        logger.info(
                            f"GitHub release {sanitize_log_message(str(owner_repo))}@{sanitize_log_message(str(tag_variant))} has no body text"
                        )
                        return None

                    logger.info(
                        f"Found GitHub release {sanitize_log_message(str(owner_repo))}@{sanitize_log_message(str(tag_variant))}"
                    )
                    return ChangelogResult(
                        raw_text=body,
                        source=api_url,
                        tag=tag_variant,
                        title=data.get("name"),
                        url=data.get("html_url"),
                    )

                logger.info(
                    f"GitHub release {sanitize_log_message(str(owner_repo))}@{sanitize_log_message(str(tag))} not found (tried {sanitize_log_message(str(len(tag_variations)))} variations)"
                )
                return None
        except httpx.HTTPStatusError as e:
            logger.warning(
                f"HTTP error fetching GitHub release for {sanitize_log_message(str(owner_repo))}@{sanitize_log_message(str(tag))}: {sanitize_log_message(str(e))}"
            )
            return None
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            logger.warning(
                f"Connection error fetching GitHub release for {sanitize_log_message(str(owner_repo))}@{sanitize_log_message(str(tag))}: {sanitize_log_message(str(e))}"
            )
            return None
        except (ValueError, KeyError) as e:
            logger.warning(
                f"Invalid GitHub release data for {sanitize_log_message(str(owner_repo))}@{sanitize_log_message(str(tag))}: {sanitize_log_message(str(e))}"
            )
            return None


class ChangelogClassifier:
    """Classify changelog text into reason types."""

    BUGFIX_PATTERNS = re.compile(r"\b(fix(?:es|ed)?|bug|patch)\b", re.IGNORECASE)
    FEATURE_PATTERNS = re.compile(
        r"\b(add(?:ed)?|new |feature|improve)\b", re.IGNORECASE
    )
    MAINT_PATTERNS = re.compile(
        r"\b(maintenance|refactor|deps|dependency|cleanup)\b", re.IGNORECASE
    )
    SECURITY_PATTERNS = re.compile(r"\b(cve|security|vuln)\b", re.IGNORECASE)

    @classmethod
    def classify(cls, text: str) -> Tuple[str, str]:
        reason_type = "unknown"
        summary = cls._extract_summary(text)

        if cls.SECURITY_PATTERNS.search(text):
            reason_type = "security"
        elif cls.BUGFIX_PATTERNS.search(text):
            reason_type = "bugfix"
        elif cls.FEATURE_PATTERNS.search(text):
            reason_type = "feature"
        elif cls.MAINT_PATTERNS.search(text):
            reason_type = "maintenance"

        return reason_type, summary

    @staticmethod
    def _extract_summary(text: str) -> str:
        """Extract a brief summary from changelog text.

        Returns a short, generic summary based on the update type.
        The full details are shown in the expandable Release Notes section.
        """
        # Just return a generic summary - the full changelog is shown in the expandable section
        # This prevents duplication of content between summary and release notes
        return "See release notes for details"
