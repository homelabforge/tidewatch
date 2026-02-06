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

    # Pattern to match any ### subsection (Added, Changed, Fixed, etc.)
    SUBSECTION_PATTERN = re.compile(r"^### \w+")

    # Mapping from dependency types to section headers
    SECTION_HEADERS = {
        "http_server": "### HTTP Servers",
        "dockerfile": "### Dockerfile Dependencies",
        "app_dependency_production": "### App Dependencies",
        "app_dependency_optional": "### App Dependencies",
        "app_dependency_peer": "### App Dependencies",
        "app_dependency_development": "### Dev Dependencies",
    }

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
        app_dependency_type: str = "production",
    ) -> bool:
        """
        Update CHANGELOG.md with a dependency update entry.

        Adds an entry under the [Unreleased] section's appropriate subsection based on dependency type.
        Creates the subsection if it doesn't exist.

        Args:
            project_root: Path to the project root directory
            dependency_name: Name of the dependency that was updated
            old_version: Previous version
            new_version: New version
            dependency_type: Type of dependency (dockerfile, http_server, app_dependency)
            app_dependency_type: For app_dependency, the specific type (production, development, optional, peer)

        Returns:
            True if changelog was updated successfully, False otherwise
        """
        changelog_path = project_root / "CHANGELOG.md"

        if not changelog_path.exists():
            logger.debug(f"No CHANGELOG.md found at {changelog_path}")
            return False

        try:
            # Determine the section header based on dependency type
            if dependency_type == "app_dependency":
                section_key = f"app_dependency_{app_dependency_type}"
            else:
                section_key = dependency_type

            section_header = ChangelogUpdater.SECTION_HEADERS.get(section_key, "### Changed")

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
            # Look for the target section within [Unreleased]
            section_idx = None

            for i in range(unreleased_idx + 1, len(lines)):
                line = lines[i].strip()

                # Check if we've hit the next version section (end of Unreleased)
                if ChangelogUpdater.VERSION_SECTION_PATTERN.match(line):
                    break

                # Check if this is the target section
                if line == section_header:
                    section_idx = i
                    break

            # Determine where to insert
            if section_idx is not None:
                # Find the last entry in the section to append after it
                insert_idx = section_idx + 1

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
                    if ChangelogUpdater.VERSION_SECTION_PATTERN.match(
                        next_line
                    ) or ChangelogUpdater.SUBSECTION_PATTERN.match(next_line):
                        lines.insert(next_line_idx, "\n")

            else:
                # Need to create the section
                # Insert after [Unreleased] header
                insert_idx = unreleased_idx + 1

                # Skip one blank line after [Unreleased] if it exists
                if insert_idx < len(lines) and not lines[insert_idx].strip():
                    insert_idx += 1

                # Build the new section content
                # We want: ### Section\n- entry\n\n (with blank line after for separation)
                new_section = section_header + "\n" + entry + "\n"
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
