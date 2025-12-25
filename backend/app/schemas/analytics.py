"""Analytics schemas for TideWatch dashboards."""

from typing import List

from pydantic import BaseModel


class FrequencyPoint(BaseModel):
    date: str
    count: int


class VulnerabilityPoint(BaseModel):
    date: str
    cves_fixed: int


class DistributionItem(BaseModel):
    label: str
    value: int


class AnalyticsSummary(BaseModel):
    period_days: int
    total_updates: int
    successful_updates: int
    failed_updates: int
    update_frequency: List[FrequencyPoint]
    vulnerability_trends: List[VulnerabilityPoint]
    policy_distribution: List[DistributionItem]
    avg_update_duration_seconds: float
    total_cves_fixed: int
