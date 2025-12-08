"""Schemas for vulnerability scanning endpoints."""

from datetime import datetime
from typing import List, Dict, Optional
from pydantic import BaseModel, Field, ConfigDict


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
    cves: List[str]
    risk_score: Optional[float] = None
    status: str


class ScanSummarySchema(BaseModel):
    """Aggregate vulnerability scan statistics across all containers."""

    model_config = ConfigDict(from_attributes=True)

    total_containers_scanned: int
    total_vulnerabilities: int
    severity_breakdown: Dict[str, int]  # {"critical": X, "high": Y, "medium": Z, "low": W}
    last_scan: Optional[datetime] = None
    containers_at_risk: int  # Containers with critical or high vulnerabilities
