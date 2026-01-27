"""Schemas for vulnerability scanning endpoints."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ScanResultSchema(BaseModel):
    """Individual container vulnerability scan result."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: int
    container_id: int
    container_name: str
    scanned_at: datetime
    total_vulns: int
    critical: int
    high: int
    medium: int
    low: int
    cves: list[str]
    risk_score: float | None = None
    status: str


class ScanSummarySchema(BaseModel):
    """Aggregate vulnerability scan statistics across all containers."""

    model_config = ConfigDict(from_attributes=True)

    total_containers_scanned: int
    total_vulnerabilities: int
    severity_breakdown: dict[
        str, int
    ]  # {"critical": X, "high": Y, "medium": Z, "low": W}
    last_scan: datetime | None = None
    containers_at_risk: int  # Containers with critical or high vulnerabilities
