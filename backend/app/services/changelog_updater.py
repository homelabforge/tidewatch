"""Service for automatically updating CHANGELOG.md files when dependencies are updated."""

import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)


class ChangelogUpdater:
    """Service for updating CHANGELOG.md files with dependency update entries."""

    # Pattern to match the [Unreleased] section header
    UNRELEASED_PATTERN = re.compile(r"^## \[Unreleased\]", re.IGNORECASE)

    # Pattern to match any version section header (to know where Unreleased ends)
    VERSION_SECTION_PATTERN = re.compile(r"^## \[\d+\.\d+\.\d+\]")

    # Pattern to match the ### Changed subsection
    CHANGED_SECTION_PATTERN = re.compile(r"^### Changed\s*$", re.IGNORECASE)

    # Pattern to match any ### subsection (Added, Changed, Fixed, etc.)
    SUBSECTION_PATTERN = re.compile(r"^### \w+")

    @staticmethod
    def extract_project_root(dependency_path: str, base_path: Path) -> Path | None:
        """
        Extract project root from a dependency path.

        Args:
            dependency_path: Relative path like 'tidewatch/backend/Dockerfile'
            base_path: Base path where projects are mounted (e.g., /projects)

        Returns:
            Path to project root, or None if cannot be determined
        """
        if not dependency_path:
            return None

        # Split the path and get the first component (project name)
        parts = Path(dependency_path).parts
        if not parts:
            return None

        project_name = parts[0]
        project_root = base_path / project_name

        # Check if CHANGELOG.md exists at project root
        changelog_path = project_root / "CHANGELOG.md"
        if changelog_path.exists():
            return project_root

        return None

    @staticmethod
    def update_changelog(
        project_root: Path,
        dependency_name: str,
        old_version: str,
        new_version: str,
        dependency_type: str = "app_dependency",
    ) -> bool:
        """
        Update CHANGELOG.md with a dependency update entry.

        Adds an entry under the [Unreleased] section's ### Changed subsection.
        Creates the ### Changed subsection if it doesn't exist.

        Args:
            project_root: Path to the project root directory
            dependency_name: Name of the dependency that was updated
            old_version: Previous version
            new_version: New version
            dependency_type: Type of dependency (dockerfile, http_server, app_dependency)

        Returns:
            True if changelog was updated successfully, False otherwise
        """
        changelog_path = project_root / "CHANGELOG.md"

        if not changelog_path.exists():
            logger.debug(f"No CHANGELOG.md found at {changelog_path}")
            return False

        try:
            # Read the current changelog
            content = changelog_path.read_text(encoding="utf-8")
            lines = content.splitlines(keepends=True)

            # Format the entry
            entry = f"- **{dependency_name}**: {old_version} → {new_version}\n"

            # Check if this exact entry already exists (avoid duplicates)
            if entry.strip() in content:
                logger.debug(f"Entry already exists in changelog: {entry.strip()}")
                return True

            # Find the [Unreleased] section
            unreleased_idx = None
            for i, line in enumerate(lines):
                if ChangelogUpdater.UNRELEASED_PATTERN.match(line.strip()):
                    unreleased_idx = i
                    break

            if unreleased_idx is None:
                logger.warning(f"No [Unreleased] section found in {changelog_path}")
                return False

            # Find where to insert the entry
            # Look for ### Changed section within [Unreleased]
            changed_idx = None

            for i in range(unreleased_idx + 1, len(lines)):
                line = lines[i].strip()

                # Check if we've hit the next version section (end of Unreleased)
                if ChangelogUpdater.VERSION_SECTION_PATTERN.match(line):
                    break

                # Check if this is the ### Changed section
                if ChangelogUpdater.CHANGED_SECTION_PATTERN.match(line):
                    changed_idx = i
                    break

            # Determine where to insert
            if changed_idx is not None:
                # Find the last entry in ### Changed section to append after it
                insert_idx = changed_idx + 1

                # Skip past all existing entries (lines starting with "- ")
                while insert_idx < len(lines):
                    line = lines[insert_idx].strip()
                    if line.startswith("- "):
                        insert_idx += 1
                        continue
                    # Stop at blank line, next section, or next version
                    break

                # Insert the entry at the end of existing entries
                lines.insert(insert_idx, entry)

                # Ensure blank line before next section if needed
                # Check if the line after our inserted entry (now at insert_idx + 1) is a section header
                next_line_idx = insert_idx + 1
                if next_line_idx < len(lines):
                    next_line = lines[next_line_idx].strip()
                    # If it's a section header and there's no blank line, add one
                    if (
                        ChangelogUpdater.VERSION_SECTION_PATTERN.match(next_line)
                        or ChangelogUpdater.SUBSECTION_PATTERN.match(next_line)
                    ):
                        lines.insert(next_line_idx, "\n")

            else:
                # Need to create ### Changed section
                # Insert after [Unreleased] header
                insert_idx = unreleased_idx + 1

                # Skip one blank line after [Unreleased] if it exists
                if insert_idx < len(lines) and not lines[insert_idx].strip():
                    insert_idx += 1

                # Build the new section content
                # We want: ### Changed\n- entry\n\n (with blank line after for separation)
                new_section = "### Changed\n" + entry + "\n"
                lines.insert(insert_idx, new_section)

            # Write back
            changelog_path.write_text("".join(lines), encoding="utf-8")

            logger.info(
                f"Updated CHANGELOG.md for {project_root.name}: "
                f"{dependency_name} {old_version} → {new_version}"
            )
            return True

        except Exception as e:
            logger.error(f"Failed to update changelog at {changelog_path}: {e}")
            return False
