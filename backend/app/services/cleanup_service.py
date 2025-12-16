"""Docker cleanup service for pruning unused containers and images."""

import asyncio
import json
import logging
import re
from typing import Any, Dict, List, Optional
from app.utils.security import sanitize_log_message

logger = logging.getLogger(__name__)


class CleanupService:
    """Service for cleaning up Docker containers and images."""

    @staticmethod
    def _parse_bytes(size_str: str) -> int:
        """Parse byte size string like '512MB', '1.5GB' to bytes."""
        if not size_str or size_str == "N/A":
            return 0

        size_str = size_str.strip()

        units = {
            'B': 1,
            'KB': 1000,
            'MB': 1000**2,
            'GB': 1000**3,
            'TB': 1000**4,
            'KIB': 1024,
            'MIB': 1024**2,
            'GIB': 1024**3,
            'TIB': 1024**4,
        }

        try:
            match = re.match(r'^([\d.]+)\s*([A-Za-z]+)?$', size_str)
            if not match:
                return 0

            number = float(match.group(1))
            unit = match.group(2) if match.group(2) else 'B'
            unit = unit.upper()

            multiplier = units.get(unit, 1)
            return int(number * multiplier)
        except (ValueError, AttributeError):
            return 0

    @staticmethod
    def _format_bytes(size_bytes: int) -> str:
        """Format bytes to human readable string."""
        if size_bytes == 0:
            return "0 B"

        units = ["B", "KB", "MB", "GB", "TB"]
        unit_index = 0
        size = float(size_bytes)

        while size >= 1000 and unit_index < len(units) - 1:
            size /= 1000
            unit_index += 1

        return f"{size:.2f} {units[unit_index]}"

    @staticmethod
    def _matches_exclude_pattern(name: str, patterns: List[str]) -> bool:
        """Check if a container/image name matches any exclude pattern."""
        if not patterns:
            return False

        name_lower = name.lower()
        for pattern in patterns:
            pattern = pattern.strip().lower()
            if not pattern:
                continue
            if pattern in name_lower:
                return True
        return False

    @staticmethod
    async def get_disk_usage() -> Dict[str, Any]:
        """Get Docker disk usage statistics.

        Returns:
            Dictionary with disk usage stats for images, containers, volumes
        """
        try:
            process = await asyncio.create_subprocess_exec(
                "docker", "system", "df", "-v", "--format", "{{json .}}",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=30.0
            )

            if process.returncode != 0:
                error_msg = stderr.decode().strip()
                logger.error(f"Failed to get disk usage: {sanitize_log_message(str(error_msg))}")
                return {"error": error_msg}

            # Parse JSON output (one per line for different resource types)
            lines = stdout.decode().strip().split('\n')
            result = {
                "images": {"count": 0, "size": 0, "reclaimable": 0},
                "containers": {"count": 0, "size": 0, "reclaimable": 0},
                "volumes": {"count": 0, "size": 0, "reclaimable": 0},
                "build_cache": {"count": 0, "size": 0, "reclaimable": 0},
            }

            for line in lines:
                if not line.strip():
                    continue
                try:
                    data = json.loads(line)
                    resource_type = data.get("Type", "").lower()

                    if "image" in resource_type:
                        result["images"] = {
                            "count": data.get("TotalCount", 0),
                            "size": CleanupService._parse_bytes(data.get("Size", "0B")),
                            "reclaimable": CleanupService._parse_bytes(data.get("Reclaimable", "0B")),
                        }
                    elif "container" in resource_type:
                        result["containers"] = {
                            "count": data.get("TotalCount", 0),
                            "size": CleanupService._parse_bytes(data.get("Size", "0B")),
                            "reclaimable": CleanupService._parse_bytes(data.get("Reclaimable", "0B")),
                        }
                    elif "volume" in resource_type:
                        result["volumes"] = {
                            "count": data.get("TotalCount", 0),
                            "size": CleanupService._parse_bytes(data.get("Size", "0B")),
                            "reclaimable": CleanupService._parse_bytes(data.get("Reclaimable", "0B")),
                        }
                    elif "build" in resource_type:
                        result["build_cache"] = {
                            "count": data.get("TotalCount", 0),
                            "size": CleanupService._parse_bytes(data.get("Size", "0B")),
                            "reclaimable": CleanupService._parse_bytes(data.get("Reclaimable", "0B")),
                        }
                except json.JSONDecodeError:
                    continue

            # Add formatted sizes
            for key in result:
                if "size" in result[key]:
                    result[key]["size_formatted"] = CleanupService._format_bytes(result[key]["size"])
                if "reclaimable" in result[key]:
                    result[key]["reclaimable_formatted"] = CleanupService._format_bytes(result[key]["reclaimable"])

            return result

        except asyncio.TimeoutError:
            logger.error("Timeout getting disk usage")
            return {"error": "Timeout getting disk usage"}
        except (OSError, PermissionError) as e:
            logger.error(f"Process execution error: {sanitize_log_message(str(e))}")
            return {"error": str(e)}

    @staticmethod
    async def get_dangling_images(exclude_patterns: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """Get list of dangling (untagged) images.

        Args:
            exclude_patterns: List of patterns to exclude from results

        Returns:
            List of dangling images with their details
        """
        try:
            process = await asyncio.create_subprocess_exec(
                "docker", "images", "-f", "dangling=true",
                "--format", "{{json .}}",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=30.0
            )

            if process.returncode != 0:
                return []

            images = []
            for line in stdout.decode().strip().split('\n'):
                if not line.strip():
                    continue
                try:
                    data = json.loads(line)
                    image_id = data.get("ID", "")

                    # Check exclude patterns (for dangling, check against ID since no tag)
                    if exclude_patterns and CleanupService._matches_exclude_pattern(image_id, exclude_patterns):
                        continue

                    images.append({
                        "id": image_id,
                        "size": data.get("Size", "0B"),
                        "created": data.get("CreatedSince", ""),
                    })
                except json.JSONDecodeError:
                    continue

            return images

        except (asyncio.TimeoutError, OSError, PermissionError) as e:
            logger.error(f"Error getting dangling images: {sanitize_log_message(str(e))}")
            return []

    @staticmethod
    async def get_exited_containers(exclude_patterns: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """Get list of exited/dead containers.

        Args:
            exclude_patterns: List of patterns to exclude from results

        Returns:
            List of exited containers with their details
        """
        try:
            process = await asyncio.create_subprocess_exec(
                "docker", "ps", "-a",
                "-f", "status=exited",
                "-f", "status=dead",
                "-f", "status=created",
                "--format", "{{json .}}",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=30.0
            )

            if process.returncode != 0:
                return []

            containers = []
            for line in stdout.decode().strip().split('\n'):
                if not line.strip():
                    continue
                try:
                    data = json.loads(line)
                    name = data.get("Names", "")
                    image = data.get("Image", "")

                    # Check exclude patterns against name and image
                    if exclude_patterns:
                        if CleanupService._matches_exclude_pattern(name, exclude_patterns):
                            continue
                        if CleanupService._matches_exclude_pattern(image, exclude_patterns):
                            continue

                    containers.append({
                        "id": data.get("ID", ""),
                        "name": name,
                        "image": image,
                        "status": data.get("Status", ""),
                        "created": data.get("CreatedAt", ""),
                    })
                except json.JSONDecodeError:
                    continue

            return containers

        except (asyncio.TimeoutError, OSError, PermissionError) as e:
            logger.error(f"Error getting exited containers: {sanitize_log_message(str(e))}")
            return []

    @staticmethod
    async def get_old_images(
        days: int = 7,
        exclude_patterns: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """Get list of images older than specified days that aren't in use.

        Args:
            days: Age threshold in days
            exclude_patterns: List of patterns to exclude from results

        Returns:
            List of old unused images
        """
        hours = days * 24
        try:
            process = await asyncio.create_subprocess_exec(
                "docker", "images", "-a",
                "-f", f"until={hours}h",
                "--format", "{{json .}}",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=30.0
            )

            if process.returncode != 0:
                return []

            images = []
            for line in stdout.decode().strip().split('\n'):
                if not line.strip():
                    continue
                try:
                    data = json.loads(line)
                    repo = data.get("Repository", "<none>")
                    tag = data.get("Tag", "<none>")
                    full_name = f"{repo}:{tag}" if repo != "<none>" else data.get("ID", "")

                    # Check exclude patterns
                    if exclude_patterns and CleanupService._matches_exclude_pattern(full_name, exclude_patterns):
                        continue

                    images.append({
                        "id": data.get("ID", ""),
                        "repository": repo,
                        "tag": tag,
                        "size": data.get("Size", "0B"),
                        "created": data.get("CreatedSince", ""),
                    })
                except json.JSONDecodeError:
                    continue

            return images

        except (asyncio.TimeoutError, OSError, PermissionError) as e:
            logger.error(f"Error getting old images: {sanitize_log_message(str(e))}")
            return []

    @staticmethod
    async def get_cleanup_preview(
        mode: str = "dangling",
        days: int = 7,
        exclude_patterns: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """Preview what would be cleaned up without removing anything.

        Args:
            mode: Cleanup mode ('dangling', 'moderate', 'aggressive')
            days: Age threshold for aggressive mode
            exclude_patterns: Patterns to exclude

        Returns:
            Dictionary with preview of what would be cleaned
        """
        result = {
            "mode": mode,
            "exclude_patterns": exclude_patterns or [],
            "dangling_images": [],
            "exited_containers": [],
            "old_images": [],
            "totals": {
                "images": 0,
                "containers": 0,
            }
        }

        # Always get dangling images
        result["dangling_images"] = await CleanupService.get_dangling_images(exclude_patterns)
        result["totals"]["images"] = len(result["dangling_images"])

        # Get containers for moderate and aggressive modes
        if mode in ["moderate", "aggressive"]:
            result["exited_containers"] = await CleanupService.get_exited_containers(exclude_patterns)
            result["totals"]["containers"] = len(result["exited_containers"])

        # Get old images for aggressive mode
        if mode == "aggressive":
            result["old_images"] = await CleanupService.get_old_images(days, exclude_patterns)
            # Add old images to total (excluding already counted dangling)
            dangling_ids = {img["id"] for img in result["dangling_images"]}
            unique_old = [img for img in result["old_images"] if img["id"] not in dangling_ids]
            result["totals"]["images"] += len(unique_old)

        return result

    @staticmethod
    async def prune_dangling_images() -> Dict[str, Any]:
        """Remove all dangling (untagged) images.

        Returns:
            Dictionary with cleanup results
        """
        try:
            process = await asyncio.create_subprocess_exec(
                "docker", "image", "prune", "-f",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=300.0
            )

            if process.returncode != 0:
                error_msg = stderr.decode().strip()
                logger.error(f"Failed to prune dangling images: {sanitize_log_message(str(error_msg))}")
                return {"success": False, "error": error_msg, "images_removed": 0, "space_reclaimed": 0}

            # Parse output for space reclaimed
            output = stdout.decode()
            space_reclaimed = 0
            images_removed = 0

            # Count deleted images
            for line in output.split('\n'):
                if line.startswith("deleted:") or (line and not line.startswith("Total")):
                    if "sha256:" in line or len(line.strip()) == 12:
                        images_removed += 1

            # Parse space reclaimed
            match = re.search(r'Total reclaimed space:\s*([\d.]+\s*[A-Za-z]+)', output)
            if match:
                space_reclaimed = CleanupService._parse_bytes(match.group(1))

            logger.info(f"Pruned {sanitize_log_message(str(images_removed))} dangling images, reclaimed {sanitize_log_message(str(CleanupService._format_bytes(space_reclaimed)))}")

            return {
                "success": True,
                "images_removed": images_removed,
                "space_reclaimed": space_reclaimed,
                "space_reclaimed_formatted": CleanupService._format_bytes(space_reclaimed),
            }

        except asyncio.TimeoutError:
            logger.error("Timeout pruning dangling images")
            return {"success": False, "error": "Timeout", "images_removed": 0, "space_reclaimed": 0}
        except (OSError, PermissionError) as e:
            logger.error(f"Process execution error: {sanitize_log_message(str(e))}")
            return {"success": False, "error": str(e), "images_removed": 0, "space_reclaimed": 0}

    @staticmethod
    async def prune_exited_containers(exclude_patterns: Optional[List[str]] = None) -> Dict[str, Any]:
        """Remove exited/dead containers.

        Args:
            exclude_patterns: List of patterns to exclude from cleanup

        Returns:
            Dictionary with cleanup results
        """
        # If we have exclude patterns, we need to remove containers individually
        if exclude_patterns:
            containers = await CleanupService.get_exited_containers(exclude_patterns)

            if not containers:
                return {"success": True, "containers_removed": 0}

            removed = 0
            errors = []

            for container in containers:
                try:
                    process = await asyncio.create_subprocess_exec(
                        "docker", "rm", container["id"],
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    )

                    await asyncio.wait_for(process.communicate(), timeout=30.0)

                    if process.returncode == 0:
                        removed += 1
                        logger.debug(f"Removed container: {sanitize_log_message(str(container['name']))}")
                    else:
                        errors.append(container["name"])

                except (asyncio.TimeoutError, OSError, PermissionError) as e:
                    errors.append(f"{container['name']}: {e}")

            logger.info(f"Removed {sanitize_log_message(str(removed))} exited containers")

            return {
                "success": len(errors) == 0,
                "containers_removed": removed,
                "errors": errors if errors else None,
            }

        # No exclude patterns, use docker container prune
        try:
            process = await asyncio.create_subprocess_exec(
                "docker", "container", "prune", "-f",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=300.0
            )

            if process.returncode != 0:
                error_msg = stderr.decode().strip()
                logger.error(f"Failed to prune containers: {sanitize_log_message(str(error_msg))}")
                return {"success": False, "error": error_msg, "containers_removed": 0}

            # Count removed containers from output
            output = stdout.decode()
            containers_removed = 0
            for line in output.split('\n'):
                line = line.strip()
                if line and not line.startswith("Total") and not line.startswith("Deleted"):
                    containers_removed += 1

            logger.info(f"Pruned {sanitize_log_message(str(containers_removed))} exited containers")

            return {
                "success": True,
                "containers_removed": containers_removed,
            }

        except asyncio.TimeoutError:
            logger.error("Timeout pruning containers")
            return {"success": False, "error": "Timeout", "containers_removed": 0}
        except (OSError, PermissionError) as e:
            logger.error(f"Process execution error: {sanitize_log_message(str(e))}")
            return {"success": False, "error": str(e), "containers_removed": 0}

    @staticmethod
    async def cleanup_old_images(
        days: int = 7,
        exclude_patterns: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """Remove images older than X days that aren't in use.

        Args:
            days: Age threshold in days
            exclude_patterns: Patterns to exclude

        Returns:
            Dictionary with cleanup results
        """
        hours = days * 24

        # If we have exclude patterns, get images first and filter
        if exclude_patterns:
            old_images = await CleanupService.get_old_images(days, exclude_patterns)

            if not old_images:
                return {"success": True, "images_removed": 0, "space_reclaimed": 0}

            removed = 0
            space_reclaimed = 0
            errors = []

            for image in old_images:
                try:
                    # Get image size before removal
                    size = CleanupService._parse_bytes(image.get("size", "0B"))

                    process = await asyncio.create_subprocess_exec(
                        "docker", "rmi", image["id"],
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    )

                    _, stderr_out = await asyncio.wait_for(process.communicate(), timeout=60.0)

                    if process.returncode == 0:
                        removed += 1
                        space_reclaimed += size
                        logger.debug(f"Removed old image: {sanitize_log_message(str(image.get('repository', image['id'])))}")
                    else:
                        # Image might be in use, skip silently
                        stderr_text = stderr_out.decode().strip()
                        if "image is being used" not in stderr_text and "image has dependent" not in stderr_text:
                            errors.append(f"{image['id']}: {stderr_text}")

                except (asyncio.TimeoutError, OSError, PermissionError) as e:
                    errors.append(f"{image['id']}: {e}")

            logger.info(f"Removed {sanitize_log_message(str(removed))} old images, reclaimed {sanitize_log_message(str(CleanupService._format_bytes(space_reclaimed)))}")

            return {
                "success": len(errors) == 0,
                "images_removed": removed,
                "space_reclaimed": space_reclaimed,
                "space_reclaimed_formatted": CleanupService._format_bytes(space_reclaimed),
                "errors": errors if errors else None,
            }

        # No exclude patterns, use docker image prune with filter
        try:
            process = await asyncio.create_subprocess_exec(
                "docker", "image", "prune", "-a", "-f",
                "--filter", f"until={hours}h",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=300.0
            )

            if process.returncode != 0:
                error_msg = stderr.decode().strip()
                logger.error(f"Failed to prune old images: {sanitize_log_message(str(error_msg))}")
                return {"success": False, "error": error_msg, "images_removed": 0, "space_reclaimed": 0}

            output = stdout.decode()
            space_reclaimed = 0
            images_removed = 0

            # Count deleted images
            for line in output.split('\n'):
                if "deleted:" in line.lower() or "untagged:" in line.lower():
                    images_removed += 1

            # Parse space reclaimed
            match = re.search(r'Total reclaimed space:\s*([\d.]+\s*[A-Za-z]+)', output)
            if match:
                space_reclaimed = CleanupService._parse_bytes(match.group(1))

            logger.info(f"Pruned {sanitize_log_message(str(images_removed))} old images (>{sanitize_log_message(str(days))} days), reclaimed {sanitize_log_message(str(CleanupService._format_bytes(space_reclaimed)))}")

            return {
                "success": True,
                "images_removed": images_removed,
                "space_reclaimed": space_reclaimed,
                "space_reclaimed_formatted": CleanupService._format_bytes(space_reclaimed),
            }

        except asyncio.TimeoutError:
            logger.error("Timeout pruning old images")
            return {"success": False, "error": "Timeout", "images_removed": 0, "space_reclaimed": 0}
        except (OSError, PermissionError) as e:
            logger.error(f"Process execution error: {sanitize_log_message(str(e))}")
            return {"success": False, "error": str(e), "images_removed": 0, "space_reclaimed": 0}

    @staticmethod
    async def run_cleanup(
        mode: str = "dangling",
        days: int = 7,
        exclude_patterns: Optional[List[str]] = None,
        cleanup_containers: bool = True,
    ) -> Dict[str, Any]:
        """Run cleanup based on configured mode.

        Args:
            mode: Cleanup mode ('dangling', 'moderate', 'aggressive')
            days: Age threshold for aggressive mode
            exclude_patterns: Patterns to exclude
            cleanup_containers: Whether to also clean up containers

        Returns:
            Combined cleanup results
        """
        result = {
            "success": True,
            "mode": mode,
            "images_removed": 0,
            "containers_removed": 0,
            "space_reclaimed": 0,
            "errors": [],
        }

        # Always prune dangling images
        dangling_result = await CleanupService.prune_dangling_images()
        result["images_removed"] += dangling_result.get("images_removed", 0)
        result["space_reclaimed"] += dangling_result.get("space_reclaimed", 0)
        if not dangling_result.get("success"):
            result["errors"].append(f"Dangling images: {dangling_result.get('error')}")

        # Moderate mode: also clean containers
        if mode in ["moderate", "aggressive"] and cleanup_containers:
            container_result = await CleanupService.prune_exited_containers(exclude_patterns)
            result["containers_removed"] = container_result.get("containers_removed", 0)
            if not container_result.get("success"):
                result["errors"].append(f"Containers: {container_result.get('error')}")
            if container_result.get("errors"):
                result["errors"].extend(container_result["errors"])

        # Aggressive mode: also clean old images
        if mode == "aggressive":
            old_result = await CleanupService.cleanup_old_images(days, exclude_patterns)
            result["images_removed"] += old_result.get("images_removed", 0)
            result["space_reclaimed"] += old_result.get("space_reclaimed", 0)
            if not old_result.get("success"):
                result["errors"].append(f"Old images: {old_result.get('error')}")
            if old_result.get("errors"):
                result["errors"].extend(old_result["errors"])

        result["space_reclaimed_formatted"] = CleanupService._format_bytes(result["space_reclaimed"])
        result["success"] = len(result["errors"]) == 0

        if not result["errors"]:
            del result["errors"]

        logger.info(
            f"Cleanup complete ({mode} mode): "
            f"{result['images_removed']} images, "
            f"{result['containers_removed']} containers, "
            f"{result['space_reclaimed_formatted']} reclaimed"
        )

        return result


# Singleton instance
cleanup_service = CleanupService()
